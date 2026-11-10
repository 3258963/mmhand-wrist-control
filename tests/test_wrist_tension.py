"""wrist_tension 张力守卫与 τ=Rf 观测测试。

golden 值由六段常数独立预计算：零位 R(0)·f，f=(1,2,3) N
→ τ_roll=+0.007757 N·m，τ_pitch=−0.001524 N·m，f·n̂=3.7314 N。
"""
import math

import pytest

from wrist_model import RANGE_DEG, ROLL
from wrist_tension import (
    TENSION_OK,
    TENSION_OVERLOAD,
    TENSION_SLACK,
    TENSION_STALE,
    TensionConfig,
    tension_evaluate,
)


def make_cfg():
    # f_min/f_max 无默认值：必须显式给定（数值为测试自定，仅测逻辑）
    return TensionConfig(f_min_n=0.5, f_max_n=50.0)


def test_tau_from_r():
    ev = tension_evaluate([1.0, 2.0, 3.0], 10.0, make_cfg(), 0.0, 0.0)
    assert ev.flags == TENSION_OK
    assert ev.tau_roll_nm == pytest.approx(0.007757, abs=1e-6)
    assert ev.tau_pitch_nm == pytest.approx(-0.001524, abs=1e-6)


def test_preload():
    ev = tension_evaluate([1.0, 2.0, 3.0], 10.0, make_cfg(), 0.0, 0.0)
    assert ev.preload_n == pytest.approx(3.7314, abs=1e-3)
    assert not any(ev.slack) and not any(ev.overload)


def test_slack_overload():
    ev = tension_evaluate([0.1, 2.0, 60.0], 10.0, make_cfg(), 0.0, 0.0)
    assert ev.slack == [True, False, False]
    assert ev.overload == [False, False, True]
    assert ev.flags & TENSION_SLACK
    assert ev.flags & TENSION_OVERLOAD


def test_stale():
    ev = tension_evaluate([1.0, 2.0, 3.0], 400.0, make_cfg(), 0.0, 0.0)
    assert ev.flags == TENSION_STALE
    assert math.isnan(ev.tau_roll_nm) and math.isnan(ev.tau_pitch_nm)
    assert math.isnan(ev.preload_n)
    assert not any(ev.slack) and not any(ev.overload)


def test_invalid_samples():
    for bad in ([1.0, math.nan, 3.0], [1.0, -2.0, 3.0], [1.0, math.inf, 3.0]):
        ev = tension_evaluate(bad, 10.0, make_cfg(), 0.0, 0.0)
        assert ev.flags == TENSION_STALE
        assert math.isnan(ev.tau_roll_nm)
        assert not any(ev.slack) and not any(ev.overload)


def test_no_null_direction():
    """(−25°,−25°) 属于无全正预紧方向的姿态：preload=NaN 但 τ 正常。"""
    lo = math.radians(RANGE_DEG[ROLL][0])
    ev = tension_evaluate([1.0, 2.0, 3.0], 10.0, make_cfg(), lo, lo)
    assert math.isnan(ev.preload_n)
    assert math.isfinite(ev.tau_roll_nm)
    assert math.isfinite(ev.tau_pitch_nm)


def test_config_validation():
    with pytest.raises(ValueError):
        TensionConfig()                       # 缺 f_min/f_max：无默认值
    with pytest.raises(ValueError):
        TensionConfig(f_min_n=1.0)            # 缺 f_max
    with pytest.raises(ValueError):
        TensionConfig(f_min_n=50.0, f_max_n=1.0)   # min>max
    with pytest.raises(ValueError):
        TensionConfig(f_min_n=-1.0, f_max_n=10.0)  # 负下限
    cfg = TensionConfig(f_min_n=0.5, f_max_n=50.0)
    assert cfg.max_age_ms == pytest.approx(300.0)
