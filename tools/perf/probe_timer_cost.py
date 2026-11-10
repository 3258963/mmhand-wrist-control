"""量 Qt 定时器唤醒本身的成本：1kHz vs 500Hz vs 不打表。

只测「唤醒 + 回调 + 立即返回」的纯开销，不含驱动业务；用来判断
张力轮询从 1ms 改到 2ms 值不值得（安全上 2ms 会掉采样率，见同目录
probe_tension_poll_rate.py）。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_timer_cost.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])


def measure(interval_ms: int | None, seconds: float = 3.0) -> tuple[float, float]:
    hits = {"n": 0}
    timers = []
    if interval_ms is not None:
        t = QTimer()
        t.setTimerType(Qt.PreciseTimer)
        t.timeout.connect(lambda: hits.__setitem__("n", hits["n"] + 1))
        t.start(interval_ms)
        timers.append(t)
    cpu0, wall0 = time.process_time(), time.perf_counter()
    while time.perf_counter() - wall0 < seconds:
        app.processEvents()
        time.sleep(0.0005)
    cpu = time.process_time() - cpu0
    wall = time.perf_counter() - wall0
    for t in timers:
        t.stop()
    return cpu / wall * 100.0, hits["n"] / wall


print(f"{'定时器':>10} {'命中/秒':>9} {'CPU 占比':>9}")
for label, iv in (("无", None), ("500Hz(2ms)", 2), ("1kHz(1ms)", 1)):
    cpu, hz = measure(iv)
    print(f"{label:>10} {hz:>8.0f}/s {cpu:>8.2f}%")
