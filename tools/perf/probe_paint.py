"""量 paint 预算：软件光栅下主图/观测台真正能跑多少 FPS。

_update_plot（setData）只要 0.5ms，但那不含绘制。这里用 QWidget.render()
强制走真实 paint 路径（Windows 上同样是 raster 引擎），得到每帧 paint 毫秒数，
再换算 FPS 天花板。矩阵扫描：曲线数 × 时间窗 × 降采样档。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_paint.py
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
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsView, QWidget  # noqa: E402

app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")
win.resize(1600, 900)
win.show()
app.processEvents()

RATE = 150.0
SECONDS = 130.0
n = int(SECONDS * RATE)
for j in range(M.ENCODER_COUNT):
    ch = win.channels[f"enc_raw_{j}"]
    t = np.arange(n) / RATE
    ch.buf.t[:] = t[-ch.buf.capacity:]
    ch.buf.t[:] = np.linspace(0, SECONDS, ch.buf.capacity)
    ch.buf.v[:] = 8000 + 400 * np.sin(ch.buf.t * 2 * np.pi * 0.7 + j) + 40 * np.sin(ch.buf.t * 40)
    ch.buf.head = 0
    ch.buf.count = ch.buf.capacity
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


img = None


def render_widget(widget, image):
    painter = QPainter(image)
    try:
        if isinstance(widget, QWidget) and not isinstance(widget, QGraphicsView):
            widget.render(painter, QPoint(0, 0))
        else:
            widget.render(painter)
    finally:
        painter.end()


def paint_ms(reps=12):
    """强制 paint 一次 + 取中位数。"""
    global img
    w = win.plot.width()
    h = win.plot.height()
    if img is None or img.width() != w or img.height() != h:
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    win._update_plot()
    app.processEvents()
    samples = []
    for _ in range(reps):
        win._plot_dirty = True
        win._update_plot()
        t0 = time.perf_counter()
        render_widget(win.plot, img)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return samples[len(samples) // 2]


print(f"plot 视口 {win.plot.width()}×{win.plot.height()} px")
print(f"{'曲线数':>6} {'窗口':>6} {'paint ms':>9} {'FPS 天花板':>11}")
for k in (0, 3, 5, 10, 20):
    set_curves(k)
    for win_s in ("10s", "30s", "120s"):
        win.window_combo.setCurrentText(win_s)
        ms = paint_ms()
        print(f"{k:>6} {win_s:>6} {ms:>9.2f} {1000 / ms:>11.0f}")

# 全窗 repaint（含表格/树/面板）——看「一次整窗重绘」的代价
set_curves(5)
win.window_combo.setCurrentText("30s")
w, h = win.width(), win.height()
full = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
render_widget(win, full)
samples = []
for _ in range(8):
    t0 = time.perf_counter()
    render_widget(win, full)
    samples.append((time.perf_counter() - t0) * 1000.0)
samples.sort()
print(f"\n整窗 repaint（{w}×{h}，5 条曲线）：{samples[len(samples) // 2]:.2f} ms")

# 观测台窗口 paint
win._toggle_rt_window()
app.processEvents()
rt = win.rt_window
rt.resize(1140, 900)
app.processEvents()
w2, h2 = rt.width(), rt.height()
rt_img = QImage(w2, h2, QImage.Format_ARGB32_Premultiplied)
render_widget(rt, rt_img)
samples = []
for _ in range(8):
    t0 = time.perf_counter()
    render_widget(rt, rt_img)
    samples.append((time.perf_counter() - t0) * 1000.0)
samples.sort()
print(f"观测台 repaint（{w2}×{h2}）：{samples[len(samples) // 2]:.2f} ms")



