"""「控力矩」分配（2026-11-22）：`allocate_torque_priority` 的行为测试。

与 `tda_solve`（固定预紧 t，做不到就缩力矩 α）的区别：
  · 预紧 `preload` 变成**下限** `t_floor`
  · 实际用 `t = max(s_lo, t_floor)`，`α ≡ 1`（力矩全额实现）
  · 力矩不可行时返回 None（由调用方钳制/拒绝），不静默降额

数学依据：3 缆 2 轴 ⟹ 零空间 1 维，`f(s) = f_τ + s·n̂`，
`‖f(s)‖² = ‖f_τ‖² + s²`（f_τ ⊥ n̂，顶点在 s=0），
力封闭要求 s ≥ f_min·Σn̂ > 0 ⟹ 最省力解必在左端点 `s_lo`。
"""
import math

import pytest

from wrist_model import positive_null_direction, wrist_eval
from wrist_tda import (TDA_INFEASIBLE, TDA_OK, TDA_PRELOAD_INFEASIBLE,
                       TDA_PRELOAD_RAISED, allocate_torque_priority,
                       preload_window, tda_solve, torque_capacity)

FMIN, FMAX = 0.2, 25.0
_OUT = wrist_eval(0.0, 0.0)
_R = _OUT.r_m
_N = tuple(positive_null_direction(0.0, 0.0))


def _tau_of(f):
    return (sum(_R[0][i] * f[i] for i in range(3)),
            sum(_R[1][i] * f[i] for i in range(3)))


# ---------------- 核心性质 ----------------

def test_torque_is_exact():
    """α≡1：分配出的三缆张力必须精确产生目标力矩。"""
    for tau_p in (0.0, -0.1, -0.3, -0.8, -1.2):
        f, fl, a = allocate_torque_priority(_R, _N, 0.0, tau_p, 2.0, FMIN, FMAX)
        assert f is not None, tau_p
        assert a == pytest.approx(1.0)
        tr, tp = _tau_of(f)
        assert tr == pytest.approx(0.0, abs=1e-12)
        assert tp == pytest.approx(tau_p, abs=1e-12)


def test_bounds_respected():
    f, _fl, _a = allocate_torque_priority(_R, _N, 0.0, -0.8, 2.0, FMIN, FMAX)
    assert all(FMIN - 1e-12 <= v <= FMAX + 1e-12 for v in f)


def test_t_floor_is_honoured_when_sufficient():
    """预紧下限够大时，实际 t = t_floor（不被抬）。"""
    f, fl, _a = allocate_torque_priority(_R, _N, 0.0, -0.1, 3.0, FMIN, FMAX)
    t_used = sum(_N[i] * f[i] for i in range(3))
    assert t_used == pytest.approx(3.0)
    assert fl == TDA_OK            # 没被抬


def test_t_is_raised_to_s_lo_for_big_torque():
    """力矩大时预紧必须被抬到 s_lo，并打 TDA_PRELOAD_RAISED。"""
    f, fl, _a = allocate_torque_priority(_R, _N, 0.0, -0.8, 2.0, FMIN, FMAX)
    t_used = sum(_N[i] * f[i] for i in range(3))
    assert t_used > 2.0 + 1e-6
    assert fl & TDA_PRELOAD_RAISED
    # 抬到 s_lo 时必然有一根缆正好压在下界
    assert min(f) == pytest.approx(FMIN, abs=1e-9)


def test_min_norm_equals_left_endpoint():
    """沿可行区间**向前**扫描，‖f‖² 单调增大 ⟹ 左端点即最小范数解。"""
    tau_p = -0.6
    f_cl, _fl, _a = allocate_torque_priority(_R, _N, 0.0, tau_p, 0.0, FMIN, FMAX)
    s_cl = sum(_N[i] * f_cl[i] for i in range(3))
    n0 = sum(v * v for v in f_cl)
    for ds in (0.05, 0.2, 1.0, 3.0):
        f = [f_cl[i] + ds * _N[i] for i in range(3)]
        assert all(v <= FMAX + 1e-9 for v in f), (ds, f)
        assert sum(v * v for v in f) > n0, ds


# ---------------- 不可行 / 错误路径 ----------------

def test_infeasible_torque_returns_none():
    f, fl, a = allocate_torque_priority(_R, _N, 0.0, -5.0, 2.0, FMIN, FMAX)
    assert f is None
    assert fl & TDA_INFEASIBLE
    assert math.isnan(a)           # 断口语义


def test_preload_floor_too_big_is_distinguished():
    """用户预紧下限 > s_hi → 用专门的 flag（提示"预紧太大"而非"力矩不可行"）。"""
    f, fl, _a = allocate_torque_priority(_R, _N, 0.0, -1.2, 100.0, FMIN, FMAX)
    assert f is None
    assert fl & TDA_PRELOAD_INFEASIBLE


def test_no_null_returns_none():
    f, fl, a = allocate_torque_priority(_R, None, 0.0, -0.1, 2.0, FMIN, FMAX)
    assert f is None and math.isnan(a)


# ---------------- 能力查询 ----------------

def test_capacity_is_direction_asymmetric():
    """R 的力臂不对称 ⟹ 正反向能力不同（实测 pitch 正向约 0.50、负向约 1.44）。"""
    cap_pos = torque_capacity(_R, _N, 2.0, FMIN, FMAX, axis=1, sign=+1.0)
    cap_neg = torque_capacity(_R, _N, 2.0, FMIN, FMAX, axis=1, sign=-1.0)
    assert cap_pos > 0.0 and cap_neg > 0.0
    assert cap_neg > cap_pos * 1.5      # 负向明显更大


def test_capacity_is_actually_achievable():
    """能力边界内的力矩必须真的可分配（边界外不行）。"""
    cap = torque_capacity(_R, _N, 2.0, FMIN, FMAX, axis=1, sign=-1.0)
    f_in, _fl, _a = allocate_torque_priority(_R, _N, 0.0, -0.98 * cap, 2.0, FMIN, FMAX)
    assert f_in is not None
    f_out, fl_out, _a2 = allocate_torque_priority(
        _R, _N, 0.0, -1.02 * cap, 2.0, FMIN, FMAX)
    assert f_out is None and fl_out & TDA_INFEASIBLE


# ---------------- 与旧实现对比 ----------------

def test_old_solver_derates_but_new_one_does_not():
    """同一个"预紧偏小"的工况：旧实现打折，新实现精确。"""
    tau_p = -0.3
    f_old, fl_old, a_old = tda_solve(_R, _N, 0.0, tau_p, 1.0, FMIN, FMAX)
    assert a_old < 1.0 and fl_old != TDA_OK          # 旧：降额
    f_new, _fl, a_new = allocate_torque_priority(_R, _N, 0.0, tau_p, 1.0, FMIN, FMAX)
    assert a_new == pytest.approx(1.0)               # 新：不打折
    assert _tau_of(f_new)[1] == pytest.approx(tau_p, abs=1e-12)
