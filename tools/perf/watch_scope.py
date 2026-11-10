"""MMHand 上位机运行监视器：卡顿 / 帧率 / 刷新率 / 资源占用。

两条数据通道：

1. **外部探针**（不需要改上位机、可监视已在运行的实例）
   - UI 卡顿：向主窗发 WM_NULL 并测往返耗时（SendMessageTimeout）。线程被长
     回调阻塞时这个值会直接涨起来，等于"点一下按钮多久才有响应"。
   - 进程 CPU / 工作集内存 / GDI·USER 句柄 / 句柄总数（用于发现泄漏型卡顿）。
   - 显示器刷新率（EnumDisplaySettings）。

2. **内部遥测**（可选，需要上位机带 MMHAND_TELEMETRY 启动）
   - 每秒一行 JSONL：主图 fps、paint 毫秒、点数密度、事件循环最大停顿、
     表格刷新 Hz、上行队列积压、编码器/遥测 Hz、张力龄期、闭环状态。

用法（推荐：一条命令托管启动 + 监视）：
    .venv\\Scripts\\python.exe tools\\perf\\watch_scope.py --launch

只监视已开着的窗口：
    .venv\\Scripts\\python.exe tools\\perf\\watch_scope.py

让脚本自己起上位机时，会自动把 MMHAND_TELEMETRY 指到
run_data/telemetry/scope_live.jsonl；你自己手动启动的话，先设环境变量：
    set MMHAND_TELEMETRY=%CD%\\run_data\\telemetry\\scope_live.jsonl
    .venv\\Scripts\\python.exe mmhand_scope.py
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_TELEMETRY = REPO / "run_data" / "telemetry" / "scope_live.jsonl"
DEFAULT_CSV_DIR = REPO / "run_data" / "telemetry"
TITLE_HINT = "MMHand"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
APP = REPO / "mmhand_scope.py"

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

WM_NULL = 0x0000
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                            ctypes.POINTER(wintypes.DWORD)]
user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.GetGuiResources.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FILETIME)] * 4
kernel32.GetProcessHandleCount.argtypes = [wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.DWORD)]
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                       wintypes.DWORD]


def _ft_to_s(ft: FILETIME) -> float:
    return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7


def find_window(hint: str = TITLE_HINT) -> tuple[int, str] | None:
    """返回 (hwnd, title)；跳过控制台窗口，避免拿到启动器外壳。"""
    found: list[tuple[int, str]] = []

    @WNDENUMPROC
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if hint.lower() not in title.lower():
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
            return True
        found.append((int(hwnd), title))
        return False

    user32.EnumWindows(_cb, 0)
    return found[0] if found else None


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def ui_stall_ms(hwnd: int, timeout_ms: int = 500) -> float | None:
    """WM_NULL 往返毫秒；超时（窗口无响应）返回 None。"""
    result = ctypes.c_size_t(0)
    t0 = time.perf_counter()
    ok = user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0,
                                    SMTO_BLOCK | SMTO_ABORTIFHUNG,
                                    timeout_ms, ctypes.byref(result))
    if not ok:
        return None
    return (time.perf_counter() - t0) * 1000.0


def display_hz() -> int | None:
    """当前显示器刷新率（GetDeviceCaps VREFRESH，比重构 DEVMODE 稳）。"""
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        hz = int(gdi32.GetDeviceCaps(hdc, 116))   # VREFRESH
        return hz if hz > 1 else None
    finally:
        user32.ReleaseDC(None, hdc)


class ProcProbe:
    """CPU / 内存 / 句柄采样（同一进程句柄复用）。

    权限说明：只给 PROCESS_QUERY_LIMITED_INFORMATION 时 GetProcessMemoryInfo /
    GetGuiResources 会失败（表现为 4MB、GDI=0 这种假数据），所以优先要
    QUERY_INFORMATION|VM_READ；失败再退回 limited，并把取不到的项标 None。
    """

    QUERY_FULL = 0x0400 | 0x0010      # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    QUERY_LIMITED = 0x1000

    def __init__(self, pid: int):
        self.pid = pid
        self.handle = kernel32.OpenProcess(self.QUERY_FULL, False, pid)
        self.limited_only = False
        if not self.handle:
            self.handle = kernel32.OpenProcess(self.QUERY_LIMITED, False, pid)
            self.limited_only = bool(self.handle)
        self.prev_cpu = None
        self.prev_t = None
        if not self.handle:
            raise OSError(f"OpenProcess 失败（pid={pid}, err={ctypes.get_last_error()}）")

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def sample(self) -> dict:
        out = {"cpu_pct": None, "rss_mb": None, "gdi": None,
               "user_obj": None, "handles": None}
        if not self.handle:
            return out
        now = time.perf_counter()
        c, e, k, u = (FILETIME(), FILETIME(), FILETIME(), FILETIME())
        if kernel32.GetProcessTimes(self.handle, ctypes.byref(c), ctypes.byref(e),
                                    ctypes.byref(k), ctypes.byref(u)):
            cpu_s = _ft_to_s(k) + _ft_to_s(u)
            if self.prev_cpu is not None and now > self.prev_t:
                out["cpu_pct"] = (cpu_s - self.prev_cpu) / (now - self.prev_t) * 100.0
            self.prev_cpu, self.prev_t = cpu_s, now
        if not self.limited_only:
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            if psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(pmc), pmc.cb):
                mb = pmc.WorkingSetSize / (1024 * 1024)
                out["rss_mb"] = mb if mb > 0 else None
            gdi = int(user32.GetGuiResources(self.handle, 0))
            usr = int(user32.GetGuiResources(self.handle, 1))
            out["gdi"] = gdi or None
            out["user_obj"] = usr or None
        hc = wintypes.DWORD(0)
        if kernel32.GetProcessHandleCount(self.handle, ctypes.byref(hc)):
            out["handles"] = int(hc.value) or None
        return out


class TeleTail:
    """按偏移增量读取内部遥测 JSONL，只保留最新一行。"""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self.pos = 0
        self.last: dict | None = None

    def read(self) -> dict | None:
        if self.path is None or not self.path.exists():
            return self.last
        try:
            with self.path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                if size < self.pos:
                    self.pos = 0          # 文件被重建/截断
                fh.seek(self.pos)
                chunk = fh.read()
                self.pos = fh.tell()
        except OSError:
            return self.last
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self.last = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
        return self.last


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MMHand 上位机运行监视器")
    ap.add_argument("--title", default=TITLE_HINT, help="主窗标题关键字（默认 MMHand）")
    ap.add_argument("--pid", type=int, default=0, help="直接指定进程 id（免找窗口）")
    ap.add_argument("--interval", type=float, default=1.0, help="采样间隔秒（默认 1.0）")
    ap.add_argument("--seconds", type=float, default=0.0, help="监视多久后自动汇总（0=直到 Ctrl+C）")
    ap.add_argument("--stall-timeout", type=int, default=500, help="WM_NULL 超时毫秒")
    ap.add_argument("--telemetry", default="", help="内部遥测 JSONL 路径（默认自动找）")
    ap.add_argument("--csv", default="", help="CSV 输出路径（默认 run_data/telemetry/watch_*.csv）")
    ap.add_argument("--launch", action="store_true", help="由脚本拉起上位机并注入遥测")
    ap.add_argument("--launch-args", default="", help="透传给 mmhand_scope.py 的参数")
    ap.add_argument("--keep-open", action="store_true",
                    help="监视结束后不关闭 --launch 拉起的上位机（默认会关掉）")
    ap.add_argument("--quiet", action="store_true", help="不打印逐秒行，只出汇总")
    args = ap.parse_args(argv)

    tele_path = Path(args.telemetry) if args.telemetry else DEFAULT_TELEMETRY
    proc = None
    hwnd = 0
    title = ""

    if args.launch:
        tele_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            tele_path.unlink()
        except OSError:
            pass
        env = dict(os.environ)
        env["MMHAND_TELEMETRY"] = str(tele_path)
        cmd = [str(PYTHON if PYTHON.exists() else sys.executable), str(APP)]
        if args.launch_args:
            cmd += args.launch_args.split()
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env)
        print(f"已启动上位机 pid={proc.pid}  遥测={tele_path}")

    if args.pid and proc is None:
        pid = args.pid
    elif proc is not None:
        pid = proc.pid
    else:
        pid = 0

    # 找窗口（最多等 10s，支持 --launch 后冷启动）
    deadline = time.time() + 10.0
    while True:
        hit = find_window(args.title)
        if hit:
            hwnd, title = hit
            break
        if time.time() > deadline:
            print(f"没找到标题含「{args.title}」的窗口。请确认上位机已启动。")
            return 2
        time.sleep(0.25)

    # 以**窗口所属进程**为准：Windows venv 的 python.exe 是启动器，会再 exec
    # 一次真正的解释器，Popen 拿到的 pid 只有几 MB，测它就全是假数据。
    wpid = window_pid(hwnd)
    if wpid:
        if pid and wpid != pid:
            print(f"（启动器 pid={pid}，应用窗口属于 pid={wpid}，监视后者）")
        pid = wpid

    try:
        probe = ProcProbe(pid)
    except OSError as exc:
        print(f"打开进程失败：{exc}（试试用管理员运行）")
        return 2

    tele = TeleTail(tele_path)
    hz = display_hz()
    print(f"窗口：{title}")
    print(f"进程：pid={pid}   显示器刷新率：{hz or '?'} Hz")
    print(f"遥测：{tele_path}")
    print("时间      UI停滞   CPU    内存     GDI   fps  paint  迟到  rx  备注")
    print("-" * 96)

    csv_path = Path(args.csv) if args.csv else (
        DEFAULT_CSV_DIR / f"watch_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["t", "stall_ms", "cpu_pct", "rss_mb", "gdi", "user_obj", "handles",
              "fps", "paint_ms", "pts_px", "loop_late_ms", "drain_max_ms",
              "plot_max_ms", "table_max_ms", "table_hz", "rx_q",
              "enc_hz", "telem_hz", "tension_age_ms"]
    fh = csv_path.open("w", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(fh, fieldnames=fields)
    writer.writeheader()

    stalls: list[float] = []
    cpus: list[float] = []
    fps_list: list[float] = []
    paints: list[float] = []
    gaps: list[float] = []
    rss_list: list[float] = []
    gdi_list: list[float] = []
    sample_no = 0
    t0 = time.time()
    last_print = 0.0
    data_flowing = False
    try:
        while True:
            now = time.time()
            elapsed = now - t0
            if args.seconds and elapsed >= args.seconds:
                break
            stall = ui_stall_ms(hwnd, args.stall_timeout)
            ps = probe.sample()
            tel = tele.read() or {}
            row = {
                "t": round(elapsed, 2),
                "stall_ms": ("" if stall is None else round(stall, 2)),
                "cpu_pct": ("" if ps["cpu_pct"] is None else round(ps["cpu_pct"], 1)),
                "rss_mb": ("" if ps["rss_mb"] is None else round(ps["rss_mb"], 1)),
                "gdi": ps["gdi"] or "",
                "user_obj": ps["user_obj"] or "",
                "handles": ps["handles"] or "",
                "fps": tel.get("fps", ""),
                "paint_ms": tel.get("paint_ms", ""),
                "pts_px": tel.get("pts_px", ""),
                "loop_late_ms": tel.get("loop_late_ms", ""),
                "drain_max_ms": tel.get("drain_max_ms", ""),
                "plot_max_ms": tel.get("plot_max_ms", ""),
                "table_max_ms": tel.get("table_max_ms", ""),
                "table_hz": tel.get("table_hz", ""),
                "rx_q": tel.get("rx_q", ""),
                "enc_hz": tel.get("enc_hz", ""),
                "telem_hz": tel.get("telem_hz", ""),
                "tension_age_ms": tel.get("tension_age_ms", ""),
            }
            writer.writerow(row)
            fh.flush()

            if stall is not None:
                stalls.append(stall)
            if ps["cpu_pct"] is not None:
                cpus.append(ps["cpu_pct"])
            if ps["rss_mb"] is not None:
                rss_list.append(ps["rss_mb"])
            if ps["gdi"]:
                gdi_list.append(float(ps["gdi"]))
            if isinstance(tel.get("enc_hz"), (int, float)) and tel["enc_hz"] > 0:
                data_flowing = True
            if isinstance(tel.get("fps"), (int, float)):
                fps_list.append(float(tel["fps"]))
            if isinstance(tel.get("paint_ms"), (int, float)):
                paints.append(float(tel["paint_ms"]))
            sample_no += 1
            if sample_no > 2 and isinstance(tel.get("loop_late_ms"), (int, float)):
                gaps.append(float(tel["loop_late_ms"]))

            if not args.quiet and now - last_print >= args.interval:
                last_print = now
                note = []
                if stall is None:
                    note.append("无响应!")
                if tel.get("cl"):
                    note.append("闭环中")

                def _f(v, spec):
                    return "—" if v in (None, "") else format(v, spec)

                print(f"{elapsed:7.1f}s {_f(stall, '6.1f')} "
                      f"{_f(ps['cpu_pct'], '5.1f')}% {_f(ps['rss_mb'], '6.0f')}MB "
                      f"{_f(ps['gdi'], '5.0f')} {_f(tel.get('fps'), '>4')} "
                      f"{_f(tel.get('paint_ms'), '>6')} "
                      f"{_f(tel.get('loop_late_ms'), '>6')} "
                      f"{_f(tel.get('rx_q'), '>3')}  {' '.join(note)}")
            time.sleep(max(0.05, args.interval - (time.time() - now)))
    except KeyboardInterrupt:
        print("\n已停止采样（Ctrl+C）。")
    finally:
        fh.close()
        probe.close()

    # ---------------- 汇总 ----------------
    # 前 2 个采样是冷启动（窗口刚出现、首帧构建），不算卡顿
    steady_stalls = stalls[2:] if len(stalls) > 3 else stalls
    print("\n" + "=" * 72)
    print(f"汇总：时长 {time.time() - t0:.1f}s，采样 {len(stalls) or len(cpus)} 次")
    if steady_stalls:
        print(f"UI 停滞(ms)   p50 {pct(steady_stalls, 0.5):6.1f}  "
              f"p95 {pct(steady_stalls, 0.95):6.1f}  "
              f"p99 {pct(steady_stalls, 0.99):6.1f}  峰值 {max(steady_stalls):6.1f}")
    else:
        print("UI 停滞(ms)   未采到（窗口句柄可能已失效）")
    if cpus:
        print(f"CPU(%)      均值 {sum(cpus) / len(cpus):5.1f}  峰值 {max(cpus):5.1f}")
    if rss_list:
        print(f"内存(MB)     起 {rss_list[0]:.0f}  末 {rss_list[-1]:.0f}  "
              f"增长 {rss_list[-1] - rss_list[0]:+.0f}")
    if gdi_list:
        print(f"GDI 句柄     起 {gdi_list[0]:.0f}  末 {gdi_list[-1]:.0f}  "
              f"增长 {gdi_list[-1] - gdi_list[0]:+.0f}")
    if fps_list:
        print(f"主图 fps     均值 {sum(fps_list) / len(fps_list):5.1f}  最低 {min(fps_list):5.0f}"
              + ("" if data_flowing else "  （无上行数据，不算掉帧）"))
    if paints:
        print(f"paint(ms)    均值 {sum(paints) / len(paints):5.2f}  峰值 {max(paints):5.2f}")
    if gaps:
        print(f"事件循环迟到 峰值 {max(gaps):5.1f} ms（50ms 心跳超出自身间隔的部分）")

    print("-" * 72)
    verdict = []
    if steady_stalls and pct(steady_stalls, 0.95) > 40:
        verdict.append("⚠ UI 卡顿明显（p95 > 40ms）")
    if steady_stalls and max(steady_stalls) > 300:
        verdict.append("⚠ 出现过 >300ms 的无响应")
    if fps_list and data_flowing and min(fps_list) < 45:
        verdict.append(f"⚠ 主图掉帧（最低 {min(fps_list):.0f} fps）")
    if gaps and max(gaps) > 100:
        verdict.append(f"⚠ 事件循环被占用（迟到 {max(gaps):.0f} ms）")
    if rss_list and rss_list[-1] - rss_list[0] > 150:
        verdict.append(f"⚠ 内存增长 {rss_list[-1] - rss_list[0]:.0f} MB（疑似泄漏）")
    if gdi_list and gdi_list[-1] - gdi_list[0] > 300:
        verdict.append(f"⚠ GDI 句柄增长 {gdi_list[-1] - gdi_list[0]:.0f}（疑似泄漏）")
    print("结论：" + ("；".join(verdict) if verdict else "✅ 未发现卡顿/掉帧/泄漏特征"))
    if not fps_list:
        print("提示：未收到内部遥测，帧率/paint 显示为空。"
              "用 --launch 启动，或手动设 MMHAND_TELEMETRY 后再启动上位机。")
    print(f"CSV：{csv_path}")

    if proc is not None and not args.keep_open:
        print("监视结束，关闭本次 --launch 拉起的上位机…")
        # venv 启动器会再 exec 一次，只 terminate 父进程可能留孤儿 → 杀进程树
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
