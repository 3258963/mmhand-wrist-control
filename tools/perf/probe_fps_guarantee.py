"""验收：全 60FPS 能不能守住。

测「一帧」的真实成本 = _update_plot（取数+抽稀+setData）+ paint（真实渲染），
并在重载场景（20 条曲线 / 120s 窗口）下跑 240 帧，看自适应阀门
_adapt_density 是否把每帧压进 16.6ms（60FPS 预算）。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_fps_guarantee.py
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

img = QImage(1000, 700, QImage.Format_ARGB32_Premultiplied)


def select(keys):
    """先全不选再选目标：否则已勾选项 setCheckState 不发信号，曲线不会被重建。"""
    for ch in win.channels.values():
        if ch.tree_item.checkState(0) != M.Qt.Unchecked:
            ch.tree_item.setCheckState(0, M.Qt.Unchecked)
    for ch in win.channels.values():
        if ch.curve is not None:
            win.plot.removeItem(ch.curve)
            ch.curve = None
    for k in keys:
        win.channels[k].tree_item.setCheckState(0, M.Qt.Checked)
    app.processEvents()


def one_frame():
    """一帧 = 更新 + 真渲染（和真实 paint 同一条路径）。"""
    t0 = time.perf_counter()
    win._update_plot()
    mid = time.perf_counter()
    p = QPainter(img)
    win.plot.render(p)
    p.end()
    end = time.perf_counter()
    return (mid - t0) * 1000.0, (end - mid) * 1000.0


def run(tag, frames=240):
    win._pts_per_px = 2.0
    win.plot.paint_ema_ms = 0.0
    for _ in range(5):
        one_frame()
    upd, pnt = [], []
    for _ in range(frames):
        u, p = one_frame()
        win.plot.paint_ema_ms = (p if not win.plot.paint_ema_ms
                                 else win.plot.paint_ema_ms * 0.9 + p * 0.1)
        win._adapt_density()
        upd.append(u)
        pnt.append(p)
    tot = [u + p for u, p in zip(upd, pnt)]
    tot.sort()
    n = len(tot)
    avg = sum(tot) / n
    print(f"{tag:<26} update {sum(upd) / n:5.2f} | paint {sum(pnt) / n:5.2f} | "
          f"合计 均值 {avg:5.2f} p95 {tot[int(n * 0.95)]:5.2f} | "
          f"→ {1000 / avg:5.0f} FPS | 密度 {win._pts_per_px:.2f}px")


print(f"PLOT_HZ={M.PLOT_HZ}  60FPS 预算 16.6ms")
select(["enc_raw_16", "enc_raw_17", "m27_abs", "m28_abs", "m29_abs"])
win.window_combo.setCurrentText("30s")
run("5 条 / 30s")

preset = M.ScopeWindow.PRESETS["腕部调试"]
select(preset)
run(f"{len(preset)} 条 / 30s（腕部预设）")

select([f"enc_raw_{j}" for j in range(20)])
win.window_combo.setCurrentText("30s")
run("20 条 / 30s")

win.window_combo.setCurrentText("120s")
run("20 条 / 120s（最重）")

select([f"enc_raw_{j}" for j in range(21)])
run("21 条 / 120s（全磁编+120s）")
