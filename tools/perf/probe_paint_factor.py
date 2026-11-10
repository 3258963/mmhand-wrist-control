"""验证 autoDownsampleFactor 对 paint 的影响：能不能「不降帧、只降点数」。

pyqtgraph 默认 autoDownsampleFactor=5（每像素画 5 个点）。120s 窗口 @150Hz
= 18000 点/曲线，20 条曲线一帧 12 万点。把因子收到 1（每像素 1 点）后
点数降一个数量级，paint 也应降一个数量级。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_paint_factor.py
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

RATE, SECONDS = 150.0, 130.0
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


def paint_ms(factor, reps=10):
    for key in KEYS:
        ch = win.channels[key]
        if ch.curve is not None:
            ch.curve.opts["autoDownsampleFactor"] = factor
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


print(f"视口 {win.plot.width()}×{win.plot.height()} px")
print(f"{'曲线':>4} {'窗口':>5} {'因子5(默认)':>12} {'因子2':>8} {'因子1':>8} {'因子0.5':>8}  {'→60FPS?':>8}")
for k in (5, 10, 20):
    set_curves(k)
    for win_s in ("30s", "120s"):
        win.window_combo.setCurrentText(win_s)
        r = {f: paint_ms(f) for f in (5.0, 2.0, 1.0, 0.5)}
        print(f"{k:>4} {win_s:>5} {r[5.0]:>12.2f} {r[2.0]:>8.2f} {r[1.0]:>8.2f} "
              f"{r[0.5]:>8.2f}  {'✅' if r[1.0] < 16.6 * 0.6 else '❌':>8}")
