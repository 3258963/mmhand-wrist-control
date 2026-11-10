"""确认「paint 时到底画了多少个点」——直接看 getData() 的长度和 ds。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_paint_points.py
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
win._latest_t = SECONDS

img = QImage(916, 626, QImage.Format_ARGB32_Premultiplied)
win.window_combo.setCurrentText("120s")


def paint_ms(reps=8):
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


def add_curve(key):
    ch = win.channels[key]
    if ch.curve is None:
        ch.curve = win.plot.plot(pen=M.pg.mkPen(ch.color, width=1), name=ch.name,
                                 downsample=4, autoDownsample=True)


print("=== 单条曲线，120s 窗口：ds 与 paint 的关系 ===")
add_curve("enc_raw_0")
ch = win.channels["enc_raw_0"]
for label, ds, auto in (("默认(downsample=4,auto)", 4, True),
                        ("auto 关 ds=4", 4, False),
                        ("auto 关 ds=20", 20, False),
                        ("auto 关 ds=50", 50, False),
                        ("auto 关 ds=200", 200, False)):
    ch.curve.setDownsampling(ds=ds, auto=auto)
    win._update_plot()
    xd, _yd = ch.curve.getData()
    n = len(xd) if xd is not None else 0
    print(f"  {label:<24} 画出 {n:>6} 点  paint {paint_ms():6.2f} ms  "
          f"_adsLast={getattr(ch.curve, '_adsLastValue', None)}")

print("\n=== 20 条曲线，120s：关掉 auto 固定 ds=50 ===")
for key in [f"enc_raw_{j}" for j in range(1, 20)]:
    add_curve(key)
for key in [f"enc_raw_{j}" for j in range(20)]:
    win.channels[key].curve.setDownsampling(ds=50, auto=False)
print(f"  20 条 × ds=50  paint {paint_ms():6.2f} ms")
for key in [f"enc_raw_{j}" for j in range(20)]:
    win.channels[key].curve.setDownsampling(ds=4, auto=True)
print(f"  20 条 × auto     paint {paint_ms():6.2f} ms")
