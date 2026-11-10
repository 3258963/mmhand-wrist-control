"""验证「活动域（active_motor_mask）与勾选不一致」的防护。

事故场景（2026-11-03 实机）：
  急停 → 单机电点动（0xDE，不查活动域，能动）→ 一键紧绳/松绳（0xD3，固件按
  active_motor_mask 收窄）→ 只有活动域里那一台动。

根因：ACTIVE_SCOPE 只在 owner=NONE/未使能时被固件接受；急停后立刻重新使能时
状态机还没清 owner，重写被静默拒绝，活动域停在上一次的单电机掩码。

修法：
  · 使能前强制 STOP+RESET 再写活动域，START 延后 150ms 等状态机收敛；
  · 使能确认时核对活动域，缺电机则自动重写（最多 2 次）；
  · 启动闭环/一键松绳前再核对一次，缺电机直接拒绝并说明。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_scope_mask.py
"""
from __future__ import annotations

import os
import queue
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
import sys  # noqa: E402
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
win.targets = {27: 1000, 28: 2000, 29: 3000}
win._tension_last = (time.monotonic(), [2.0, 2.0, 2.0])
win._tension_guard_saved = {"f_min": "", "f_max": ""}
win.cl_edits["f_min"].setText("0")
win.cl_edits["fmax_f"].setText("30")
win.cl_edits["trim_sign"].setText("1,1,1")
for m in M.SERVO_TARGETS:
    win.cable_enable_checks[m].setChecked(True)

ALL = (1 << 27) | (1 << 28) | (1 << 29)

print("=== 1. 活动域只有 M27 时：一键松绳必须拒绝 ===")
win.status_info["active_motor_mask"] = 1 << 27
win._release_plan = None
win.rx_thread.frames.clear()
win._on_release_rope()
check("拒绝且状态行点名缺哪台", "活动域" in win.ctrl_status.text(),
      f"{win.ctrl_status.text()!r}")
check("没有发出任何运动帧", not win.rx_thread.frames,
      f"帧数={len(win.rx_thread.frames)}")

print("\n=== 2. 活动域只有 M27 时：启动闭环必须拒绝 ===")
win.status_info["active_motor_mask"] = 1 << 27
win.cl_enabled = False
win.cl_mode_combo.blockSignals(True)
win.cl_mode_combo.setCurrentIndex(0)      # 位置模式
win.cl_mode_combo.blockSignals(False)
win._cl_mode = "position"
win.angle_baseline = {16: 0.0, 17: 0.0}
win._enc_filt_raw = {16: 0, 17: 0}
win._start_closed_loop()
check("闭环没有启动", not win.cl_enabled, f"cl_enabled={win.cl_enabled}")
check("状态行说明活动域不符", "活动域" in win.ctrl_status.text(),
      f"{win.ctrl_status.text()!r}")

print("\n=== 3. 活动域正确（三缆）时：松绳正常、闭环能启动 ===")
win.status_info["active_motor_mask"] = ALL
win._release_plan = None
win.rx_thread.frames.clear()
win._on_release_rope()
check("松绳发出 1 帧 0xD3", len(win.rx_thread.frames) == 1,
      f"帧数={len(win.rx_thread.frames)}")
check("三缆目标都推进", (win.targets[27], win.targets[28], win.targets[29])
      == (500, 1500, 2500), f"targets={win.targets}")
win._release_plan = None
win._start_closed_loop()
check("闭环能启动", win.cl_enabled, f"cl_enabled={win.cl_enabled}")
win._stop_closed_loop("test", hold=False)

print("\n=== 4. 使能序列：STOP→RESET→SCOPE，START 延后 ===")
win.rx_thread.frames.clear()
win._admit_timer.stop()
win._finish_enable()
codes = [f[2] for f in win.rx_thread.frames if len(f) > 2]
check("先发 STOP(0xCD) 再 RESET(0xCE) 再 SCOPE(0xD7)",
      codes[:3] == [0xCD, 0xCE, 0xD7], f"实际={ [hex(c) for c in codes] }")
check("START 被延后（本拍还没发）", 0xD7 in codes and len(codes) == 3,
      f"codes={ [hex(c) for c in codes] }")

print("\n=== 汇总 ===")
fails = [r for r in rows if not r[1]]
print(f"{len(rows) - len(fails)}/{len(rows)} 通过")
sys.exit(1 if fails else 0)
