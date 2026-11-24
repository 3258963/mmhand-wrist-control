"""正弦跟随测试的**纯数学**部分 —— `sine_target_step`。

用途（2026-11-24 用户要求）：张力模式下把目标改成

    f_target_i = 基值_i + sign_i · A · sin(2π f t + φ)

用来测**张力内环的动态响应**（跟随误差、幅值衰减、相位滞后）。

为什么单独抽出来做测试：
    · `t` 必须从"勾上测试那一刻"起算，`φ=0` 时起点严格等于基值（**不许有阶跃**）——
      阶跃会把内环的饱和/非线性混进辨识结果；
    · 幅度过大必须**削顶**而不是撞界（过载闸门要留给真故障）；
    · 符号 `(1,1,1)` = 共模（测张力环本身），`(1,-1,-1)` = 差动（测 roll 差分）。
"""

import math

import pytest

from wrist_force_law import sine_target_step


BASE = (2.0, 2.0, 2.0)
COMMON = (1, 1, 1)
DIFF = (1, -1, -1)


def test_starts_at_base_no_step():
    """`t=0, φ=0` → 目标等于基值，没有阶跃。"""
    out = sine_target_step(BASE, 1.0, 0.5, 0.0, 0.0, COMMON, 0.0, 30.0)
    assert out == [2.0, 2.0, 2.0]


def test_quarter_period_peaks():
    """`f=0.5Hz`（T=2s）→ `t=0.5s` 是 1/4 周期，sin=1 → 基值+A。"""
    out = sine_target_step(BASE, 1.0, 0.5, 0.0, 0.5, COMMON, 0.0, 30.0)
    assert out == pytest.approx([3.0, 3.0, 3.0], abs=0.02)


def test_half_period_returns():
    """`t=1s` 是半周期 → 回到基值。"""
    out = sine_target_step(BASE, 1.0, 0.5, 0.0, 1.0, COMMON, 0.0, 30.0)
    assert out == pytest.approx([2.0, 2.0, 2.0], abs=0.02)


def test_three_quarter_period_goes_below():
    """`t=1.5s` 是 3/4 周期 → 基值−A。"""
    out = sine_target_step(BASE, 1.0, 0.5, 0.0, 1.5, COMMON, 0.0, 30.0)
    assert out == pytest.approx([1.0, 1.0, 1.0], abs=0.02)


def test_differential_signs_split_axes():
    """`(1,-1,-1)` → C1 升、C2/C3 降（产生 roll 力矩摆动）。"""
    out = sine_target_step(BASE, 1.0, 0.5, 0.0, 0.5, DIFF, 0.0, 30.0)
    assert out == pytest.approx([3.0, 1.0, 1.0], abs=0.02)


def test_phase_shift():
    """`φ=90°` 时 `t=0` 直接到峰值（等价于 cos 起点）。"""
    out = sine_target_step(BASE, 1.0, 0.5, math.pi / 2, 0.0, COMMON, 0.0, 30.0)
    assert out == pytest.approx([3.0, 3.0, 3.0], abs=0.02)


def test_clamped_not_overflow():
    """幅度远超界限 → 削顶在 `[lo, hi]`，不会越界（过载闸门留给真故障）。"""
    out = sine_target_step(BASE, 50.0, 0.5, 0.0, 0.5, COMMON, 0.3, 25.0)
    assert all(0.3 <= v <= 25.0 for v in out)
    assert out == pytest.approx([25.0, 25.0, 25.0])


def test_clamped_low():
    """负向摆到下限被夹住。"""
    out = sine_target_step(BASE, 5.0, 0.5, 0.0, 1.5, COMMON, 0.3, 30.0)
    assert all(v >= 0.3 for v in out)


def test_zero_amplitude_is_constant():
    """`A=0` → 恒等于基值（用于"开测试但不动"验证）。"""
    for t in (0.0, 0.3, 1.1, 2.7):
        assert sine_target_step(BASE, 0.0, 1.3, 0.7, t, COMMON, 0.0, 30.0) \
            == [2.0, 2.0, 2.0]


def test_negative_amplitude_uses_magnitude():
    """负幅度按绝对值处理（符号交给 `signs`）。"""
    a = sine_target_step(BASE, -1.0, 0.5, 0.0, 0.5, COMMON, 0.0, 30.0)
    b = sine_target_step(BASE, 1.0, 0.5, 0.0, 0.5, COMMON, 0.0, 30.0)
    assert a == b


def test_frequency_scales_rate():
    """频率加倍 → 同时刻的相位加倍：`t=0.25s` 在 1Hz 下是 1/4 周期（峰值）。"""
    out = sine_target_step(BASE, 1.0, 1.0, 0.0, 0.25, COMMON, 0.0, 30.0)
    assert out == pytest.approx([3.0, 3.0, 3.0], abs=0.02)


def test_bad_inputs_return_empty():
    """非法输入 → 返回空表（调用方据此报错停环，而不是乱下目标）。"""
    assert sine_target_step(BASE, 1.0, 0.5, 0.0, 0.0, (1, 1), 0.0, 30.0) == []
    assert sine_target_step(BASE, 1.0, 0.5, 0.0, 0.0, COMMON, 0.0, 30.0, ) != []
    assert sine_target_step((), 1.0, 0.5, 0.0, 0.0, (), 0.0, 30.0) == []
    assert sine_target_step(BASE, float("nan"), 0.5, 0.0, 0.0, COMMON, 0.0, 30.0) == []
    assert sine_target_step((float("nan"), 2.0, 2.0), 1.0, 0.5, 0.0, 0.0,
                            COMMON, 0.0, 30.0) == []


def test_lo_greater_than_hi_degenerates():
    """`lo > hi`（阈值非法）不抛异常，退化为 `lo`。"""
    out = sine_target_step(BASE, 1.0, 0.5, 0.0, 0.5, COMMON, 10.0, 5.0)
    assert out == pytest.approx([10.0, 10.0, 10.0])
