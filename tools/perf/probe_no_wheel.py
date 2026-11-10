"""验证滚轮不会改变控制模式（以及其它下拉/数值框）。

Qt 默认：QComboBox/QAbstractSpinBox 有焦点时滚轮直接改值。控制模式被滚轮
误改会触发停环，属于事故级误操作；本探针钉住"滚轮不再改值"。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_no_wheel.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

rows: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


def wheel(widget, delta: int = -120) -> None:
    """向控件投递一次滚轮事件（向下滚一档）。"""
    pos = QPointF(widget.rect().center())
    ev = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


app = QApplication([])
M.load_layout_json = lambda: {}
win = M.ScopeWindow(default_port="COM_NONE")
win.show()          # 需要可见/有焦点才会走 QComboBox 的滚轮分支
app.processEvents()

print("=== 1. 控制模式：滚轮不得改 ===")
win.cl_mode_combo.setFocus()
before = win.cl_mode_combo.currentIndex()
for _ in range(3):
    wheel(win.cl_mode_combo, -120)
check("控制模式下拉未被滚轮改动",
      win.cl_mode_combo.currentIndex() == before,
      f"{before} → {win.cl_mode_combo.currentIndex()}")

print("=== 2. 步长 / 斜坡速率：滚轮不得改 ===")
win.step_combo.setFocus()
step_before = win.step_combo.currentText()
wheel(win.step_combo, -120)
check("步长下拉未被滚轮改动", win.step_combo.currentText() == step_before,
      f"{step_before} → {win.step_combo.currentText()}")
win.ramp_rate_spin.setFocus()
ramp_before = win.ramp_rate_spin.value()
wheel(win.ramp_rate_spin, 120)
check("斜坡速率数值未被滚轮改动", win.ramp_rate_spin.value() == ramp_before,
      f"{ramp_before} → {win.ramp_rate_spin.value()}")

print("=== 3. 反证：守卫拿掉后滚轮确实会改值（确认探针有效） ===")
app.removeEventFilter(getattr(app, "_no_wheel_guard"))
win.step_combo.setFocus()
step_before = win.step_combo.currentText()
wheel(win.step_combo, -120)
changed = win.step_combo.currentText() != step_before
check("去掉守卫后滚轮能改值（说明前面的 PASS 是真的被拦住了）", changed,
      f"{step_before} → {win.step_combo.currentText()}")
win._cl_timer.stop()
win._admit_timer.stop()
win._tension_poll_timer.stop()
win.hide()

print("\n=== 汇总 ===")
fails = [r for r in rows if not r[1]]
print(f"{len(rows) - len(fails)}/{len(rows)} 通过")
sys.exit(1 if fails else 0)
