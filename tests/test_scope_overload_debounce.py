"""张力过载停环的**去抖**测试（2026-11-23）。

背景：目标贴着 f_max 时，内环一次正常超调（25.06 N vs 25 N）就把环停掉，
现场表现为"跑一会就自动停"。现在要求连续 `OVERLOAD_STOP_TICKS` 拍超限才停。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

import mmhand_scope as scope


@pytest.fixture(scope="module")
def win():
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = scope.ScopeWindow(default_port="COM_TEST")
    yield w
    w._admit_timer.stop()
    w._zero_timer.stop()
    w._ramp_timer.stop()
    w._cl_timer.stop()
    w.close()
    scope.load_layout_json = real_load
    app.processEvents()


def _feed(win, fvals):
    win._tension_last = (time.monotonic(), list(fvals))


def test_overload_needs_three_consecutive_ticks(win):
    stops = []
    win._stop_closed_loop = lambda reason, **kw: stops.append(reason)
    win._effective_flimits = lambda: (0.2, 25.0, True)
    win.wrist_calib = None
    win._overload_streak = 0

    _feed(win, (30.0, 1.0, 1.0))
    win._tension_guard(0.0, 0.0)
    assert stops == []                       # 第 1 拍：只计数，不停
    win._tension_guard(0.0, 0.0)
    assert stops == []                       # 第 2 拍：仍不停
    win._tension_guard(0.0, 0.0)
    assert stops and "张力过载" in stops[0]   # 第 3 拍：真停


def test_overload_streak_resets_between_bursts(win):
    stops = []
    win._stop_closed_loop = lambda reason, **kw: stops.append(reason)
    win._effective_flimits = lambda: (0.2, 25.0, True)
    win.wrist_calib = None
    win._overload_streak = 0

    _feed(win, (30.0, 1.0, 1.0))
    win._tension_guard(0.0, 0.0)
    win._tension_guard(0.0, 0.0)
    _feed(win, (1.0, 1.0, 1.0))              # 回到正常 → 计数清零
    win._tension_guard(0.0, 0.0)
    _feed(win, (30.0, 1.0, 1.0))
    win._tension_guard(0.0, 0.0)
    win._tension_guard(0.0, 0.0)
    assert stops == []                       # 两段各 2 拍，都不该停
    win._tension_guard(0.0, 0.0)
    assert stops and "张力过载" in stops[0]   # 第三段连续 3 拍才停
