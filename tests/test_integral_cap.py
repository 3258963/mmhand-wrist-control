"""积分累积上限（2026-11-20 用户定案）的行为测试。

设计变更：
  · **取消条件积分闸门** —— 积分允许一直累积（含输出饱和期），
    不再用 `|raw| < max_step` 冻结（那个闸门会让"改 max_step"顺手改掉积分窗口）。
  · **只保留一个可调上限** `i_term_lim`（counts），界面上可改：
      - 贡献上限 = i_term_lim
      - 状态上限 = i_term_lim / Ki（N·s），自动换算
      - 填 0 = 关闭积分（纯 P）
"""
import pytest

from wrist_force_law import (
    TENSION_I_TERM_LIM_COUNTS,
    WristForceV2Params,
    WristTensionParams,
    WristTightParams,
    _incr_step,
)

KP, KI, DT = 10.0, 20.0, 0.01
MS = 340.0      # 界面当前值（大限幅，正好验证"限幅不再影响积分"）


def _run(e, lim, ticks=300, ms=MS, integ=0.0, resid=0.0):
    for _ in range(ticks):
        integ, resid, step = _incr_step(e, integ, resid, KP, KI, DT, ms, lim)
    return integ, step


# ---------------- 基元行为 ----------------

def test_accumulates_even_when_output_saturated():
    """饱和（kp·e=500 ≫ max_step=20）时也必须累积 —— 旧实现在这里会是 0。"""
    e = 50.0                       # kp·e = 500 ≫ max_step=20 → 输出饱和
    integ, _resid, _step = _incr_step(e, 0.0, 0.0, KP, KI, DT, 20.0, 5.0)
    # 一步就顶到状态上限（5/20 = 0.25 N·s），说明"累积"确实发生了
    assert integ == pytest.approx(5.0 / KI)
    assert integ > 0.0


def test_cap_is_the_only_brake():
    """不同上限 → 积分停在不同位置；且贡献不超过上限。"""
    for lim in (5.0, 20.0, 50.0):
        integ, _ = _run(5.0, lim)
        assert KI * integ == pytest.approx(lim)
        assert KI * integ <= lim + 1e-9


def test_zero_cap_disables_integral():
    """上限 0 → 纯 P：状态恒 0，步长只由 kp·e 决定。"""
    integ, step = _run(5.0, 0.0)
    assert integ == 0.0
    assert step == int(round(KP * 5.0))


def test_decoupled_from_max_step():
    """同一上限下，改 max_step 不改变积分结果（旧实现会变）。"""
    results = []
    for ms in (20.0, 50.0, 340.0):
        integ, _ = _run(5.0, 5.0, ms=ms)
        results.append(round(KI * integ, 6))
    assert len(set(results)) == 1


def test_unwinds_after_error_reverses():
    """接触后误差转负，积分要能反向退（不是只朝一个方向顶）。"""
    integ, _ = _run(5.0, 5.0)
    assert KI * integ == pytest.approx(5.0)
    for _ in range(100):
        integ, _resid, _step = _incr_step(-1.0, integ, 0.0, KP, KI, DT, MS, 5.0)
    assert KI * integ == pytest.approx(-5.0)


def test_gate_no_longer_depends_on_saturation():
    """小误差、大限幅（旧实现会因 |raw|<max_step 而积分）与大误差行为一致：
    两者都累积，只是上限不同。"""
    small, _r1, _s1 = _incr_step(0.1, 0.0, 0.0, KP, KI, DT, 340.0, 5.0)
    big, _r2, _s2 = _incr_step(5.0, 0.0, 0.0, KP, KI, DT, 340.0, 5.0)
    assert small == pytest.approx(0.1 * DT)
    assert big == pytest.approx(5.0 * DT)


# ---------------- 参数类 ----------------

def test_three_modes_accept_zero_cap():
    """填 0 不能再抛 ValueError（原来的校验要求 > 0）。"""
    common = dict(kp=KP, ki=KI, trim_sign=(1, 1, 1), max_trim=5000.0,
                  max_step=MS, f_max=25.0, deadband=0.05, i_term_lim=0.0)
    t = WristTensionParams(f_target=(5.0, 5.0, 5.0), **common)
    assert t.i_term_lim == 0.0
    g = WristTightParams(t_target=15.0, null_dir=(0, 1, 0), **common)
    assert g.i_term_lim == 0.0
    v = WristForceV2Params(
        tau_d=(0.0, 0.0), preload_n=5.0, kp=0.0, ki=0.0,
        f_min=0.2, r_m=(1, 0, 0), null_dir=(0, 1, 0),
        kp_inner=KP, ki_inner=KI,
        **{k: x for k, x in common.items() if k not in ("kp", "ki")})
    assert v.i_term_lim == 0.0


def test_default_cap_matches_module_constant():
    """不显式传时使用模块常量（当前 5 counts）。"""
    p = WristTensionParams(f_target=(5.0, 5.0, 5.0), kp=KP, ki=KI,
                           trim_sign=(1, 1, 1), max_trim=5000.0, max_step=MS,
                           f_max=25.0, deadband=0.05)
    assert p.i_term_lim == pytest.approx(TENSION_I_TERM_LIM_COUNTS)


def test_negative_cap_still_rejected():
    with pytest.raises(ValueError):
        WristTensionParams(f_target=(5.0, 5.0, 5.0), kp=KP, ki=KI,
                           trim_sign=(1, 1, 1), max_trim=5000.0, max_step=MS,
                           f_max=25.0, deadband=0.05, i_term_lim=-1.0)
