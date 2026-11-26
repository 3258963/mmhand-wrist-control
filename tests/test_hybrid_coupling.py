"""混合模式 C1↔C2/C3 耦合比（`coupling_ratios`）的测试。

结论（从 P 矩阵推出来的，见 `wrist_hybrid_control.coupling_ratios`）：

    ∂f/∂t = n̂   ⟹   s = n̂/n̂[0]   ⟹   s2 = n̂[1]/n̂[0], s3 = n̂[2]/n̂[0]

即「C1 每 +1 N，C2/C3 稳态要跟着变多少」**只由零空间方向决定**，与负载无关。
"""
import math

import pytest

from wrist_hybrid_control import c1_share_of_preload, coupling_ratios


def test_matches_numeric_example():
    """位姿 (roll +5, pitch -10) 实测 n̂=(0.293,0.718,0.631) → s2≈2.45, s3≈2.15。"""
    n1, s2, s3 = coupling_ratios((0.293, 0.718, 0.631))
    assert n1 == pytest.approx(0.293)
    assert s2 == pytest.approx(0.718 / 0.293, rel=1e-6)
    assert s3 == pytest.approx(0.631 / 0.293, rel=1e-6)
    assert s2 == pytest.approx(2.45, abs=0.01)


def test_ideal_case_c1_is_pure_preload():
    """n̂=(1,0,0) → C1 承担全部预紧，改它不打扰 C2/C3（s2=s3=0）。"""
    _n1, s2, s3 = coupling_ratios((1.0, 0.0, 0.0))
    assert s2 == pytest.approx(0.0)
    assert s3 == pytest.approx(0.0)


def test_bad_case_c1_mostly_torque():
    """n̂[0] 很小时耦合比会很大 —— 这就是"加 1 N 逼出十几 N"的机理。"""
    _n1, s2, s3 = coupling_ratios((0.087, 0.25, 0.964))
    assert s2 > 2.5 and s3 > 10.0


def test_c1_absent_from_preload_returns_none():
    assert coupling_ratios((0.0, 0.6, 0.8)) is None


def test_rejects_nonfinite_and_short():
    assert coupling_ratios((float("nan"), 1.0, 1.0)) is None
    assert coupling_ratios((0.3,)) is None
    assert coupling_ratios(None) is None


def test_ratio_is_scale_invariant():
    """n̂ 未归一化也应给出同一组比值。"""
    a = coupling_ratios((0.3, 0.7, 0.6))
    b = coupling_ratios((3.0, 7.0, 6.0))
    assert a[1] == pytest.approx(b[1])
    assert a[2] == pytest.approx(b[2])


def test_share_of_preload_normalizes():
    assert c1_share_of_preload((1.0, 0.0, 0.0)) == pytest.approx(1.0)
    assert c1_share_of_preload((0.0, 1.0, 0.0)) == pytest.approx(0.0)
    v = (0.3, 0.4, 0.0)                       # 模长 0.5 → 份额 0.6
    assert c1_share_of_preload(v) == pytest.approx(0.6)
    assert c1_share_of_preload(None) == 0.0
