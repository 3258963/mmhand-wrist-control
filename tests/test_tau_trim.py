"""力矩修正（漏积分外环）单元测试 —— `wrist_force_law.tau_trim_step`。

2026-11-24 新增：力控的 τ 原本是**纯前馈**（`τ* → f_d → 追 f`），没有"τ 误差 →
修正"的环节，内环到不了 `f_d` 时力矩会长期偏低且无人补。这个外环补的正是
**稳态**那一部分，且必须是"漏积分 + 死区 + 可冻结"，不能带 P。

为什么不能带 P（历史依据，2026-11-18 实测）：
    `τ_meas = R·f` 与 `τ*` 只差"f 追上 f_d 没有"，τ 误差的响应就是内环的响应
    （本机内环极点 0.70）。外环带 P（`Kp_τ=20`）等于给同一快通道再套一环 →
    51% 的拍 α<1、摆动 0.075 N·m。
"""

import math

import pytest

from wrist_force_law import tau_trim_step


DT = 0.01


def test_basic_integration_rate():
    """`ki=1/s`、`e=0.1`、`dt=10ms` → 每拍涨 0.001。"""
    integ, trim = tau_trim_step(0.1, 0.0, 1.0, DT, 0.3)
    assert trim == pytest.approx(0.001, abs=1e-12)
    assert integ == trim


def test_sign_follows_error():
    """误差反号 → 修正量往反方向走。"""
    integ, trim = tau_trim_step(-0.1, 0.0, 1.0, DT, 0.3)
    assert trim == pytest.approx(-0.001, abs=1e-12)


def test_clamped_to_cap():
    """修正量被 ±cap 夹住，不能无限涨。"""
    _, trim = tau_trim_step(0.5, 0.29, 10.0, DT, 0.3)
    assert trim == pytest.approx(0.3, abs=1e-12)
    _, trim = tau_trim_step(-0.5, -0.29, 10.0, DT, 0.3)
    assert trim == pytest.approx(-0.3, abs=1e-12)


def test_ki_zero_disables_and_clears():
    """`ki=0` = 关闭：修正量归零（不是保持），这样关掉后不会留残余偏置。"""
    integ, trim = tau_trim_step(0.5, 0.2, 0.0, DT, 0.3)
    assert integ == 0.0 and trim == 0.0


def test_deadband_stops_integration():
    """误差在死区内 → 不积分（噪声不该被积起来）；只按 `leak` 轻微衰减。"""
    _, trim = tau_trim_step(0.001, 0.1, 1.0, DT, 0.3, deadband=0.005)
    assert trim <= 0.1
    assert trim == pytest.approx(0.1 * (1 - 0.1 * DT), rel=1e-9)
    # 死区外则正常积分
    _, trim2 = tau_trim_step(0.05, 0.1, 1.0, DT, 0.3, deadband=0.005)
    assert trim2 > 0.1


def test_leak_decays_inside_deadband():
    """误差跨过死区后，修正量按 `leak` 自己退掉（漏积分），不留永久偏置。"""
    integ = 0.2
    for _ in range(100):                       # 1 s
        integ, trim = tau_trim_step(0.0, integ, 1.0, DT, 0.3, leak=0.1)
    assert trim < 0.2
    assert trim == pytest.approx(0.2 * (1 - 0.1 * DT) ** 100, rel=1e-6)


def test_freeze_holds_value():
    """`freeze=True`（能力受限 α<1）→ 本拍不积分。"""
    _, trim = tau_trim_step(0.5, 0.1, 1.0, DT, 0.3, freeze=True)
    assert trim <= 0.1 + 1e-12


def test_nan_inputs_keep_state():
    """NaN/非法输入 → 原样返回，不污染状态。"""
    integ, trim = tau_trim_step(float("nan"), 0.1, 1.0, DT, 0.3)
    assert trim == 0.1 and integ == 0.1
    integ, trim = tau_trim_step(0.1, 0.1, 1.0, 0.0, 0.3)   # dt=0
    assert trim == 0.1


def test_nan_ki_keeps_state():
    integ, trim = tau_trim_step(0.1, 0.1, float("inf") * 0.0, DT, 0.3)
    assert trim == 0.1


def test_converges_when_plant_can_deliver():
    """对象能交付时：修正在"漏积分平衡点"停住并把差补掉大半。

    漏积分平衡：`ki·e = leak·trim`，且 `e = target − gain·(target+trim)`
    → `trim = target(1−gain) / (gain + leak/ki)`。
    `target=0.2, gain=0.6, ki=1, leak=0.1` → `trim = 0.08/0.7 ≈ 0.1143`。
    """
    target, gain, leak = 0.2, 0.6, 0.1
    trim = 0.0
    for _ in range(6000):                      # 60 s
        meas = gain * (target + trim)
        trim, _ = tau_trim_step(target - meas, trim, 1.0, DT, 0.3, leak=leak,
                                deadband=0.0)
    expect = target * (1 - gain) / (gain + leak)
    assert trim == pytest.approx(expect, abs=2e-3)
    # 补上了：残差显著小于"不补"时的 0.08
    assert abs(target - gain * (target + trim)) < 0.02


def test_pure_integration_reaches_exact():
    """`leak=0` 时是纯积分 → 稳态差被完全补掉。"""
    target, gain = 0.2, 0.6
    trim = 0.0
    for _ in range(6000):
        meas = gain * (target + trim)
        trim, _ = tau_trim_step(target - meas, trim, 1.0, DT, 0.3, leak=0.0,
                                deadband=0.0)
    assert trim == pytest.approx(target / gain - target, abs=2e-3)


def test_bounded_when_plant_saturates():
    """对象饱和（永远给不出目标）→ 修正量被 cap 限住，不会发散。"""
    trim = 0.0
    for _ in range(5000):
        meas = min(0.2 + trim, 0.12)
        trim, _ = tau_trim_step(0.2 - meas, trim, 1.0, DT, 0.3)
    assert trim <= 0.3 + 1e-12
    assert math.isfinite(trim)
