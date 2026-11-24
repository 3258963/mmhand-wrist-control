"""图区交互：悬停读数（最近采样点）+ 双击加/删水平标记线。

2026-11-24 新增功能，覆盖：
- 悬停浮层出现、列出该 x 上每条可见曲线的采样值、并高亮这些采样点；
- 双击图区加一条标记线，双击该线（±6px）删除它；
- 多条标记线时只删命中的那一条；
- 鼠标离开图区后浮层收起。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import mmhand_scope as scope

# 其它测试模块可能把 ScopeWindow._save_layout 换成 no-op（类属性、全局生效）。
# 这里记下导入时的真身，存档用例里显式还原，保证与运行顺序无关。
_REAL_SAVE_LAYOUT = scope.ScopeWindow._save_layout


@pytest.fixture(scope="module")
def win():
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}
    app = QApplication.instance() or QApplication([])
    w = scope.ScopeWindow(default_port="COM_TEST")
    w.show()
    # 灌 30s 数据（两条曲线）
    t = 0.0
    for _ in range(3000):
        t += 0.01
        w.channels["enc_raw_16"].buf.append(t, 8200 + 600 * math.sin(t))
        w.channels["m27_abs"].buf.append(t, 5000 + 900 * math.sin(0.5 * t))
    w._latest_t = t
    for key in ("enc_raw_16", "m27_abs"):
        w.channels[key].tree_item.setCheckState(0, Qt.Checked)
    w._plot_dirty = True
    w._update_plot()
    app.processEvents()
    yield w
    w._admit_timer.stop()
    w._zero_timer.stop()
    w._ramp_timer.stop()
    w._cl_timer.stop()
    w.close()
    scope.load_layout_json = real_load
    app.processEvents()


def _dbl(win, view_x: float, view_y: float) -> None:
    vb = win.plot.getPlotItem().vb
    wp = win.plot.mapFromScene(vb.mapViewToScene(QPointF(view_x, view_y)))
    ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(wp), QPointF(wp),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    win.plot.mouseDoubleClickEvent(ev)


def test_hover_shows_nearest_sample(win):
    vb = win.plot.getPlotItem().vb
    win._on_plot_mouse_moved(vb.mapViewToScene(QPointF(15.0, 8600.0)))
    tip = win._hover_tip
    assert tip.isVisible()
    text = tip.text()
    assert "J16 raw" in text and "M27 ABS" in text
    # 每条可见曲线一个高亮点
    assert len(win._hover_dots.data) == 2
    # 读数应该取自 15s 附近的采样（t 步长 0.01，容差一拍）
    assert "14.9" in text or "15.0" in text


def test_hover_hides_on_leave(win):
    vb = win.plot.getPlotItem().vb
    win._on_plot_mouse_moved(vb.mapViewToScene(QPointF(15.0, 8000.0)))
    assert win._hover_tip.isVisible()
    win._hide_hover()
    assert not win._hover_tip.isVisible()
    assert len(win._hover_dots.data) == 0


def test_double_click_adds_and_removes_marker(win):
    win._h_markers.clear()
    _dbl(win, 12.0, 8600.0)
    assert len(win._h_markers) == 1
    y = win._h_markers[0].value()
    assert 8400 < y < 8800
    # 同一位置再双击 → 删除
    _dbl(win, 12.0, 8600.0)
    assert len(win._h_markers) == 0


def test_markers_delete_individually(win):
    win._h_markers.clear()
    for yy in (4300.0, 5200.0, 6100.0):
        _dbl(win, 10.0, yy)
    assert len(win._h_markers) == 3
    _dbl(win, 10.0, 5200.0)          # 只删中间那条
    ys = sorted(round(m.value()) for m in win._h_markers)
    assert len(ys) == 2
    assert all(abs(v - 5200) > 100 for v in ys)
    for m in list(win._h_markers):
        win._remove_h_marker(m)
    assert len(win._h_markers) == 0


def test_double_click_outside_viewbox_ignored(win):
    win._h_markers.clear()
    # 图区外的点（左下角外边距）不应加标记线
    ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(2, 2), QPointF(2, 2),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    win.plot.mouseDoubleClickEvent(ev)
    assert len(win._h_markers) == 0


def test_clear_button_removes_markers(win):
    """「清空」按钮 = 清曲线数据 + 清标记线（用户 2026-11-24 定案）。"""
    win._clear_h_markers()
    _dbl(win, 10.0, 5000.0)
    _dbl(win, 10.0, 6000.0)
    assert len(win._h_markers) == 2
    win._clear_buffers()
    assert len(win._h_markers) == 0


def test_markers_persist_across_restart(win, monkeypatch):
    """标记线写进布局存档，重启后按原 y 恢复。"""
    captured = {}
    monkeypatch.setattr(scope, "save_layout_json", lambda d: captured.update(d))
    monkeypatch.setattr(scope.ScopeWindow, "_save_layout", _REAL_SAVE_LAYOUT)
    # _save_layout 在离屏测试里会主动跳过写盘，这里临时把平台串换掉
    monkeypatch.setenv("QT_QPA_PLATFORM", "minimal")
    win._clear_h_markers()
    _dbl(win, 10.0, 5000.0)
    _dbl(win, 10.0, 6000.0)
    win._save_layout()
    assert len(captured.get("h_markers", [])) == 2

    saved = dict(captured)
    monkeypatch.setattr(scope, "load_layout_json", lambda: saved)
    w2 = scope.ScopeWindow(default_port="COM_TEST")
    try:
        ys = sorted(round(m.value(), 1) for m in w2._h_markers)
        assert len(ys) == 2
        assert abs(ys[0] - 5000) < 80 and abs(ys[1] - 6000) < 80
    finally:
        w2._admit_timer.stop()
        w2._zero_timer.stop()
        w2._ramp_timer.stop()
        w2._cl_timer.stop()
        w2.close()
