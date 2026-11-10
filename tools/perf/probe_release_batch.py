"""验证「多电机直控必须一帧批量」：松绳/斜坡/回零不再逐帧 0xDE。

根因：固件 upperApplySingleMotorTarget() 每帧 pending_direct_generation+1
并把 pending_direct_motor_mask 覆盖成单电机位；状态机用
pendingDirectCommandMatches(generation) 过滤，只有最新代际那帧被接受。
同一毫秒连发 3 帧 0xDE → 前两帧被丢弃 → 只有一根绳动（实机现象）。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_release_batch.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from desktop.core.protocol import (  # noqa: E402
    CMD_MOTOR_POS_ABS, CMD_MOTOR_POS_ABS_ONE, build_motor_pos_abs_cmd)
from PySide6.QtWidgets import QApplication  # noqa: E402

rows: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


class FakeRx:
    def __init__(self):
        self.frames: list[bytes] = []
        import queue
        self.tx_queue = queue.Queue()

    def send(self, data, priority=False):
        self.frames.append(bytes(data))
        return True


app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")
win.rx_thread = FakeRx()
win.connected = True
win.armed = True
win.ramp_check.setChecked(False)
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

print("=== 1. 一键松绳第一步：应只发 1 帧 0xD3（含三缆） ===")
win.rx_thread.frames.clear()
win._on_release_rope()
frames = list(win.rx_thread.frames)
one_frames = [f for f in frames if len(f) > 2 and f[2] == CMD_MOTOR_POS_ABS_ONE]
batch_frames = [f for f in frames if len(f) > 2 and f[2] == CMD_MOTOR_POS_ABS]
expect = [100] * 30
expect[27], expect[28], expect[29] = 500, 1500, 2500   # 各放 500c
check("没有单电机 0xDE 帧", not one_frames, f"0xDE 帧数={len(one_frames)}")
check("恰好 1 帧批量 0xD3", len(batch_frames) == 1, f"0xD3 帧数={len(batch_frames)}")
check("批量帧里三缆目标都正确", batch_frames and batch_frames[0] == build_motor_pos_abs_cmd(expect),
      f"targets={win.targets}")
win._release_plan = None

print("\n=== 2. 斜坡：三台同时斜坡，每拍也应只发 1 帧 ===")
win.ramp_check.setChecked(True)
win.targets = {m: 1000 for m in M.SERVO_TARGETS}
win._ramp_state = {m: {"target": 5000, "next_due": 0.0} for m in M.SERVO_TARGETS}
win.rx_thread.frames.clear()
win._on_ramp_tick()
frames = list(win.rx_thread.frames)
one_frames = [f for f in frames if len(f) > 2 and f[2] == CMD_MOTOR_POS_ABS_ONE]
batch_frames = [f for f in frames if len(f) > 2 and f[2] == CMD_MOTOR_POS_ABS]
check("斜坡一拍无 0xDE", not one_frames, f"0xDE 帧数={len(one_frames)}")
check("斜坡一拍恰好 1 帧 0xD3", len(batch_frames) == 1, f"0xD3 帧数={len(batch_frames)}")
check("三台都在推进（targets 都变了）",
      all(win.targets[m] > 1000 for m in M.SERVO_TARGETS),
      f"targets={win.targets}")
win._ramp_state.clear()
win._ramp_timer.stop()

print("\n=== 3. 回零：一帧批量，未勾选的不动 ===")
win.ramp_check.setChecked(False)
win.targets = {m: 0 for m in M.SERVO_TARGETS}
win.cable_enable_checks[29].setChecked(False)
win.rx_thread.frames.clear()
win._do_goto_zero({"motors": {"27": 1000, "28": 2000, "29": 3000}})
frames = list(win.rx_thread.frames)
batch_frames = [f for f in frames if len(f) > 2 and f[2] == CMD_MOTOR_POS_ABS]
expect = [100] * 30
expect[27], expect[28] = 1000, 2000
check("回零 1 帧 0xD3 且不含未勾选的 M29",
      len(batch_frames) == 1 and batch_frames[0] == build_motor_pos_abs_cmd(expect),
      f"0xD3={len(batch_frames)} targets={win.targets}")
win.cable_enable_checks[29].setChecked(True)

print("\n=== 汇总 ===")
fails = [r for r in rows if not r[1]]
print(f"{len(rows) - len(fails)}/{len(rows)} 通过")
sys.exit(1 if fails else 0)
