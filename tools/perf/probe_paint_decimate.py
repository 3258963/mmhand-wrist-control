"""验证「先自己峰值抽稀、再 setData」对 paint 的收益。

pyqtgraph 的 auto downsampling 发生在 paint 内、对原始数组做 O(n) 处理：
120s@150Hz=18000 点 × 20 条曲线，每帧都要走一遍 → 28.8ms。
若在喂之前先把每个窗口抽到 ~2 点/像素（保峰：每 bin 取 min/max），
pyqtgraph 只需处理 ~1800 点 → paint 应降到个位数毫秒。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_paint_decimate.py
"""
from __future__ import annotations

import math
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
    # 打几个尖峰，验证保峰抽稀不会丢
    ch.buf.v[::997] += 600
    ch.buf.head, ch.buf.count = 0, ch.buf.capacity
win._latest_t = SECONDS

KEYS = [f"enc_raw_{j}" for j in range(21)]
img = QImage(916, 626, QImage.Format_ARGB32_Premultiplied)


def peak_decimate(t: np.ndarray, v: np.ndarray, max_pts: int):
    """保峰抽稀：每 bin 取 min/max 两点。NaN 用 fmin/fmax 保留断口。"""
    n = t.size
    if n <= max_pts or max_pts < 4:
        return t, v
    bins = max(2, max_pts // 2)
    step = int(math.ceil(n / bins))
    if step <= 1:
        return t, v
    m = (n // step) * step
    if m < step * 2:
        return t, v
    block_v = v[:m].reshape(-1, step)
    lo = np.fmin.reduce(block_v, axis=1)
    hi = np.fmax.reduce(block_v, axis=1)
    tb = t[:m:step] + ((step - 1) * 0.5) * (t[1] - t[0] if n > 1 else 1.0)
    x = np.repeat(tb, 2)
    y = np.empty(lo.size * 2, dtype=v.dtype)
    y[0::2] = lo
    y[1::2] = hi
    if m < n:                       # 余段原样接上
        x = np.concatenate((x, t[m:]))
        y = np.concatenate((y, v[m:]))
    return x, y


def set_curves(k):
    for key in KEYS:
        ch = win.channels[key]
        if ch.curve is not None:
            win.plot.removeItem(ch.curve)
            ch.curve = None
    for key in KEYS[:k]:
        ch = win.channels[key]
        ch.curve = win.plot.plot(pen=M.pg.mkPen(ch.color, width=1), name=ch.name,
                                 downsample=1, autoDownsample=True)


def encode(max_pts=None):
    """按窗口取数，可选先抽稀，再 setData。"""
    tail = float(win.window_combo.currentText().rstrip("s"))
    for ch in win.channels.values():
        if ch.curve is None:
            continue
        t, v = ch.buf.series(tail)
        if max_pts is not None:
            t, v = peak_decimate(t, v, max_pts)
        ch.curve.setData(t, v, skipFiniteCheck=True)


def paint_ms(max_pts, reps=10):
    encode(max_pts)
    app.processEvents()
    s = []
    for _ in range(reps):
        encode(max_pts)
        p = QPainter(img)
        t0 = time.perf_counter()
        win.plot.render(p)
        s.append((time.perf_counter() - t0) * 1000.0)
        p.end()
    s.sort()
    return s[len(s) // 2]


def encode_ms(max_pts, reps=10):
    s = []
    for _ in range(reps):
        t0 = time.perf_counter()
        encode(max_pts)
        s.append((time.perf_counter() - t0) * 1000.0)
    s.sort()
    return s[len(s) // 2]


px = win.plot.getViewBox().width() or win.plot.width()
print(f"视口 {win.plot.width()}×{win.plot.height()} px（ViewBox 宽 {px:.0f}）")
print(f"{'曲线':>4} {'窗口':>5} {'原始':>8} {'抽稀到':>6} {'encode ms':>10} {'paint ms':>9} {'合计':>7}")
for k in (5, 10, 20):
    set_curves(k)
    for win_s in ("30s", "120s"):
        win.window_combo.setCurrentText(win_s)
        for target in (None, int(2 * px), int(px)):
            e = encode_ms(target)
            p = paint_ms(target)
            tag = "不抽稀" if target is None else str(target)
            print(f"{k:>4} {win_s:>5} {'18k' if win_s == '120s' else '4.5k':>8} {tag:>6} "
                  f"{e:>10.2f} {p:>9.2f} {e + p:>7.2f}")
