"""直控/松绳是否还做张力检测 —— 按 2026-11-03 用户定案重新定义契约。

新契约：
  · 直控（点动/Go/斜坡/回零）**不做**张力检测：张力超限也照发，无传感器也照发、
    不再弹"无张力保护"确认；
  · 一键松绳**不做**张力检测：无张力样本也能完整放完，某缆张力变化不影响流程；
  · 张力保护只在**闭环**：力控三模式启动要求新鲜样本、守卫阈值非法时 fail-closed
    停环、位置模式单拍斜率限制 —— 这三项受 🛡 开关控制。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_safety_interlock.py
"""
from __future__ import annotations

import os
import queue
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

rows: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


class FakeRx:
    def __init__(self):
        self.frames: list[bytes] = []
        self.tx_queue = queue.Queue()

    def drop_pending_tx(self):
        return 0

    def send(self, data, priority=False):
        self.frames.append(bytes(data))
        return True


app = QApplication([])
M.load_layout_json = lambda: {}
win = M.ScopeWindow(default_port="COM_NONE")
win.connected = True
win.armed = True
win.rx_thread = FakeRx()
win.last_servo_abs_all = [100] * 30
win._motor_origin = {27: 0, 28: 0, 29: 0}
win.targets = {27: 0, 28: 0, 29: 0}
win._tension_guard_saved = {"f_min": "", "f_max": ""}
win.cl_edits["f_min"].setText("0")
win.cl_edits["fmax_f"].setText("30")
win.cl_edits["trim_sign"].setText("1,1,1")
for m in M.SERVO_TARGETS:
    win.cable_enable_checks[m].setChecked(True)


def fresh(vals=(2.0, 2.0, 2.0)) -> None:
    win._tension_last = (time.monotonic(), list(vals))


print("=== 1. 直控不看张力：超限也照发 ===")
fresh((2.0, 45.0, 2.0))               # 45N 远超 fmax 30N
win.rx_thread.frames.clear()
win._send_motor_target(27, 500)
check("张力超限时直控仍然下发", bool(win.rx_thread.frames) and win.targets[27] == 500,
      f"target={win.targets[27]} 状态={win.ctrl_status.text()!r}")

print("\n=== 2. 直控不看张力：没传感器也照发、不再弹确认 ===")
win._tension_last = None
win._tension_sensor = None
win.rx_thread.frames.clear()
win._send_motor_target(28, 600)
check("无张力数据时直控仍然下发", bool(win.rx_thread.frames) and win.targets[28] == 600,
      f"target={win.targets[28]}")
check("不再出现「无张力保护」确认提示",
      "无张力保护" not in win.ctrl_status.text(),
      f"状态={win.ctrl_status.text()!r}")

print("\n=== 3. 一键松绳不看张力：无样本也能放完 ===")
win.targets = {27: 1000, 28: 1000, 29: 1000}
win._release_plan = None
win._tension_last = None
win.rx_thread.frames.clear()
win._on_release_rope()
for _ in range(4):
    win._release_step()
check("无张力样本也能完整松绳", win._release_plan is None
      and (win.targets[27], win.targets[28], win.targets[29]) == (-1500, -1500, -1500),
      f"targets={win.targets}")

print("\n=== 4. 🛡 开关只作用于闭环：阈值非法时 fail-closed ===")
win.safety_check.setChecked(True)
win.cl_enabled = True
win.cl_edits["f_min"].setText("30")     # fmin>fmax → 阈值非法
win.cl_edits["fmax_f"].setText("10")
win._tension_guard(0.0, 0.0)
check("安全保护开启：阈值非法 → 停环", not win.cl_enabled,
      f"cl_enabled={win.cl_enabled} 状态={win.ctrl_status.text()!r}")

win.safety_check.setChecked(False)
win.cl_enabled = True
win._tension_guard(0.0, 0.0)
check("安全保护关闭：阈值非法也不停环（放行）", win.cl_enabled,
      f"cl_enabled={win.cl_enabled}")
win.cl_enabled = False
win.cl_edits["f_min"].setText("0")
win.cl_edits["fmax_f"].setText("30")
win.safety_check.setChecked(True)

print("\n=== 5. 安全取证日志仍在记录 ===")
path = M.safety_log_path()
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
check("safety 日志有直控/松绳记录",
      any("[DIRECT]" in ln for ln in lines) and any("[RELEASE" in ln for ln in lines),
      f"末行={lines[-1] if lines else '(空)'}")

print("\n=== 汇总 ===")
fails = [r for r in rows if not r[1]]
print(f"{len(rows) - len(fails)}/{len(rows)} 通过")
sys.exit(1 if fails else 0)
