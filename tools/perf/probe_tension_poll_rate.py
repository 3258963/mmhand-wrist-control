"""量化「张力轮询 1ms → 2ms」对采样率的影响（纯仿真，不接硬件）。

驱动 ZnsvTransmitter 的节奏锚定在**请求起点**（_end() 里 _next_weights =
_tx_started + period），所以理论上采样率不会被轮询间隔拉长；但响应完成是
在下一次 poll 才被看到的，2ms 间隔会把完成检测量化到 2ms，是否吃满 250Hz
需要实测。

做法：虚拟时钟按 tick 步进，模拟从站响应延迟 latency，跑 2 秒虚拟时间，
数 poll() 返回的样本数。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_tension_poll_rate.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from znsv_app.znsv import ZnsvTransmitter  # noqa: E402
from znsv_app.crc16 import crc16  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class LatentSerial:
    """write 后延迟 latency 才交付响应；in_waiting 只统计已到达的字节。"""

    def __init__(self, clock, latency=0.002):
        self.clock, self.latency = clock, latency
        self.is_open = True
        self._pending = []      # [(deliver_at, bytes)]
        self._rx = bytearray()
        self.tx = []

    def _pump(self):
        now = self.clock.now
        keep = []
        for at, data in self._pending:
            if at <= now:
                self._rx.extend(data)
            else:
                keep.append((at, data))
        self._pending = keep
        return len(self._rx)

    @property
    def in_waiting(self):
        return self._pump()

    def write(self, packet):
        self.tx.append(bytes(packet))
        self._pending.append((self.clock.now + self.latency, self._respond(bytes(packet))))
        return len(packet)

    @staticmethod
    def _respond(request):
        if request[1] != 3:
            return request                       # FC06 回显
        start = int.from_bytes(request[2:4], "big")
        count = int.from_bytes(request[4:6], "big")
        regs = [11] * count if start == 0 else [620, 1, 8, 40][:count]
        data = b"".join(int(r).to_bytes(2, "big") for r in regs)
        payload = bytes((request[0], 3, len(data))) + data
        return payload + crc16(payload).to_bytes(2, "little")

    def read(self, n):
        self._pump()
        if n <= 0:
            return b""
        take = self._rx[:n]
        del self._rx[:len(take)]
        return bytes(take)

    def reset_input_buffer(self):
        self._rx.clear()

    def close(self):
        self.is_open = False


def run(tick: float, seconds: float = 2.0, latency: float = 0.002) -> tuple[float, float]:
    """固定 tick 轮询。返回 (采样率 Hz, 每秒唤醒次数)。"""
    clock = Clock()
    sensor = ZnsvTransmitter(address=1, hz=250.0,
                             serial_factory=lambda **kw: LatentSerial(clock, latency),
                             clock=clock)
    sensor.connect("FAKE")
    samples = 0
    wakeups = 0
    t = 0.0
    while t < seconds:
        clock.now = t
        wakeups += 1
        if sensor.poll() is not None:
            samples += 1
        t += tick
    return samples / seconds, wakeups / seconds


def run_adaptive(seconds: float = 2.0, latency: float = 0.002) -> tuple[float, float]:
    """复刻 mmhand_scope._tension_poll 的自适应排程：空闲按 next_poll_delay 睡。"""
    clock = Clock()
    sensor = ZnsvTransmitter(address=1, hz=250.0,
                             serial_factory=lambda **kw: LatentSerial(clock, latency),
                             clock=clock)
    sensor.connect("FAKE")
    samples = 0
    wakeups = 0
    t = 0.0
    while t < seconds:
        clock.now = t
        wakeups += 1
        if sensor.poll() is not None:
            samples += 1
        delay = sensor.next_poll_delay()
        step = 0.001 if delay <= 0.0005 else max(
            0.001, min(0.020, math.ceil(delay * 1000.0) / 1000.0))
        t += step
    return samples / seconds, wakeups / seconds


def main() -> int:
    print(f"{'策略':>16} {'响应延迟':>8} {'采样率':>9} {'唤醒/秒':>9}")
    for latency in (0.0015, 0.002, 0.0025, 0.003):
        for label, fn, tick in (
                ("固定 1ms", lambda s, l: run(0.001, s, l), 0.001),
                ("固定 2ms", lambda s, l: run(0.002, s, l), 0.002),
                ("自适应（本次改动）", lambda s, l: run_adaptive(s, l), None)):
            hz, wakes = fn(2.0, latency)
            print(f"{label:>16} {latency * 1000:>6.1f}ms {hz:>8.1f}Hz {wakes:>8.0f}/s")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
