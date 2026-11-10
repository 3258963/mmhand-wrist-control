"""截图：标出「限速斜坡」开关在界面上的位置。

用真实 Windows 平台起一次界面（不连串口、不自动连接），抓取控件所在区域并在
四周画红框，输出到 run_data/screenshots/。

用法： .venv\\Scripts\\python.exe tools\\perf\\shot_ramp_switch.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = REPO / "run_data" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
M.load_layout_json = lambda: {}          # 用默认布局，避免受用户存档影响
win = M.ScopeWindow(default_port="COM_NONE")
win.resize(1600, 900)
win.show()

# 让布局/样式刷完再抓
deadline = time.time() + 1.2
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)

target = win.ramp_check
pos = target.mapTo(win, QPoint(0, 0))
rect = QRect(pos, target.size())         # 复选框在窗口内的矩形
print(f"「{target.text()}」位置 x={rect.x()} y={rect.y()} w={rect.width()} h={rect.height()}")

full = win.grab()
dpr = full.devicePixelRatio()      # Windows 缩放 150%/175% 时 >1，copy() 要按设备像素
print(f"窗口 {win.width()}x{win.height()} 逻辑，抓图 {full.width()}x{full.height()} 设备像素，DPR={dpr}")

# 取一个能看清上下文的区域（右侧控制面板：步长行 + 限速斜坡 + 速率）
x0 = max(0, rect.x() - 330)
y0 = max(0, rect.y() - 210)
cw = min(full.width() / dpr - x0, 560)
ch = min(full.height() / dpr - y0, 300)
crop = QPixmap(int(cw * dpr), int(ch * dpr))
crop.setDevicePixelRatio(dpr)
p0 = QPainter(crop)
p0.drawPixmap(QPoint(0, 0), full,
              QRect(int(x0 * dpr), int(y0 * dpr), int(cw * dpr), int(ch * dpr)))
p0.end()

painter = QPainter(crop)
painter.setRenderHint(QPainter.Antialiasing, True)
pen = QPen(QColor("#ff2d2d"))
pen.setWidth(3)
painter.setPen(pen)
local = QRect(rect.x() - x0 - 6, rect.y() - y0 - 6, rect.width() + 12, rect.height() + 12)
painter.drawRoundedRect(local, 5, 5)
painter.setPen(QPen(QColor("#ff2d2d"), 2))
painter.drawLine(local.left() - 28, local.center().y(), local.left() - 2, local.center().y())
painter.end()
crop.save(str(OUT / "ramp_switch_area.png"))

# 同一个红框也画到整窗图上，便于知道它在界面哪个位置
painter = QPainter(full)
pen = QPen(QColor("#ff2d2d"))
pen.setWidth(4)
painter.setPen(pen)
painter.drawRoundedRect(QRect(rect.x() - 6, rect.y() - 6, rect.width() + 12, rect.height() + 12), 5, 5)
painter.end()
full.save(str(OUT / "ramp_switch_full.png"))

print(f"已保存：{OUT / 'ramp_switch_area.png'}")
print(f"已保存：{OUT / 'ramp_switch_full.png'}")
win.close()
app.processEvents()
