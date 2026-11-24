"""舵机信息窗（2026-11-20）的单测：只测数据装配，不碰串口/文件。

窗口的数据全部来自已有上行通道（ABS/raw/speed/load/current/volt/temp）
与 `scope.servo_range`（0x13 会话逻辑行程）。这里验证：
  · 有遥测 → 对应单元格显示数值
  · 无遥测 → 显示 “—”
  · 无 servo_range → 逻辑行程列为 “—”，行程宽度为 “—”
  · 有 servo_range 且位图命中 → 显示 min/max 与宽度
"""
import math

import pytest

import mmhand_scope as scope


@pytest.fixture()
def win():
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = scope.ScopeWindow(default_port="COM_TEST")
    yield w
    for name in ("_admit_timer", "_zero_timer", "_ramp_timer", "_cl_timer",
                 "_ui_drain_timer", "_cl_snapshot_timer"):
        t = getattr(w, name, None)
        if t is not None:
            t.stop()
    w.close()
    scope.load_layout_json = real_load


def _feed(win, motor: int, **fields):
    for key, value in fields.items():
        ch = win.channels.get(f"m{motor}_{key}")
        assert ch is not None, key
        ch.buf.append(1.0, float(value))


def test_row_without_telemetry_shows_dash(win):
    info = scope.ServoInfoWindow(win)
    try:
        row = info._row_values(28)
        assert row[0] == "M28"
        assert row[3] == "—"          # ABS 无数据
        assert row[5] == "—"          # 速度无数据
        assert row[10] == "—" and row[11] == "—"   # 逻辑行程未请求
        assert row[12] == "—"         # 行程宽度
    finally:
        info.close()


def test_row_with_telemetry(win):
    win.armed = True
    win._motor_origin[27] = 4900
    win.targets[27] = 5010
    _feed(win, 27, abs=5000, raw=120, speed=-123, load=45,
          current=3, volt=11.8, temp=33)
    info = scope.ServoInfoWindow(win)
    try:
        row = info._row_values(27)
        assert row[3] == "+5000"
        assert row[4] == "+120"
        assert row[5] == "-123"       # 舵机自报速度（counts/s）
        assert row[8] == "+11.8"
        assert row[13] == "+4900" and row[14] == "+5010"
        assert row[15] == "+100"      # 累计 = 实测 − 起点
    finally:
        info.close()


def test_logical_range_from_state_sync(win):
    win.servo_range = {"bitmap": 1 << 27,
                       "min": [0] * 30, "max": [0] * 30}
    win.servo_range["min"][27] = 300
    win.servo_range["max"][27] = 6300
    info = scope.ServoInfoWindow(win)
    try:
        row = info._row_values(27)
        assert row[10] == "+300" and row[11] == "+6300"
        assert row[12] == "6000"
        # 未命中的通道仍留 “—”
        assert info._row_values(28)[10] == "—"
    finally:
        info.close()


def test_cols_count_matches_table(win):
    info = scope.ServoInfoWindow(win)
    try:
        assert info.table.columnCount() == len(scope.ServoInfoWindow.COLS)
        assert info.table.rowCount() == len(scope.SERVO_TARGETS)
    finally:
        info.close()
