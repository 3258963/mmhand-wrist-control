"""自动调参序列的单元测试（`wrist_autotune`）。"""

import math

import pytest

import wrist_autotune as at
from wrist_autotune import (SINE_AMP_N, SINE_BASE_N, STEP_HIGH_N, STEP_LOW_N,
                            TARGET_MIN_N, command_at, stages, total_seconds)


PRE = 1     # 序列第 0 档是「预紧」，各项测试的偏移量


def test_stage_count_and_order():
    s = stages()
    assert s[0][0] == "预紧" and s[0][1] == at.KIND_PRE
    assert [x[0] for x in s][PRE:PRE + 2] == ["阶跃上", "阶跃下"]
    assert len(s) == 1 + 2 + len(at.SINE_FREQS_HZ)
    # 正弦频率递增
    hz = [x[3] for x in s[PRE + 2:]]
    assert hz == sorted(hz)


def test_total_seconds_matches_sum():
    assert total_seconds() == pytest.approx(sum(x[2] for x in stages()))


def test_step_stage_is_constant_high():
    idx, name, kind, tgts, local = command_at(at.PRELOAD_S + 1e-9)
    assert (idx, kind) == (PRE, at.KIND_STEP)
    assert tgts == [STEP_HIGH_N] * 3
    # 整个阶跃上档都保持同一个值（这就是"阶跃"）
    _, _, _, t2, _ = command_at(at.PRELOAD_S + at.STEP_HOLD_S - 1e-6)
    assert t2 == [STEP_HIGH_N] * 3


def test_step_down_after_hold():
    idx, _n, kind, tgts, _l = command_at(at.PRELOAD_S + at.STEP_HOLD_S + 1e-6)
    assert idx == PRE + 1 and kind == at.KIND_STEP
    assert tgts == [STEP_LOW_N] * 3


def test_sine_starts_at_base_no_jump():
    """正弦档起点必须等于基值（相位 0）—— 不允许阶跃。"""
    t0 = at.PRELOAD_S + 2 * at.STEP_HOLD_S
    idx, name, kind, tgts, local = command_at(t0 + 1e-9)
    assert kind == at.KIND_SINE and local < 1e-6
    assert tgts[0] == pytest.approx(SINE_BASE_N, abs=1e-6)


def test_sine_amplitude_and_min_target():
    """幅度 = 4、范围 1~9，且**永不低于 1 N**（用户硬约束）。"""
    t0 = at.PRELOAD_S + 2 * at.STEP_HOLD_S
    hz = at.SINE_FREQS_HZ[0]
    period = 1.0 / hz
    vals = []
    for k in range(400):
        _i, _n, _k, tgts, _l = command_at(t0 + period * k / 400.0)
        vals.append(tgts[0])
    assert min(vals) >= TARGET_MIN_N - 1e-9
    assert max(vals) == pytest.approx(SINE_BASE_N + SINE_AMP_N, abs=0.02)
    assert min(vals) == pytest.approx(SINE_BASE_N - SINE_AMP_N, abs=0.02)


def test_every_stage_respects_bounds():
    """所有档位的目标都在 [max(1, f_min), f_max] 内（界更严时以界为准）。"""
    T = total_seconds()
    for k in range(2000):
        _i, _n, _k, tgts, _l = command_at(T * k / 2000.0, f_min=0.3, f_max=6.0)
        for v in tgts:
            assert 1.0 - 1e-9 <= v <= 6.0 + 1e-9


def test_min_clamped_by_fmin_when_higher():
    """f_min 高于 1 时以 f_min 为准（不能违反设备下限）。"""
    _i, _n, _k, tgts, _l = command_at(0.0, f_min=2.0, f_max=30.0)
    assert tgts[0] >= 2.0


def test_returns_none_after_finish():
    idx, name, kind, tgts, local = command_at(total_seconds() + 1e-6)
    assert idx is None and tgts is None and kind == "" and local == 0.0


def test_negative_time_treated_as_start():
    a = command_at(-5.0)
    b = command_at(0.0)
    assert a == b


def test_nan_time_treated_as_start():
    a = command_at(float("nan"))
    b = command_at(0.0)
    assert a == b


def test_stage_boundaries_are_contiguous():
    """每一档的末拍与下一档的首拍之间不能有"空档"。"""
    T = total_seconds()
    prev = None
    t = 0.0
    for idx, (name, kind, dur, payload) in enumerate(stages()):
        _i, _n, _k, tgts, _l = command_at(t + 1e-9)
        assert _i == idx, (name, _i)
        t += dur
    assert t == pytest.approx(T)


def test_sine_seconds_at_least_three_cycles():
    for hz in at.SINE_FREQS_HZ:
        assert at._sine_seconds(hz) >= 3.0 / hz - 1e-9


def test_summary_mentions_all_stages():
    txt = at.summary_text()
    for name, _k, _d, _p in stages():
        assert name in txt


def test_each_sine_stage_actually_covers_its_frequency():
    """抽查 0.3 Hz 档：0.3 s 处应走完约 1/10 周期。"""
    t0 = (at.PRELOAD_S + 2 * at.STEP_HOLD_S
          + at._sine_seconds(0.1) + at._sine_seconds(0.2))
    _i, name, kind, tgts, local = command_at(t0 + 0.3)
    assert kind == at.KIND_SINE and "0.3" in name
    expect = SINE_BASE_N + SINE_AMP_N * math.sin(2 * math.pi * 0.3 * local)
    assert tgts[0] == pytest.approx(expect, abs=0.05)
