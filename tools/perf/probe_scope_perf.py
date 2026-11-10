"""mmhand_scope 性能探针：量化「越用越卡」。

直接 import mmhand_scope（原 17:07 误插块已在源头修复，无需再摘块 exec——
exec 源码方案已按 Mimosa 复查移除）。离屏构造窗口，逐项量：

  1. 主图 _update_plot 单帧耗时（决定 FPS 天花板）
  2. 数值表 _update_tables 单拍耗时
  3. 观测台/参数窗 反复开关后的实例泄漏与定时器泄漏
  4. 泄漏后 GUI 线程实际还能跑多少 Hz（用户感觉到的「卡」）

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_scope_perf.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402  直接导入：无 exec、无源码改写

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
import numpy as np  # noqa: E402

print(f"加载完成：{M.__name__}  PLOT_HZ={M.PLOT_HZ}  BUFFER_LEN={M.BUFFER_LEN}")
app = QApplication([])
t0 = time.perf_counter()
win = M.ScopeWindow(default_port="COM_NONE")
print(f"主窗构造 {time.perf_counter() - t0:.2f}s，通道 {len(win.channels)} 路")


# ---------------- 造数据 ----------------
def feed(seconds: float = 40.0, rate: float = 150.0) -> None:
    n = int(seconds * rate)
    dt = 1.0 / rate
    for j in range(M.ENCODER_COUNT):
        ch = win.channels[f"enc_raw_{j}"]
        for k in range(n):
            ch.buf.append(k * dt, 8000 + 400 * np.sin(k * 0.01 + j) + 30 * np.sin(k * 0.7))
    for m in (27, 28, 29):
        for field in ("abs", "raw", "speed", "load", "current", "volt", "temp"):
            ch = win.channels[f"m{m}_{field}"]
            for k in range(n):
                ch.buf.append(k * dt, 500 + 100 * np.sin(k * 0.02 + m))
    win._latest_t = n * dt
    win.status_info["encoder_online"] = (1 << M.ENCODER_COUNT) - 1
    win.status_info["servo_online"] = sum(1 << m for m in (27, 28, 29))


t0 = time.perf_counter()
feed()
print(f"灌 40s 数据 {time.perf_counter() - t0:.1f}s")


def check_curves(keys):
    for k in keys:
        ch = win.channels[k]
        if ch.curve is None:
            ch.curve = win.plot.plot(pen=M.pg.mkPen(ch.color, width=1), name=ch.name,
                                     downsample=4, autoDownsample=True)


def bench(fn, n=40, warm=5):
    for _ in range(warm):
        fn()
    t = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t) / n * 1000.0


# ---------------- 1. 主图 ----------------
print("\n=== 1. 主图 _update_plot（软件光栅，离屏；不含真实 paint） ===")
check_curves(["enc_raw_16", "enc_raw_17", "m27_abs", "m28_abs", "m29_abs"])
ms5 = bench(win._update_plot)
print(f"5 条曲线  : {ms5:6.2f} ms/帧  -> 天花板 {1000 / ms5:5.0f} FPS")

preset = M.ScopeWindow.PRESETS["腕部调试"]
check_curves(preset)
ms19 = bench(win._update_plot)
print(f"{len(preset)} 条曲线: {ms19:6.2f} ms/帧  -> 天花板 {1000 / ms19:5.0f} FPS")

for k in preset:
    ch = win.channels[k]
    if ch.curve is not None:
        win.plot.removeItem(ch.curve)
        ch.curve = None

# ---------------- 2. 数值表 ----------------
print("\n=== 2. 数值表 _update_tables ===")
ms_tab = bench(win._update_tables)
print(f"{ms_tab:6.2f} ms/拍 -> 60Hz 占用 {ms_tab / 16.7 * 100:4.1f}% GUI 线程")

# ---------------- 3. 观测台开关泄漏 ----------------
print("\n=== 3. 反复开关「张力·R 观测台」/「参数窗」 ===")


def live(cls):
    return [w for w in win.findChildren(cls) if w is not None]


def count_timers():
    n = 0
    for w in win.findChildren(object):
        try:
            if isinstance(w, QTimer) and w.isActive():
                n += 1
        except Exception:
            pass
    return n


def toggle_rt(n):
    for _ in range(n):
        win._toggle_rt_window()   # 打开
        win._toggle_rt_window()   # 关闭（现已停定时器+deleteLater）
        app.processEvents()       # 让 deleteLater 生效后再数


def toggle_watch(n):
    for _ in range(n):
        win._toggle_watch_window()
        win._toggle_watch_window()
        app.processEvents()


print(f"初始：RTensionWindow {len(live(M.RTensionWindow))} 个，"
      f"ParameterWatchWindow {len(live(M.ParameterWatchWindow))} 个，活动 QTimer {count_timers()}")

toggle_rt(3)
rt_live = live(M.RTensionWindow)
# 性能真相=活动定时器（修复后不再随开关增长；残留的 wrapper 无定时器不耗 CPU）
rt_timers = sum(1 for w in rt_live
                if any(isinstance(t, QTimer) and t.isActive()
                       for t in w.findChildren(QTimer)))
print(f"开关观测台 3 次后：存活 {len(rt_live)} 个（deleteLater 摘除中），"
      f"其中带活动定时器 {rt_timers} 个（期望 0），活动 QTimer {count_timers()}")

toggle_watch(3)
wi_live = live(M.ParameterWatchWindow)
print(f"开关参数窗 3 次后：存活 {len(wi_live)} 个，活动 QTimer {count_timers()}")

# ---------------- 4. GUI 线程实际速率 ----------------
print("\n=== 4. GUI 线程实际节拍（16ms 定时器，1.5s 窗口） ===")


def loop_hz(msec_wait=1500):
    state = {"n": 0, "max_gap": 0.0, "last": time.perf_counter()}

    def tick():
        now = time.perf_counter()
        gap = (now - state["last"]) * 1000.0
        state["last"] = now
        if gap > state["max_gap"]:
            state["max_gap"] = gap
        state["n"] += 1

    t = QTimer()
    t.setTimerType(Qt.PreciseTimer)
    t.timeout.connect(tick)
    t.start(16)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < msec_wait / 1000.0:
        app.processEvents()
        time.sleep(0.001)
    t.stop()
    span = time.perf_counter() - t0
    return state["n"] / span, state["max_gap"]


hz, gap = loop_hz()
print(f"泄漏 {len(live(M.RTensionWindow)) + len(live(M.ParameterWatchWindow))} 个隐藏窗口时："
      f"{hz:5.1f} Hz  最大卡顿 {gap:5.1f} ms")

for w in win.findChildren(M.RTensionWindow) + win.findChildren(M.ParameterWatchWindow):
    w.hide()
    if hasattr(w, "_timer"):
        w._timer.stop()
hz2, gap2 = loop_hz()
print(f"停掉全部泄漏定时器后：{hz2:5.1f} Hz  最大卡顿 {gap2:5.1f} ms")

print("\n结论产物：以上数字直接在 60/120FPS 预算里对比即可。")
