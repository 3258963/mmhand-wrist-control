"""急停延迟实测：从点下「⛔ 急停 STOP」到 STOP 帧真正写出串口要多久。

背景：STOP 原先和普通运动指令共用一条 FIFO 下行队列，且 _on_stop 先做记账
（可能同步写标定 CSV）才发帧；串口读超时还是 50ms。

本探针用假串口按 921600 波特率模拟"空气时间"，量三种场景：
  A 旧路径：200 帧 0xD3 排在前面的 FIFO
  B 旧路径但队列空
  C 新路径：清空待发 → 抢占通道发 STOP
并单独量 _on_stop 端到端调用耗时（含记账）。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_estop_latency.py
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

BAUD = 921600
AIR_S = 10.0 / BAUD          # 每字节 10 bit 的串口时间
BATCH_BYTES = 127            # 0xD3 30 路目标帧约 127 B
STOP_FRAME = M.build_stop_cmd()


class FakePort:
    """write 按字节数 sleep，模拟串口发送时间。"""

    def __init__(self):
        self.writes: list[tuple[float, bytes]] = []

    def write(self, data: bytes) -> int:
        time.sleep(len(data) * AIR_S)
        self.writes.append((time.perf_counter(), bytes(data)))
        return len(data)

    def close(self):
        pass


def make_thread() -> "M.SerialRxThread":
    th = M.SerialRxThread("FAKE", queue.Queue())
    th.serial = FakePort()
    return th


def stop_written_at(th: "M.SerialRxThread") -> float | None:
    for when, data in th.serial.writes:
        if data == STOP_FRAME:
            return when
    return None


print(f"串口 {BAUD} baud：一帧 0xD3({BATCH_BYTES}B) ≈ "
      f"{BATCH_BYTES * AIR_S * 1000:.2f} ms，STOP {len(STOP_FRAME)}B ≈ "
      f"{len(STOP_FRAME) * AIR_S * 1000:.3f} ms")

# ---- A. 旧路径：200 帧排在 STOP 前面 ----
th = make_thread()
for _ in range(200):
    th.tx_queue.put(b"\x00" * BATCH_BYTES)
t0 = time.perf_counter()
th.tx_queue.put(STOP_FRAME)          # 旧 send() 就是塞同一个 FIFO
th._drain_tx()
a_ms = (stop_written_at(th) - t0) * 1000

# ---- B. 旧路径、队列空 ----
th = make_thread()
t0 = time.perf_counter()
th.tx_queue.put(STOP_FRAME)
th._drain_tx()
b_ms = (stop_written_at(th) - t0) * 1000

# ---- C. 新路径：清队列 + 抢占通道 ----
th = make_thread()
for _ in range(200):
    th.tx_queue.put(b"\x00" * BATCH_BYTES)
t0 = time.perf_counter()
dropped = th.drop_pending_tx()
th.send(STOP_FRAME, priority=True)
th._drain_tx()
c_ms = (stop_written_at(th) - t0) * 1000

print(f"A 旧路径（前面排 200 帧）  STOP 写出耗时 {a_ms:7.2f} ms")
print(f"B 旧路径（队列空）        STOP 写出耗时 {b_ms:7.2f} ms")
print(f"C 新路径（清 {dropped} 帧+抢占）STOP 写出耗时 {c_ms:7.2f} ms")

# ---- D. 端到端 _on_stop()（含记账/停表） ----
app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")


class FakeRx:
    def __init__(self):
        self.calls: list[tuple[float, bool]] = []

    def drop_pending_tx(self) -> int:
        return 200

    def send(self, data, priority=False):
        self.calls.append((time.perf_counter(), bool(priority)))
        return True


win.connected = True
win.rx_thread = FakeRx()
win.cl_enabled = False
t0 = time.perf_counter()
win._on_stop()
d_ms = (time.perf_counter() - t0) * 1000
first = win.rx_thread.calls[0] if win.rx_thread.calls else None
print(f"D  _on_stop() 端到端         {d_ms:7.2f} ms"
      f"（STOP 抢占={first[1] if first else 'N/A'}，"
      f"记账前已发={bool(first) }）")

ok = (c_ms < b_ms + 5) and (c_ms < a_ms / 4) and first is not None and first[1]
print("\n结论：新路径把最坏 STOP 延迟从 "
      f"{a_ms:.0f} ms 降到 {c_ms:.1f} ms" + ("  ✅" if ok else "  ❌"))
sys.exit(0 if ok else 1)
