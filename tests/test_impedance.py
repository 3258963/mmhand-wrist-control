"""阻抗外环（2026-11-22 框架）的测试。

`wrist_impedance_torque` 只做一件事：位置误差 → 力矩目标。
所以测试也只看这几条：
  · e=0 → 只输出 τ_ff
  · 刚度符号（偏离正方向 → 反向回中力矩）
  · 死区
  · 阻尼项方向
  · τ_max 钳制
  · K=0 时退化成纯力矩（等于 τ_ff）
  · NaN 断口语义
"""
import math

import pytest

from wrist_impedance import (IMP_NO_TARGET, IMP_OK, IMP_TAU_CLAMPED,
                             WristImpedanceParams, gravity_tau_sine,
                             wrist_impedance_torque)


def _p(**kw):
    base = dict(k_roll=0.5, k_pitch=0.5, d_roll=0.0, d_pitch=0.0,
                tau_ff=(0.0, 0.0), tau_r_max=0.0, tau_p_max=0.0,
                deadband_deg=0.0)
    base.update(kw)
    return WristImpedanceParams(**base)


DEG2RAD = math.pi / 180.0


# ---------------- 弹簧项 ----------------

def test_zero_error_gives_tau_ff_only():
    p = _p(tau_ff=(0.02, -0.03))
    tr, tp, fl = wrist_impedance_torque(p, 0.0, 0.0, 0.0, 0.0)
    assert (tr, tp) == pytest.approx((0.02, -0.03))
    assert fl == IMP_OK


def test_spring_restores_toward_target():
    """实际角偏离目标 +10° → 力矩应把它拉回（符号与误差相反方向的反作用）。"""
    p = _p(k_pitch=0.5)
    # 目标 0°，实际 +10° → e = -10° → τ_p = 0.5 × (-10°→rad) < 0
    tr, tp, fl = wrist_impedance_torque(p, 0.0, 10.0, 0.0, 0.0)
    assert tp == pytest.approx(0.5 * (-10.0) * DEG2RAD)
    assert tp < 0.0
    assert tr == 0.0 and fl == IMP_OK


def test_stiffness_scales_linearly():
    p = _p(k_roll=0.4)
    for e in (1.0, 5.0, 10.0):
        tr, _tp, _fl = wrist_impedance_torque(p, 0.0, 0.0, e, 0.0)
        assert tr == pytest.approx(0.4 * e * DEG2RAD)


def test_k_zero_is_pure_torque():
    """K=0 ⟹ 退化成纯力矩控制：输出等于 τ_ff，与位置无关。"""
    p = _p(k_roll=0.0, k_pitch=0.0, tau_ff=(0.1, -0.2))
    for roll, pitch in ((0, 0), (5, -12), (-20, 30)):
        tr, tp, _fl = wrist_impedance_torque(p, roll, pitch, 0.0, 0.0)
        assert (tr, tp) == pytest.approx((0.1, -0.2))


# ---------------- 死区 ----------------

def test_deadband_zeroes_small_error():
    p = _p(k_pitch=0.5, deadband_deg=0.5)
    tr, tp, _fl = wrist_impedance_torque(p, 0.0, 0.3, 0.0, 0.0)
    assert tp == 0.0                       # 0.3° < 0.5° 死区
    tr, tp, _fl = wrist_impedance_torque(p, 0.0, 2.0, 0.0, 0.0)
    assert tp != 0.0                       # 超出死区


# ---------------- 阻尼项 ----------------

def test_damping_follows_rate_sign():
    p = _p(k_roll=0.0, k_pitch=0.0, d_roll=0.1, d_pitch=0.1)
    tr, tp, _fl = wrist_impedance_torque(p, 0.0, 0.0, 0.0, 0.0,
                                        droll_dps=20.0, dpitch_dps=-20.0)
    assert tr == pytest.approx(0.1 * 20.0 * DEG2RAD)
    assert tp == pytest.approx(0.1 * -20.0 * DEG2RAD)


# ---------------- 钳制 ----------------

def test_tau_max_clamps_and_flags():
    p = _p(k_pitch=1.0, tau_p_max=0.05)
    _tr, tp, fl = wrist_impedance_torque(p, 0.0, 30.0, 0.0, 0.0)  # 30° × 1.0 = 0.52
    assert tp == pytest.approx(-0.05)
    assert fl & IMP_TAU_CLAMPED


def test_no_clamp_when_limit_zero():
    p = _p(k_pitch=1.0, tau_p_max=0.0)     # 0 = 不限
    _tr, tp, fl = wrist_impedance_torque(p, 0.0, 30.0, 0.0, 0.0)
    assert abs(tp) > 0.5
    assert fl == IMP_OK


# ---------------- 错误路径 ----------------

def test_nan_input_returns_break_semantics():
    p = _p()
    tr, tp, fl = wrist_impedance_torque(p, float("nan"), 0.0, 0.0, 0.0)
    assert math.isnan(tr) and math.isnan(tp)
    assert fl & IMP_NO_TARGET


def test_params_validation():
    with pytest.raises(ValueError):
        WristImpedanceParams(k_roll=-1.0, k_pitch=0.5)
    with pytest.raises(ValueError):
        WristImpedanceParams(k_roll=0.5, k_pitch=0.5, tau_ff=(1.0,))
    with pytest.raises(ValueError):
        WristImpedanceParams(k_roll=0.5, k_pitch=0.5, deadband_deg=-1.0)


# ---------------- 重力前馈：串列式正弦模型（**自动取反 + roll 耦合**） ----------------

def test_gravity_sine_zero_at_zero():
    """q=(0,0) → 两个力矩都为 0。"""
    tr, tp = gravity_tau_sine(0.3, 0.3, 0.0, 0.0)
    assert tr == pytest.approx(0.0)
    assert tp == pytest.approx(0.0)


def test_gravity_roll_max_at_90_negated():
    """roll=90° → τ_ff_roll = −A（重力要取反）。"""
    tr, _tp = gravity_tau_sine(0.3, 0.3, 90.0, 0.0)
    assert tr == pytest.approx(-0.3)


def test_gravity_pitch_max_at_90_when_roll_zero_negated():
    """roll=0、pitch=90° → τ_ff_pitch = −A。"""
    _tr, tp = gravity_tau_sine(0.3, 0.3, 0.0, 90.0)
    assert tp == pytest.approx(-0.3)


def test_gravity_pitch_offset_by_cos_roll():
    """**串列耦合**：roll 转动削弱 pitch 的重力矩（cos(roll)）。"""
    _tr0, tp0 = gravity_tau_sine(0.3, 0.3, 0.0, 90.0)
    _tr60, tp60 = gravity_tau_sine(0.3, 0.3, 60.0, 90.0)
    _tr90, tp90 = gravity_tau_sine(0.3, 0.3, 90.0, 90.0)
    assert tp0 == pytest.approx(-0.3)
    assert tp60 == pytest.approx(-0.3 * math.cos(math.radians(60.0)))
    assert tp90 == pytest.approx(0.0, abs=1e-12)     # roll=90 → pitch 轴与重力平行


def test_gravity_roll_not_affected_by_pitch():
    """外轴不感受内轴：pitch 变化不影响 τ_ff_roll。"""
    tr_a, _tp_a = gravity_tau_sine(0.3, 0.3, 45.0, 0.0)
    tr_b, _tp_b = gravity_tau_sine(0.3, 0.3, 45.0, 70.0)
    assert tr_a == pytest.approx(tr_b)


def test_gravity_sine_sign_flips_with_angle():
    """±90° 对称翻号。"""
    tr_p, _tp = gravity_tau_sine(0.3, 0.3, 90.0, 0.0)
    tr_n, _tn = gravity_tau_sine(0.3, 0.3, -90.0, 0.0)
    assert tr_p == pytest.approx(-0.3)
    assert tr_n == pytest.approx(+0.3)


def test_gravity_sine_half_at_30():
    """sin30° = 0.5 → τ_ff = −A/2。"""
    tr, tp = gravity_tau_sine(0.4, 0.4, 30.0, 30.0)
    assert tr == pytest.approx(-0.2, abs=1e-12)
    assert tp == pytest.approx(-0.4 * math.sin(math.radians(30.0))
                               * math.cos(math.radians(30.0)))


def test_gravity_sine_negative_amp_flips():
    """A 填负值 = 翻转方向。"""
    tr, tp = gravity_tau_sine(-0.3, -0.3, 30.0, 30.0)
    assert tr > 0.0 and tp > 0.0


def test_gravity_sine_bad_input_zero():
    tr, tp = gravity_tau_sine(float("nan"), 0.3, 90.0, 90.0)
    assert tr == pytest.approx(0.0)
    assert tp == pytest.approx(0.0)          # cos(90°)=0
