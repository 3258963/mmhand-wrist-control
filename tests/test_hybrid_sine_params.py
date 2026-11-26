"""混合模式正弦参数的**独立性**测试（2026-11-26）。

背景：混合正弦原来读的是张力行的 `sine_amp/sine_hz/sine_phase/sine_sign`，
而那一行在混合模式下整行隐藏 → 用户完全改不了（实机验证 isVisible()=False）。
现在改成混合行自己的一套：`c1_sine_*` + `ang_sine_*` + `c1_auto_rounds`。

本文件用 stub 直接调未绑定的 `_c1_test_override`，不建窗口；
「张力行给一组完全不同的值」用来证明混合正弦不再读它。
"""
import math
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import mmhand_scope as scope
from wrist_control_law import WristControlParams
from wrist_hybrid_control import C1TensionParams, HybridWristParams


class _FakeCheck:
    def __init__(self, on=False):
        self._on = on

    def isChecked(self):
        return self._on


class _FakeEdit:
    def __init__(self, t):
        self._t = str(t)

    def text(self):
        return self._t

    def setText(self, v):
        self._t = str(v)


def _params():
    return HybridWristParams(
        WristControlParams(), 5.0, -10.0,
        C1TensionParams(target_n=5.0, kp=5.0, ki=0.0, kd=0.0, ff_gain=0.0,
                        max_step=5, travel=3000, i_limit=5, min_n=0.2, max_n=25.0))


class _Stub:
    """只提供 `_c1_test_override` 用到的成员。"""

    MIX_STAGE_MANUAL = -1
    MIX_STAGE_DONE = -2
    _c1_fval = scope.ScopeWindow._c1_fval
    _c1_test_override = scope.ScopeWindow._c1_test_override

    def __init__(self, auto=False, sine=True, **edits):
        base = {
            "c1_pos_min_n": "0.2", "c1_pos_max_n": "25", "pos_limit": "25",
            "c1_sine_amp": "3", "c1_sine_hz": "0.25", "c1_sine_phase": "0",
            "c1_sine_sign": "1", "c1_auto_rounds": "3",
            "ang_sine_hz": "0.2", "ang_sine_roll": "0", "ang_sine_pitch": "0",
        }
        base.update({k: str(v) for k, v in edits.items()})
        self._c1_position_edits = {k: _FakeEdit(v) for k, v in base.items()}
        self.cl_c1_auto_check = _FakeCheck(auto)
        self.cl_c1_sine_check = _FakeCheck(sine)
        self._auto_t0_pc = None
        self._auto_stage = -1
        self._auto_kind = ""
        self._sine_t0 = 0.0

    # 张力行：故意返回一组完全不同的值 → 混合正弦若还读它就必然露馅
    def _cl_fval(self, key, default, lo, hi):
        return 99.0

    def _cl_fval3(self, key, default, lo, hi):
        return [99.0, 99.0, 99.0]


def _at(stub, t_offset):
    """把正弦时间基准拨到 `t_offset` 秒后再取一拍。"""
    stub._sine_t0 = time.monotonic() - t_offset
    return stub._c1_test_override(_params())


# ---------------- 1. 参数独立性 ----------------

def test_c1_sine_uses_hybrid_row_not_tension_row():
    """张力行说 99N/99Hz，混合行说 3N/0.25Hz → 必须用 3N/0.25Hz。"""
    s = _Stub()
    p2, _stage, kind, _note, done = _at(s, 0.0)
    assert kind == "sine" and not done
    # t=0 时 sin=0 → 起点就是基值，与幅度无关
    assert p2.c1.target_n == pytest.approx(5.0, abs=1e-6)


def test_c1_sine_amplitude_from_hybrid_row():
    """四分之一周期处应达到 基值 + 幅度（=8 N），而不是基值+99。"""
    s = _Stub(c1_sine_amp="3", c1_sine_hz="0.25")
    p2, *_ = _at(s, 0.25 / 0.25)          # 1 s = 1/4 周期
    assert p2.c1.target_n == pytest.approx(8.0, abs=1e-3)


def test_c1_sine_sign_negative():
    s = _Stub(c1_sine_amp="3", c1_sine_hz="0.25", c1_sine_sign="-1")
    p2, *_ = _at(s, 1.0)
    assert p2.c1.target_n == pytest.approx(2.0, abs=1e-3)


def test_c1_sine_phase_shifts_start():
    """相位 90° → t=0 时 sin=1，直接就在峰值。"""
    s = _Stub(c1_sine_amp="2", c1_sine_phase="90")
    p2, *_ = _at(s, 0.0)
    assert p2.c1.target_n == pytest.approx(7.0, abs=1e-3)


def test_c1_sine_clamped_to_bounds():
    s = _Stub(c1_pos_target="24", c1_sine_amp="5", c1_sine_hz="0.25", c1_pos_max_n="25")
    p2, *_ = _at(s, 1.0)
    assert p2.c1.target_n <= 25.0 + 1e-9


# ---------------- 2. 角度正弦 ----------------

def test_angle_sine_off_keeps_targets():
    s = _Stub()
    p2, *_ = _at(s, 1.0)
    assert p2.roll_target_deg == pytest.approx(5.0)
    assert p2.pitch_target_deg == pytest.approx(-10.0)


def test_roll_sine_only():
    s = _Stub(ang_sine_roll="5", ang_sine_hz="0.2", ang_sine_pitch="0")
    p2, *_ = _at(s, 0.25 / 0.2)           # 1/4 周期
    assert p2.roll_target_deg == pytest.approx(10.0, abs=1e-3)
    assert p2.pitch_target_deg == pytest.approx(-10.0, abs=1e-6)


def test_pitch_sine_only():
    s = _Stub(ang_sine_pitch="4", ang_sine_hz="0.2", ang_sine_roll="0")
    p2, *_ = _at(s, 0.25 / 0.2)
    assert p2.roll_target_deg == pytest.approx(5.0, abs=1e-6)
    assert p2.pitch_target_deg == pytest.approx(-6.0, abs=1e-3)


def test_dual_axis_sine_uses_own_amplitudes():
    s = _Stub(ang_sine_roll="5", ang_sine_pitch="2", ang_sine_hz="0.2")
    p2, *_ = _at(s, 0.25 / 0.2)
    assert p2.roll_target_deg == pytest.approx(10.0, abs=1e-3)
    assert p2.pitch_target_deg == pytest.approx(-8.0, abs=1e-3)


def test_angle_sine_respects_limit():
    s = _Stub(ang_sine_roll="50", ang_sine_hz="0.2", pos_limit="10")
    p2, *_ = _at(s, 0.25 / 0.2)
    assert abs(p2.roll_target_deg) <= 10.0 + 1e-9


# ---------------- 3. 与自动调参互斥 ----------------

def test_auto_tune_ignores_sine_fields():
    """自动调参开着时走序列目标，不被正弦字段影响（这里 t≈0 → 第 0 档保持）。"""
    s = _Stub(auto=True, sine=False, c1_sine_amp="99", ang_sine_roll="30")
    p2, stage, kind, _note, done = _at(s, 0.0)
    assert stage == 0 and kind == "hold" and not done
    assert p2.c1.target_n == pytest.approx(5.0)
    assert p2.roll_target_deg == pytest.approx(5.0)
