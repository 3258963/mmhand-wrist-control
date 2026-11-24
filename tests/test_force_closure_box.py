"""力封闭可行域钳制（2026-11-20）的测试。

背景：`positive_null_direction` 只在 n̂ 全正（力封闭成立）的姿态返回方向。
区域外它返回 None → 三个力控模式直接拒启，界面只报"无可行预紧区间"。
所以内部运算前先把角度钳到最近的可行姿态（`clamp_force_closure`），并告警。

本文件做两件事：
  ① **验证边界不是随手画的** —— 四角必须可行、邻域外侧必须失败；
  ② 验证钳制本身（区内恒等、区外拉回、NaN 回中心）。
"""
import math

import pytest

from wrist_model import (
    FORCE_CLOSURE_PITCH_DEG,
    FORCE_CLOSURE_ROLL_DEG,
    clamp_force_closure,
    positive_null_direction,
)


def _nd(roll_deg, pitch_deg):
    return positive_null_direction(math.radians(roll_deg), math.radians(pitch_deg))


# ---------------- ① 边界校验 ----------------

def test_four_corners_are_feasible():
    """可行域四角必须存在全正 n̂（钳到边界时模型仍可用）。"""
    for r in FORCE_CLOSURE_ROLL_DEG:
        for p in FORCE_CLOSURE_PITCH_DEG:
            nd = _nd(r, p)
            assert nd is not None, f"角点不可行: roll={r}, pitch={p}"
            assert all(x > 0.0 for x in nd)


def test_boundary_is_tight_just_outside_fails():
    """边界外一点必须失败 —— 否则说明盒画大了（那才是危险方向）。"""
    r_lo, r_hi = FORCE_CLOSURE_ROLL_DEG
    p_lo, p_hi = FORCE_CLOSURE_PITCH_DEG
    outside = [
        (r_lo - 5.0, 0.0),      # roll 更负
        (r_hi + 5.0, 0.0),      # roll 更正
        (0.0, p_hi + 5.0),      # pitch 更高
        (0.0, p_lo - 5.0),      # pitch 更低
    ]
    for r, p in outside:
        assert _nd(r, p) is None, f"边界外仍可行，盒画小了: roll={r}, pitch={p}"


# ---------------- ② 钳制行为 ----------------

def test_inside_is_identity():
    for r_deg, p_deg in ((0.0, 0.0), (0.0, -10.0), (-10.0, 20.0), (5.0, -25.0)):
        r, p, clamped = clamp_force_closure(math.radians(r_deg), math.radians(p_deg))
        assert not clamped
        assert r == pytest.approx(math.radians(r_deg))
        assert p == pytest.approx(math.radians(p_deg))


@pytest.mark.parametrize("r_deg,p_deg", [
    (-25.0, 0.0), (20.0, 0.0), (0.0, 44.0), (0.0, -30.0), (-25.0, 44.0),
])
def test_outside_is_clamped_and_feasible(r_deg, p_deg):
    r, p, clamped = clamp_force_closure(math.radians(r_deg), math.radians(p_deg))
    assert clamped
    # 落在边界上（而不是继续往外）
    assert FORCE_CLOSURE_ROLL_DEG[0] - 1e-9 <= math.degrees(r) <= FORCE_CLOSURE_ROLL_DEG[1] + 1e-9
    assert FORCE_CLOSURE_PITCH_DEG[0] - 1e-9 <= math.degrees(p) <= FORCE_CLOSURE_PITCH_DEG[1] + 1e-9
    # 钳后必须真的可用
    nd = positive_null_direction(r, p)
    assert nd is not None and all(x > 0.0 for x in nd)


def test_nan_and_inf_fall_back_to_center():
    for bad in (float("nan"), float("inf"), -float("inf")):
        r, p, clamped = clamp_force_closure(bad, 0.1)
        assert clamped
        assert r == 0.0 and p == 0.0


def test_clamp_is_idempotent():
    r, p, _ = clamp_force_closure(math.radians(-25.0), math.radians(44.0))
    r2, p2, clamped2 = clamp_force_closure(r, p)
    assert not clamped2
    assert (r2, p2) == (r, p)
