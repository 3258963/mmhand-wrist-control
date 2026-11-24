"""`allocation_step` / `capacity_closed_form`（2026-11-23 闭式 α 内生）的测试。

背景：3 缆 2 轴的能力集是**沿方向的凸集**，不是"每轴独立矩形"。
旧实现按轴各自二分再各砍各的，双轴组合会高估能力 → 砍完仍不可行 → 误判停环。
新实现沿目标方向闭式求 α，与论文算法 2 逐位等价。

验收清单（对应 docs/力矩控制完整流程_最终版_20261122.md §9）：
  1. R·f_d == α·τ*
  2. f_min ≤ f_d,i ≤ f_max
  3. τ=(0,−0.5) → α=1.0000, f_d=[8.718, 0.200, 0.384]
  4. τ=(0,−1.5) → α=0.9622, f_d=[25.000, 0.200, 0.627]
  5. τ=(0.2,−2.0) → α=0.6787（旧实现会停环）
  6. 与论文算法 2 对比：α、t 差 < 1e-6
  7. t_floor=20 → α 明显下降
  8. t_floor=0 → 与"无下限"一致
  9. alpha_cap=0.9 → 最多 90%
 10. m_max=0（f_min/f_max 自相矛盾）→ None + 预紧不可行
"""
import math

import pytest

from wrist_model import positive_null_direction, wrist_eval
from wrist_tda import (TDA_NO_NULL, TDA_PRELOAD_INFEASIBLE,
                       TDA_PRELOAD_RAISED, allocation_step,
                       allocate_torque_priority, capacity_closed_form,
                       torque_capacity)

FMIN, FMAX = 0.2, 25.0
_OUT = wrist_eval(0.0, 0.0)
_R = _OUT.r_m
_N = tuple(positive_null_direction(0.0, 0.0))


def _tau_of(f):
    return (sum(_R[0][i] * f[i] for i in range(3)),
            sum(_R[1][i] * f[i] for i in range(3)))


def _paper(tau_r, tau_p, fmin, fmax, t_floor=0.0, rounds=12):
    """论文算法 2（迭代解 2×2）作为参照实现。"""
    import numpy as np
    P = np.array([_R[0], _R[1], _N])
    Pi = np.linalg.inv(P)
    v = Pi @ np.array([tau_r, tau_p, 0.0])
    w = np.array(_N)
    a = 1.0
    t = max(max((fmin - v[i]) / w[i] for i in range(3)), t_floor)
    f = a * v + t * w
    it = 0
    while (np.any(f > fmax + 1e-9) or np.any(f < fmin - 1e-9)) and it < rounds:
        it += 1
        h, l = int(np.argmax(f)), int(np.argmin(f))
        A = np.array([[v[h], w[h]], [v[l], w[l]]])
        try:
            a, t = np.linalg.solve(A, np.array([fmax, fmin]))
        except np.linalg.LinAlgError:
            return None
        f = a * v + t * w
    return a, t, f


# ---------------- 恒等式与边界 ----------------

def test_identity_and_bounds():
    """R·f_d == α·τ*，且三缆全在界内（覆盖能力内/外/双轴）。"""
    for tr, tp in ((0.0, -0.5), (0.0, -1.5), (0.2, -2.0), (0.3, 0.2), (-0.3, -0.8)):
        f, _fl, a, info = allocation_step(_R, _N, tr, tp, 1.0, FMIN, FMAX)
        assert f is not None, (tr, tp)
        rt = _tau_of(f)
        assert rt[0] == pytest.approx(a * tr, abs=1e-9)
        assert rt[1] == pytest.approx(a * tp, abs=1e-9)
        assert all(FMIN - 1e-9 <= v <= FMAX + 1e-9 for v in f), f
        assert info["t"] == pytest.approx(sum(_N[i] * f[i] for i in range(3)))


def test_full_torque_when_within_capacity():
    """能力内：α=1 且结果与旧接口逐位一致。"""
    f_new, _fl, a, _info = allocation_step(_R, _N, 0.0, -0.5, 1.0, FMIN, FMAX)
    f_old, _fl2, a_old = allocate_torque_priority(_R, _N, 0.0, -0.5, 1.0, FMIN, FMAX)
    assert a == 1.0 and a_old == 1.0
    assert f_new == pytest.approx(f_old, abs=1e-12)
    assert f_new == pytest.approx([8.718, 0.200, 0.384], abs=1e-3)


def test_alpha_scaling_single_axis():
    f, fl, a, info = allocation_step(_R, _N, 0.0, -1.5, 1.0, FMIN, FMAX)
    assert a == pytest.approx(0.9622, abs=1e-4)
    assert f == pytest.approx([25.000, 0.200, 0.627], abs=1e-3)
    assert info["m_max"] == pytest.approx(1.4434, abs=1e-4)
    assert fl & TDA_PRELOAD_RAISED


def test_dual_axis_does_not_stop():
    """旧实现会在这里停环；新实现给出 α<1 的可行解。"""
    f, _fl, a, info = allocation_step(_R, _N, 0.2, -2.0, 1.0, FMIN, FMAX)
    assert f is not None
    assert a == pytest.approx(0.6787, abs=1e-4)
    assert info["m_max"] == pytest.approx(1.3643, abs=1e-4)
    # 旧接口在同样工况下应该是 None（对照，证明差别真实存在）
    f_old, _fl2, _a2 = allocate_torque_priority(_R, _N, 0.2, -2.0, 1.0, FMIN, FMAX)
    assert f_old is None


def test_matches_paper_algorithm2():
    """与论文算法 2（迭代 2×2）逐位对比。"""
    cases = ((0.0, -0.5), (0.0, -1.5), (0.0, -3.0), (0.1, -1.0),
             (0.2, -0.6), (0.3, 0.2), (0.2, -2.0), (-0.3, -0.8), (0.15, 0.3))
    for tr, tp in cases:
        f, _fl, a, info = allocation_step(_R, _N, tr, tp, 0.0, FMIN, FMAX)
        ref = _paper(tr, tp, FMIN, FMAX)
        assert ref is not None, (tr, tp)
        a_ref, t_ref, _f_ref = ref
        assert a == pytest.approx(a_ref, abs=1e-6), (tr, tp)
        assert info["t"] == pytest.approx(t_ref, abs=1e-6), (tr, tp)


# ---------------- 预紧下限 ----------------

def test_floor_zero_equals_no_floor():
    f0, _f, a0, i0 = allocation_step(_R, _N, 0.0, -1.5, 0.0, FMIN, FMAX)
    fn, _f2, an, i2 = allocation_step(_R, _N, 0.0, -1.5, 0.0, FMIN, FMAX)
    assert a0 == an and i0["t"] == i2["t"]


def test_big_floor_reduces_capacity():
    _f, _fl, _a, i_low = allocation_step(_R, _N, 0.0, -1.5, 1.0, FMIN, FMAX)
    _f2, _fl2, _a2, i_hi = allocation_step(_R, _N, 0.0, -1.5, 20.0, FMIN, FMAX)
    assert i_hi["m_max"] < i_low["m_max"] - 0.05
    # 本机实测：t_floor=20 时 270° 方向能力 1.4434 → 1.2319
    assert i_hi["m_max"] == pytest.approx(1.2319, abs=2e-3)


def test_floor_above_upper_limit_rejected():
    """预紧下限大于任何可行 t → 明确报"预紧不可行"，而不是含糊的"力矩不可行"。"""
    f, fl, a, _info = allocation_step(_R, _N, 0.0, -1.2, 100.0, FMIN, FMAX)
    assert f is None
    assert fl & TDA_PRELOAD_INFEASIBLE
    assert math.isnan(a)


def test_contradictory_bounds_rejected():
    """f_min=24 / f_max=25 且预紧下限 24.5 → 零力矩都不可行。"""
    f, fl, a, _info = allocation_step(_R, _N, 0.0, -0.3, 24.5, 24.0, 25.0)
    assert f is None
    assert fl & TDA_PRELOAD_INFEASIBLE


# ---------------- α 上限（安全系数） ----------------

def test_alpha_cap_limits_torque():
    """αcap=0.9：能力内也最多给 90%。"""
    f, _fl, a, _info = allocation_step(_R, _N, 0.0, -1.0, 1.0, FMIN, FMAX,
                                       alpha_cap=0.9)
    assert a == pytest.approx(0.9)
    rt = _tau_of(f)
    assert rt[1] == pytest.approx(-0.9, abs=1e-9)


def test_alpha_cap_not_binding_when_worse():
    """能力远小于请求时，αcap 不起作用（真实 α 更小）。"""
    _f, _fl, a, _info = allocation_step(_R, _N, 0.0, -10.0, 1.0, FMIN, FMAX,
                                        alpha_cap=0.9)
    assert a == pytest.approx(0.1443, abs=1e-3)
    assert a < 0.9


# ---------------- 闭式能力 vs 二分 ----------------

def test_capacity_matches_bisection():
    """闭式与旧二分（torque_capacity）在四轴向上一致。"""
    pairs = ((0, 1.0), (0, -1.0), (1, 1.0), (1, -1.0))
    for axis, sign in pairs:
        tr, tp = (sign, 0.0) if axis == 0 else (0.0, sign)
        m = capacity_closed_form(_R, _N, tr, tp, 1.0, FMIN, FMAX)
        cap = torque_capacity(_R, _N, 1.0, FMIN, FMAX, axis=axis, sign=sign)
        assert m == pytest.approx(cap, abs=1e-6), (axis, sign)


def test_capacity_direction_dependent():
    """同一台机器、同一位姿：能力随方向差 3 倍以上（0.43 vs 1.44）。"""
    caps = []
    for th in (0.0, 90.0, 180.0, 270.0):
        c, s = math.cos(math.radians(th)), math.sin(math.radians(th))
        caps.append(capacity_closed_form(_R, _N, c, s, 1.0, FMIN, FMAX))
    assert max(caps) / min(caps) > 2.5
    assert caps[3] == pytest.approx(1.4434, abs=1e-4)   # 270° = 纯 −pitch


def test_capacity_never_exceeds_bounds():
    """能力上限处，分配结果刚好贴边但不越界。"""
    c, s = math.cos(math.radians(225)), math.sin(math.radians(225))
    m = capacity_closed_form(_R, _N, c, s, 1.0, FMIN, FMAX)
    f, _fl, a, _info = allocation_step(_R, _N, c * m, s * m, 1.0, FMIN, FMAX)
    assert f is not None
    assert all(FMIN - 1e-6 <= v <= FMAX + 1e-6 for v in f), f
    assert a == pytest.approx(1.0, abs=1e-9)


def test_no_null_returns_none():
    assert capacity_closed_form(_R, None, 0.0, -1.0, 1.0, FMIN, FMAX) is None
    f, fl, a, _info = allocation_step(_R, None, 0.0, -1.0, 1.0, FMIN, FMAX)
    assert f is None and fl & TDA_NO_NULL and math.isnan(a)


def test_zero_torque_only_preload():
    """零力矩：只需预紧，α=1，f = t·n̂。"""
    f, _fl, a, info = allocation_step(_R, _N, 0.0, 0.0, 1.0, FMIN, FMAX)
    assert a == 1.0 and info["k"] == 0.0
    assert all(v == pytest.approx(info["t"] * _N[i]) for i, v in enumerate(f))
    assert info["t"] >= 1.0
