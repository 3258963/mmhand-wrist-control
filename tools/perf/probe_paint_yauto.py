"""定位 paint 的真正成本：Y 自动量程 vs 画线。

假设：paint 30ms 的元凶是 ViewBox 的 Y autoRange——它每次重绘都要对每条
曲线的**原始**数据（120s@150Hz=18000 点）走一遍求 bounds，和显示降采样无关
（所以调 autoDownsampleFactor 无效）。

验证：同一矩阵下对比 yauto 开/关的 paint 时间。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_paint_yauto.py
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
import numpy as np  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")
win.resize(1600, 900)
win.show()
app.processEvents()

SECONDS = 130.0
for j in range(M.ENCODER_COUNT):
    ch = win.channels[f"enc_raw_{j}"]
    ch.buf.t[:] = np.linspace(0, SECONDS, ch.buf.capacity)
    ch.buf.v[:] = 8000 + 400 * np.sin(ch.buf.t * 0.7 + j) + 40 * np.sin(ch.buf.t * 40)
    ch.buf.head, ch.buf.count = 0, ch.buf.capacity
for m in (27, 28, 29):
    for f in ("abs", "raw", "speed", "load", "current", "volt", "temp"):
        ch = win.channels[f"m{m}_{f}"]
        ch.buf.t[:] = np.linspace(0, SECONDS, ch.buf.capacity)
        ch.buf.v[:] = 500 + 100 * np.sin(ch.buf.t * 2)
        ch.buf.head, ch.buf.count = 0, ch.buf.capacity
win._latest_t = SECONDS

KEYS = [f"enc_raw_{j}" for j in range(21)] + [f"m{m}_{f}" for m in (27, 28, 29)
                                               for f in ("abs", "raw", "speed", "load",
                                                         "current", "volt", "temp")]
img = QImage(916, 626, QImage.Format_ARGB32_Premultiplied)


def set_curves(k):
    for key in KEYS:
        ch = win.channels[key]
        if ch.curve is not None:
            win.plot.removeItem(ch.curve)
            ch.curve = None
    for key in KEYS[:k]:
        ch = win.channels[key]
        ch.curve = win.plot.plot(pen=M.pg.mkPen(ch.color, width=1), name=ch.name,
                                 downsample=4, autoDownsample=True)


def measure(reps=10):
    win._plot_dirty = True
    win._update_plot()
    app.processEvents()
    s = []
    for _ in range(reps):
        win._update_plot()
        p = QPainter(img)
        t0 = time.perf_counter()
        win.plot.render(p)
        s.append((time.perf_counter() - t0) * 1000.0)
        p.end()
    s.sort()
    return s[len(s) // 2]


def yauto(on: bool):
    win.yauto_check.blockSignals(True)
    win.yauto_check.setChecked(on)
    win.yauto_check.blockSignals(False)
    vb = win.plot.getViewBox()
    if on:
        vb.enableAutoRange(axis=M.ViewBox.YAxis, x=False)
    else:
        vb.disableAutoRange(axis=M.ViewBox.YAxis)


print(f"视口 {win.plot.width()}×{win.plot.height()} px")
print(f"{'曲线':>4} {'窗口':>5} {'Y自动 开':>10} {'Y自动 关':>10} {'加速比':>8}")
for k in (5, 20):
    set_curves(k)
    for win_s in ("30s", "120s"):
        win.window_combo.setCurrentText(win_s)
        yauto(True)
        on = measure()
        yauto(False)
        off = measure()
        print(f"{k:>4} {win_s:>5} {on:>10.2f} {off:>10.2f} {on / off:>7.1f}×")
