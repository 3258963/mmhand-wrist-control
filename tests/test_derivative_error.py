"""误差微分 D（标准 PID 的 D 项）—— `tension_d_err_counts`。

2026-11-25 用户定案：**D 应该是对"张力误差"的微分**，而不是对舵机速度做阻尼。
两者都保留：

| 框 | 含义 | 符号 |
|---|---|---|
| `Kd_f` | **误差微分 D**：`Kd·d(e)/dt`，`e = 目标 − 实测` | **加**（标准 PID）|
| `Kd_v_f` | 速度阻尼：`Kd_v·舵机速度` | **减** |
"""

import math

import pytest

from wrist_force_law import (D_TERM_MAX_FRAC, IncrPiState, WristTensionParams,
                             tension_d_err_counts, wrist_tension_step)


# ---------------- 纯函数 ----------------

def test_disabled_when_kd_zero():
    d, f = tension_d_err_counts(0.0, 1.0, 0.0, 0.01, 25.0)
    assert d == 0.0 and f == 0.0


def test_basic_derivative_times_gain():
    """e 从 0 涨到 1 N，dt=10 ms → ė=100 N/s；kd=0.05 → 5·α（首拍滤波）。"""
    d, f = tension_d_err_counts(0.05, 1.0, 0.0, 0.01, 25.0, d_filt_prev=0.0,
                               alpha=1.0)
    assert f == pytest.approx(100.0)
    assert d == pytest.approx(5.0)


def test_filter_smooths_first_sample():
    """α=0.3（默认）→ 首拍只吃到 30% 的原始微分，抑制噪声。"""
    d, f = tension_d_err_counts(0.05, 1.0, 0.0, 0.01, 25.0, d_filt_prev=0.0)
    assert f == pytest.approx(30.0)
    assert d == pytest.approx(1.5)


def test_sign_brakes_when_approaching():
    """误差在减小（e 从 1 掉到 0.5）→ ė<0 → D<0 → 输出变小（刹车）。"""
    d, _f = tension_d_err_counts(0.05, 0.5, 1.0, 0.01, 25.0, alpha=1.0)
    assert d < 0.0


def test_clamped_by_frac_of_max_step():
    lim = D_TERM_MAX_FRAC * 25.0
    d, _f = tension_d_err_counts(100.0, 5.0, 0.0, 0.01, 25.0, alpha=1.0)
    assert d == pytest.approx(lim)


def test_negative_clamped_too():
    lim = D_TERM_MAX_FRAC * 25.0
    d, _f = tension_d_err_counts(100.0, 0.0, 5.0, 0.01, 25.0, alpha=1.0)
    assert d == pytest.approx(-lim)


def test_invalid_inputs_return_zero():
    for args in ((0.05, float("nan"), 0.0, 0.01, 25.0),
                 (0.05, 1.0, float("inf"), 0.01, 25.0),
                 (0.05, 1.0, 0.0, 0.0, 25.0),          # dt=0
                 (0.05, 1.0, 0.0, 0.01, 0.0)):         # max_step=0
        d, f = tension_d_err_counts(*args)
        assert d == 0.0 and f == 0.0


def test_filter_state_carries_over():
    """连续两拍：第二拍用第一拍的滤波值 → 不该从 0 重启。"""
    _d1, f1 = tension_d_err_counts(0.05, 1.0, 0.0, 0.01, 25.0, 0.0, alpha=0.3)
    d2, f2 = tension_d_err_counts(0.05, 1.5, 1.0, 0.01, 25.0, f1, alpha=0.3)
    # 第二拍 raw 仍是 50 N/s，但滤波从 f1=30 出发
    assert f2 == pytest.approx(0.3 * 50 + 0.7 * f1)


# ---------------- 与 PI 组合（行为） ----------------

def _params(**kw):
    base = dict(f_target=(2.0, 2.0, 2.0), kp=15.0, ki=0.0, trim_sign=(1, 1, 1),
                max_trim=3000.0, f_max=30.0, deadband=0.0, max_step=200.0,
                i_term_lim=10.0)
    base.update(kw)
    return WristTensionParams(**base)


def test_kd_e_raises_step_when_error_grows():
    """误差在变大（远离目标）→ D 为正 → 本拍步长比纯 P 更大（加速追赶）。"""
    p0 = _params(kd=0.0)
    p1 = _params(kd=0.05)
    s0, s1 = IncrPiState(), IncrPiState()
    a = wrist_tension_step(p0, s0, [0.0, 0.0, 0.0], 0.0, 0.01)[0][0]
    # 先让状态里 e_prev=0，此时 error=2 → 大误差在"出现"，D 为正
    b = wrist_tension_step(p1, s1, [0.0, 0.0, 0.0], 0.0, 0.01)[0][0]
    assert b > a


def test_kd_e_brakes_when_error_shrinks():
    """误差在减小 → D 为负 → 同样误差下步长比纯 P 小（刹车）。"""
    p0 = _params(kd=0.0)
    p1 = _params(kd=0.05)
    s0, s1 = IncrPiState(), IncrPiState()
    # 先跑一拍让 e_prev=2，再给一个更小的误差 0.5（e 在减小）
    wrist_tension_step(p0, s0, [0.0, 0.0, 0.0], 0.0, 0.01)
    wrist_tension_step(p1, s1, [0.0, 0.0, 0.0], 0.0, 0.01)
    a = wrist_tension_step(p0, s0, [1.5, 1.5, 1.5], 0.0, 0.01)[0][0]
    b = wrist_tension_step(p1, s1, [1.5, 1.5, 1.5], 0.0, 0.01)[0][0]
    assert b < a


def test_kd_e_zero_matches_pure_pi():
    """`kd=0` → 与纯 PI 逐位一致（不改变旧行为）。"""
    f = [0.5, 0.6, 0.7]
    a = wrist_tension_step(_params(), IncrPiState(), f, 0.0, 0.01)[0]
    b = wrist_tension_step(_params(kd=0.0), IncrPiState(), f, 0.0, 0.01)[0]
    assert a == b


def test_kd_e_per_cable():
    """逐缆 `kd_e3`：只给 C2 加 D → 只有 C2 的步长变化。"""
    p = _params(kd=0.0, kd3=[0.0, 0.1, 0.0])
    st = IncrPiState()
    trim = wrist_tension_step(p, st, [0.0, 0.0, 0.0], 0.0, 0.01)[0]
    assert trim[0] == trim[2] != trim[1]


def test_state_reset_clears_derivative():
    """起环时 `reset()` 清掉 e_prev / d_filt，避免上一轮残留造成首拍冲击。"""
    st = IncrPiState()
    wrist_tension_step(_params(kd=0.05), st, [0.0, 0.0, 0.0], 0.0, 0.01)
    assert any(v != 0.0 for v in st.e_prev)
    st.reset()
    assert st.e_prev == [0.0, 0.0, 0.0]
    assert st.d_filt == [0.0, 0.0, 0.0]
