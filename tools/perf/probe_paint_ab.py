"""严格 A/B：同一进程、同一批曲线、同一个 _update_plot，只换降采样策略。

A 现状      : 曲线由 App 代码路径创建（downsample=4 + autoDownsample）
B auto ds=1 : 把 ds 下限从 4 改成 1（auto 仍开）
C 固定 ds   : auto 关，按窗口宽度固定 ds ≈ 1 点/像素
D 预抽稀    : 自己保峰抽稀到 2 点/像素后 setData，pyqtgraph 不再降采样

每档都记录「真正画出多少点」和 paint 毫秒。
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
    ch.buf.head, ch.buf.count = 0, ch.buf.capacity
win._latest_t = SECONDS

KEYS = [f"enc_raw_{j}" for j in range(21)]
img = QImage(916, 626, QImage.Format_ARGB32_Premultiplied)


def pick(n_curves):
    for key in KEYS:
        ch = win.channels[key]
        if ch.curve is not None:
            win.plot.removeItem(ch.curve)
            ch.curve = None
    for key in KEYS[:n_curves]:
        ch = win.channels[key]
        # 与 App 完全一致的创建参数
        ch.curve = win.plot.plot(pen=M.pg.mkPen(ch.color, width=1), name=ch.name,
                                 downsample=4, autoDownsample=True)


def peak_decimate(t, v, max_pts):
    n = t.size
    if n <= max_pts or max_pts < 4:
        return t, v
    step = int(math.ceil(n / max(2, max_pts // 2)))
    if step <= 1:
        return t, v
    m = (n // step) * step
    if m < step * 2:
        return t, v
    blk = v[:m].reshape(-1, step)
    lo = np.fmin.reduce(blk, axis=1)
    hi = np.fmax.reduce(blk, axis=1)
    dt = t[1] - t[0] if n > 1 else 1.0
    tb = t[:m:step] + (step - 1) * 0.5 * dt
    x = np.repeat(tb, 2)
    y = np.empty(lo.size * 2, dtype=v.dtype)
    y[0::2] = lo
    y[1::2] = hi
    if m < n:
        x = np.concatenate((x, t[m:]))
        y = np.concatenate((y, v[m:]))
    return x, y


_px = 0


def plot_px():
    global _px
    _px = int(win.plot.getViewBox().width()) or win.plot.width()
    return _px


def run_update(decimate_to=None):
    """App 原本的 _update_plot；decimate_to 不为 None 时先抽稀。"""
    if decimate_to is None:
        win._update_plot()
        return
    tail = float(win.window_combo.currentText().rstrip("s"))
    for ch in win.channels.values():
        if ch.curve is None:
            continue
        t, v = ch.buf.series(tail)
        t, v = peak_decimate(t, v, decimate_to)
        ch.curve.setData(t, v, skipFiniteCheck=True)
    if win.xauto_check.isChecked() and win._latest_t is not None:
        vb = win.plot.getViewBox()
        vb.disableAutoRange(axis=M.ViewBox.XAxis)
        vb.setXRange(max(0.0, win._latest_t - tail), win._latest_t, padding=0)


def measure(decimate_to=None, reps=10):
    run_update(decimate_to)
    app.processEvents()
    s = []
    for _ in range(reps):
        run_update(decimate_to)
        p = QPainter(img)
        t0 = time.perf_counter()
        win.plot.render(p)
        s.append((time.perf_counter() - t0) * 1000.0)
        p.end()
    s.sort()
    pts = []
    for ch in win.channels.values():
        if ch.curve is None:
            continue
        try:
            xd, _ = ch.curve.getData()
            pts.append(0 if xd is None else len(xd))
        except Exception:
            pass
    return s[len(s) // 2], (max(pts) if pts else 0), len(pts)


px = plot_px()
print(f"视口 {win.plot.width()}×{win.plot.height()} px，ViewBox 宽 {px}")
print(f"{'曲线':>4} {'窗口':>5} {'档位':>16} {'每条点数':>9} {'paint ms':>9} {'FPS天板':>9}")
for k in (5, 20):
    pick(k)
    for win_s in ("30s", "120s"):
        win.window_combo.setCurrentText(win_s)
        # A 现状
        ms, pts, n = measure()
        print(f"{k:>4} {win_s:>5} {'A 现状(ds=4,auto)':>16} {pts:>9} {ms:>9.2f} {1000 / ms:>9.0f}")
        # B auto ds 下限 1
        for key in KEYS:
            ch = win.channels[key]
            if ch.curve is not None:
                ch.curve.setDownsampling(ds=1, auto=True)
        ms, pts, n = measure()
        print(f"{k:>4} {win_s:>5} {'B auto(ds下限=1)':>16} {pts:>9} {ms:>9.2f} {1000 / ms:>9.0f}")
        # C 固定 ds = n/px
        tail = float(win_s.rstrip("s"))
        n_pts = int(tail * 150)
        ds = max(1, int(round(n_pts / px)))
        for key in KEYS:
            ch = win.channels[key]
            if ch.curve is not None:
                ch.curve.setDownsampling(ds=ds, auto=False)
        ms, pts, n = measure()
        print(f"{k:>4} {win_s:>5} {f'C 固定ds={ds}':>16} {pts:>9} {ms:>9.2f} {1000 / ms:>9.0f}")
        # D 预抽稀 2 点/像素 + auto 关
        for key in KEYS:
            ch = win.channels[key]
            if ch.curve is not None:
                ch.curve.setDownsampling(ds=1, auto=False)
        ms, pts, n = measure(decimate_to=2 * px)
        print(f"{k:>4} {win_s:>5} {'D 预抽稀2点/px':>16} {pts:>9} {ms:>9.2f} {1000 / ms:>9.0f}")
