"""截图：位置模式面板（确认 M27/M28/M29 手填系数行已删除）。

用法： .venv\\Scripts\\python.exe tools\\perf\\shot_cl_panel.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: E402

OUT = REPO / "run_data" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
M.load_layout_json = lambda: {}
win = M.ScopeWindow(default_port="COM_NONE")
win.resize(1600, 900)
win.show()
deadline = time.time() + 1.2
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)

box = next(b for b in win.findChildren(QGroupBox) if "负反馈闭环" in b.title())
dpr = win.devicePixelRatioF()
print(f"面板尺寸 {box.width()}x{box.height()} 逻辑，DPR={dpr}")

# 面板可能比屏幕高：按整块抓，若超高就分段
pm = box.grab()
pm.save(str(OUT / "cl_panel.png"))
print(f"已保存：{OUT / 'cl_panel.png'}  ({pm.width()}x{pm.height()} 设备像素)")

# 顺带确认：界面里已没有「ROLL系数 / PITCH系数」输入框
labels = [c.text() for c in box.findChildren(type(win.motor_info[27]))]
has_gain = any(("ROLL系数" in t) or ("PITCH系数" in t) for t in labels)
print(f"面板内仍存在手填系数输入框：{has_gain}")

win.close()
app.processEvents()
