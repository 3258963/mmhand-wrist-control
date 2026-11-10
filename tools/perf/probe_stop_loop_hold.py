"""验证「停止闭环」也是立刻停：丢队列 + 抢占下发保持当前位。

背景：停环只停 100Hz 定时器，但下行队列里可能排着上百帧运动指令（~300ms），
P4 会照单执行 → 按了停止闭环还在动。现在停环先 drop 队列，再用优先通道发
一帧 0xD3（27-29 = 实测位置），动作当场刹住且保持力矩。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_stop_loop_hold.py
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
from desktop.core.protocol import CMD_MOTOR_POS_ABS, build_motor_pos_abs_cmd  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

rows: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


class FakeRx:
    def __init__(self):
        self.frames: list[tuple[bool, bytes]] = []   # (priority, frame)
        self.tx_queue = queue.Queue()
        self.pending_before_drop = 0
        self.dropped = 0

    def drop_pending_tx(self):
        self.pending_before_drop = self.tx_queue.qsize()
        self.dropped = self.pending_before_drop
        while True:
            try:
                self.tx_queue.get_nowait()
            except queue.Empty:
                return self.dropped

    def send(self, data, priority=False):
        self.frames.append((bool(priority), bytes(data)))
        return True


app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")
win.connected = True
win.armed = True
win.last_servo_abs_all = [100] * 30
win._motor_origin = {27: 0, 28: 0, 29: 0}
for m in M.SERVO_TARGETS:
    win.cable_enable_checks[m].setChecked(True)
# 实测位置：27=1000, 28=2000, 29=3000（通道缓冲最后值）
for m, v in ((27, 1000), (28, 2000), (29, 3000)):
    win.channels[f"m{m}_abs"].buf.append(time.monotonic(), float(v))
win.targets = {27: 9000, 28: 9000, 29: 9000}      # 闭环正在往 9000 冲

print("=== 1. 停止闭环：丢队列 + 抢占下发保持当前位 ===")
win.rx_thread = FakeRx()
for _ in range(37):                                # 模拟积压 37 帧运动指令
    win.rx_thread.tx_queue.put(b"\x00" * 127)
win.cl_enabled = True
win._cl_timer.start(10)
t0 = time.perf_counter()
win._stop_closed_loop("手动停止")
elapsed_ms = (time.perf_counter() - t0) * 1000

expect = [100] * 30
expect[27], expect[28], expect[29] = 1000, 2000, 3000
prio = [f for p, f in win.rx_thread.frames if p]
check("积压的 37 帧被丢弃", win.rx_thread.dropped == 37, f"dropped={win.rx_thread.dropped}")
check("发了一帧抢占保持帧", len(prio) == 1,
      f"priority 帧数={len(prio)}")
check("保持帧内容 = 三缆实测位置",
      bool(prio) and prio[0] == build_motor_pos_abs_cmd(expect),
      f"targets={win.targets}")
check("停止后 targets 被锁到实测位置",
      (win.targets[27], win.targets[28], win.targets[29]) == (1000, 2000, 3000),
      f"targets={win.targets}")
check("cl_timer 已停", not win._cl_timer.isActive())
check("端到端耗时可接受（<20ms）", elapsed_ms < 20, f"{elapsed_ms:.1f} ms")

print("\n=== 2. 急停路径不发保持帧（避免把刚断的力矩按回去） ===")
win.rx_thread = FakeRx()
win.cl_enabled = True
win._cl_timer.start(10)
win._on_stop()
frames = win.rx_thread.frames
hold_frames = [f for p, f in frames if p and len(f) > 2 and f[2] == CMD_MOTOR_POS_ABS]
stop_frames = [f for p, f in frames if p and len(f) > 2 and f[2] == 0xCD]
check("急停只发 0xCD，不发 0xD3 保持帧",
      bool(stop_frames) and not hold_frames,
      f"STOP={len(stop_frames)} HOLD={len(hold_frames)}")

print("\n=== 汇总 ===")
fails = [r for r in rows if not r[1]]
print(f"{len(rows) - len(fails)}/{len(rows)} 通过")
sys.exit(1 if fails else 0)
