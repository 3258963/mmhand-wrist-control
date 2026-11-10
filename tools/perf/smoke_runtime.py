"""端到端冒烟：让主窗真跑 4 秒事件循环（含定时器、排空、开关窗），
捕获任何回调异常。离屏，不连硬件。

用法： .venv\\Scripts\\python.exe tools/perf/smoke_runtime.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

errors: list[str] = []
_orig_hook = sys.excepthook


def hook(tp, val, tb):
    errors.append("".join(traceback.format_exception(tp, val, tb)))
    _orig_hook(tp, val, tb)


sys.excepthook = hook

app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")
win.show()

# 模拟上行包：磁编 + 舵机 + 状态，灌进 rx_queue 让 _drain_queue 真跑
n = 0


def fake_frames():
    global n
    now = time.monotonic()
    n += 1
    vals = [8000 + (n * 7 + j * 13) % 2000 for j in range(M.ENCODER_COUNT)]
    win.rx_queue.put(("enc_raw", now, vals))
    win.rx_queue.put(("servo_abs", now, [500, 600, 700]))
    win.rx_queue.put(("servo_telem", now, {
        "speed": [1, 2, 3], "load": [4, 5, 6], "current": [7, 8, 9],
        "volt": [12.0, 12.1, 12.2], "temp": [30.0, 31.0, 32.0]}))
    win.rx_queue.put(("status", now, {"state": 1, "control_enabled": 0, "owner": 0,
                                      "control_mode": 0, "servo_online": 0b111,
                                      "encoder_online": (1 << M.ENCODER_COUNT) - 1,
                                      "can_online": 1, "multiturn_unknown": 0,
                                      "direct_reject": 0}))


fk = QTimer()
fk.timeout.connect(fake_frames)
fk.start(7)

# 选中几条曲线，让 _update_plot 有活干
for key in ("enc_raw_16", "enc_raw_17", "m27_abs", "m28_abs"):
    ch = win.channels[key]
    ch.tree_item.setCheckState(0, M.Qt.Checked)

steps = []


def stage1():
    steps.append("打开观测台+参数窗")
    win._toggle_rt_window()
    win._toggle_watch_window()


def stage2():
    steps.append("X 关掉两个窗")
    win.rt_window.close()
    win.watch_window.close()


def stage3():
    steps.append("跑环降档（只翻状态位）")
    win.cl_enabled = True
    win._apply_run_prio()


def stage4():
    steps.append("停环恢复")
    win.cl_enabled = False
    win._apply_run_prio()


def finish():
    fk.stop()
    print("阶段：", " → ".join(steps))
    print(f"状态栏：{win.status_label.text()}")
    print(f"fps 计数：{getattr(win, '_plot_fps_last', 0)} | 表格行数 {win.enc_table.rowCount()}")
    print(f"窗口实例：RT={len(win.findChildren(M.RTensionWindow))} "
          f"Watch={len(win.findChildren(M.ParameterWatchWindow))}")
    if errors:
        print(f"\n❌ 捕获 {len(errors)} 个回调异常：")
        for e in errors[:3]:
            print(e)
        app.exit(1)
    else:
        print("\n✅ 4 秒事件循环无异常")
        app.exit(0)


for i, fn in enumerate((stage1, stage2, stage3, stage4), start=1):
    QTimer.singleShot(i * 800, fn)
QTimer.singleShot(4200, finish)

rc = app.exec()
win.close()
sys.exit(rc)
