"""wrist_control_law 位置环测试（两种结构：前馈+PID / 纯PID）。

golden 值由 H7 包 derived_constants.json 六段常数独立预计算
（k=1e5 c/m、目标 (1°,0°)、kp=0：C1=+0.556 / C2=+38.969 / C3=−29.596 counts）。
纯 P 的旧接口 wrist_control_step_model 仍是 = ki=kd=0 的变体 A，逐位不变。
"""
import math

import pytest

from wrist_control_law import (
    FLAG_FEEDBACK_CLAMPED,
    FLAG_I_CLAMPED,
    FLAG_LOW_PITCH,
    FLAG_NONFINITE,
    FLAG_OK,
    FLAG_TARGET_CLAMPED,
    WristCalib,
    WristControlParams,
    WristPidState,
    wrist_control_step,
    wrist_control_step_model,
    wrist_control_step_pid,
)


def make_p(kp=0.0, limit=25.0):
    p = WristControlParams()
    p.origin = [1000, 2000, 3000]
    p.kp = kp
    p.deadband_deg = 0.3
    p.target_limit_deg = limit
    p.soft_limit = 5000
    return p


CALIB = WristCalib([1e5, 1e5, 1e5], [0.0, 0.0])


def test_golden_feedforward():
    out, flags = wrist_control_step_model(make_p(), CALIB, 0.0, 0.0, 1.0, 0.0)
    assert out is not None and flags == FLAG_OK
    d = [o - org for o, org in zip(out, (1000, 2000, 3000))]
    assert d[0] == pytest.approx(1, abs=1)      # 0.556 → 边界舍入
    assert d[1] == pytest.approx(39, abs=1)     # 38.969
    assert d[2] == pytest.approx(-30, abs=1)    # −29.596


def test_delta_invariance():
    calib = WristCalib([1e5, 1e5, 1e5], [2.0, 0.0])
    out, flags = wrist_control_step_model(make_p(), calib, 0.0, 0.0, 0.0, 0.0)
    assert out == [1000, 2000, 3000]
    assert flags == FLAG_OK


def test_pitch_feedback_uses_dp_offset(monkeypatch):
    """回归：反馈侧的 pitch 必须用 δp，不能用 δr。

    δr=0、δp=5、反馈 30° → out_fb 应在 35° 求值；旧实现误用 dr，
    会退回到 30°，使 C2/C3 的 pitch 力臂在 33.8° 附近反号。
    """
    import wrist_control_law as law

    calls = []
    real_eval = law.wrist_eval

    def spy(roll_rad, pitch_rad):
        calls.append((roll_rad, pitch_rad))
        return real_eval(roll_rad, pitch_rad)

    monkeypatch.setattr(law, "wrist_eval", spy)
    calib = WristCalib([1e5, 1e5, 1e5], [0.0, 5.0])
    out, flags = wrist_control_step_model(make_p(kp=0.0), calib,
                                          0.0, 30.0, 0.0, 25.0)
    assert out is not None and flags == FLAG_OK
    # 调用顺序：out_t=(0, 30)、out_ref=(0, 5)、out_fb=(0, 35)
    assert calls[2][1] == pytest.approx(math.radians(35.0))


def test_correction_sign_and_gain():
    out, _ = wrist_control_step_model(make_p(kp=0.6), CALIB, 0.5, 0.0, 1.0, 0.0)
    # ff=38.97 + corr=+11.69 = 50.66（校正与误差同向，往目标继续推）
    assert out[1] - 2000 == pytest.approx(50, abs=2)


def test_low_pitch_clamp():
    p = make_p()
    out_clamped, flags_c = wrist_control_step_model(p, CALIB, 0.0, 0.0, 0.0, -25.0)
    out_direct, flags_d = wrist_control_step_model(p, CALIB, 0.0, 0.0, 0.0, -24.0)
    assert out_clamped == out_direct
    assert flags_c & FLAG_LOW_PITCH
    assert flags_d & FLAG_LOW_PITCH   # 恰好 −24 已进低置信区


def test_nonfinite():
    out, flags = wrist_control_step_model(make_p(), CALIB, 0.0, 0.0, math.nan, 0.0)
    assert out is None and flags & FLAG_NONFINITE
    out, flags = wrist_control_step_model(make_p(), CALIB, 0.0, math.inf, 0.0, 0.0)
    assert out is None and flags & FLAG_NONFINITE


def test_soft_limit():
    calib = WristCalib([1e9, 1e9, 1e9], [0.0, 0.0])
    out, _ = wrist_control_step_model(make_p(), calib, 0.0, 0.0, 25.0, 45.0)
    for i, org in enumerate((1000, 2000, 3000)):
        assert abs(out[i] - org) == 5000


def test_target_range_clamp():
    p = make_p(limit=25.0)
    out_clamped, flags_c = wrist_control_step_model(p, CALIB, 0.0, 0.0, 30.0, 50.0)
    out_direct, flags_d = wrist_control_step_model(p, CALIB, 0.0, 0.0, 25.0, 25.0)
    assert out_clamped == out_direct
    assert flags_c & FLAG_TARGET_CLAMPED
    assert not flags_d & FLAG_TARGET_CLAMPED


def test_feedback_clamp():
    out, flags = wrist_control_step_model(make_p(), CALIB, 30.0, 0.0, 1.0, 0.0)
    assert out is not None
    assert flags & FLAG_FEEDBACK_CLAMPED


def test_feedforward_ref_matches_origin_pose():
    """前馈参考必须与 origin 同一姿态（2026-11-10 修复）。

    origin 记的是启动瞬间的电机计数，前馈算的是 origin→目标 的绳长增量。
    若从 5° 启动、命令 10°，前馈只能走 l(10)−l(5)；旧版按零位算 l(10)−l(0)，
    多算的部分由 P 校正硬拽，稳态偏 s/(1−kp)，kp=0.6 时放大 2.5 倍。
    """
    from wrist_model import wrist_eval

    p = make_p(kp=0.0)
    out, flags = wrist_control_step_model(p, CALIB, 5.0, 0.0, 10.0, 0.0,
                                          ref_roll_deg=5.0)
    assert out is not None and flags == FLAG_OK
    ref = wrist_eval(math.radians(5.0), 0.0)
    tgt = wrist_eval(math.radians(10.0), 0.0)
    expect = 1e5 * (tgt.s_m[0][1] - ref.s_m[0][1])   # ROLL 段、C2
    assert out[1] - 2000 == pytest.approx(expect, abs=1)

    # 缺省 ref=None 仍是"零位参考"（旧行为，供 golden 用例与离线复算）
    out_zero, _ = wrist_control_step_model(p, CALIB, 5.0, 0.0, 10.0, 0.0)
    expect_zero = 1e5 * (tgt.s_m[0][1] - wrist_eval(0.0, 0.0).s_m[0][1])
    assert out_zero[1] - 2000 == pytest.approx(expect_zero, abs=1)


def test_v1_untouched():
    p = WristControlParams()
    p.origin = [1000, 2000, 3000]
    p.gain_roll = [50.0, 0.0, 30.0]
    p.gain_pitch = [0.0, -40.0, 30.0]
    p.kp = 0.6
    p.deadband_deg = 0.3
    p.target_limit_deg = 25.0
    p.soft_limit = 5000
    assert wrist_control_step(p, 1.0, 0.0, 2.0, 0.0) == [1130, 2000, 3078]
    assert wrist_control_step(p, 1.0, 1.0, 2.0, -1.0)[1] == 2088
    assert wrist_control_step(p, 1.0, 0.0, 100.0, 0.0)[0] == 2970
    assert wrist_control_step(p, 1.8, 0.0, 2.0, 0.0)[0] == 1100


# ============================================================
# 位置环两种结构（2026-11-10）
# ============================================================

# 收绳为负：counts↑ ⇒ 绳变短（台架口动确认后写入标定）
# 两套符号的标定：位置环方向必须跟着 k 走，所以两种都要测。
# CALIB_PAY 与出厂 wrist_calib.json 一致（k>0 ⇒ counts↑=放绳）；CALIB_REEL 是镜像。
CALIB_PAY = WristCalib([1e5, 1e5, 1e5], [0.0, 0.0])
CALIB_REEL = WristCalib([-1e5, -1e5, -1e5], [0.0, 0.0])
CALIB_NEG = CALIB_REEL          # 兼容旧测试名
BASE = [1000, 2000, 3000]


def _pid_p(kp=0.6, ki=0.0, kd=0.0, limit=25.0):
    p = make_p(kp=kp, limit=limit)
    p.ki, p.kd = ki, kd
    p.i_limit_deg = limit
    p.d_filter_alpha = 1.0          # 测试里不滤波，方便算期望值
    return p


def test_ff_pid_equals_old_model_when_ki_kd_zero():
    """前馈+PID 在 ki=kd=0 时与旧接口逐位一致（旧接口是它的特例）。"""
    for kp in (0.0, 0.3, 0.6):
        st = WristPidState()
        for r, t in ((0.0, 1.0), (0.5, 1.0), (-3.0, 2.0), (20.0, -20.0)):
            a, fa = wrist_control_step_pid(_pid_p(kp), CALIB, st, r, 0.0, t, 0.0,
                                           0.01, feedforward=True,
                                           ref_roll_deg=0.0)
            b, fb = wrist_control_step_model(_pid_p(kp), CALIB, r, 0.0, t, 0.0,
                                             ref_roll_deg=0.0)
            assert a == b and fa == fb, (kp, r, t, a, b)


def test_pure_pid_zero_error_holds_at_measured():
    """纯PID：误差为 0 ⇒ 目标 = 实测基准（原地保持，不回 origin）。"""
    p = _pid_p()
    st = WristPidState()
    base = [500, 600, 700]
    out, fl = wrist_control_step_pid(p, CALIB_PAY, st, 0.0, 0.0, 0.0, 0.0,
                                     0.01, feedforward=False, base_counts=base)
    assert out == base and fl == FLAG_OK


def test_pure_pid_sign_and_gain():
    """纯PID：+1° 误差 ⇒ C2 走 kp×J 的 counts，期望值由 J=−k·R 独立算出。"""
    from wrist_model import wrist_eval

    r = wrist_eval(0.0, 0.0).r_m[0][1]
    for calib, sign in ((CALIB_PAY, 1.0), (CALIB_REEL, -1.0)):
        p = _pid_p(kp=0.5)
        st = WristPidState()
        out, _ = wrist_control_step_pid(p, calib, st, 0.0, 0.0, 1.0, 0.0,
                                        0.01, feedforward=False,
                                        base_counts=BASE)
        expect = 0.5 * (-sign * 1e5 * r * math.radians(1.0))   # kp·J·e
        assert out[1] - BASE[1] == pytest.approx(expect, abs=1), (calib, out, expect)
        # C2 的 r<0：要增大 ROLL，k>0 时 counts↑、k<0 时 counts↓
        assert out[1] - BASE[1] == (1 if sign > 0 else -1) * abs(out[1] - BASE[1])


def test_per_cable_k_sign_flips_only_that_cable():
    """k 的符号是**逐路**的：只把 C1 取反，只该影响 C1 自己的 counts。

    （现场情形：C1 电机反向安装 / 换线，k=[-,+,+]；C2/C3 不变。）
    """
    p = make_p(kp=0.0)
    mix = WristCalib([-1e5, 1e5, 1e5], [0.0, 0.0])
    a, _ = wrist_control_step_pid(p, CALIB_PAY, WristPidState(), 0.0, 0.0,
                                  -2.0, 3.0, 0.01, feedforward=True,
                                  ref_roll_deg=0.0, ref_pitch_deg=0.0)
    b, _ = wrist_control_step_pid(p, mix, WristPidState(), 0.0, 0.0,
                                  -2.0, 3.0, 0.01, feedforward=True,
                                  ref_roll_deg=0.0, ref_pitch_deg=0.0)
    assert a[1] == b[1] and a[2] == b[2], (a, b)      # C2/C3 不受影响
    assert a[0] - BASE[0] == -(b[0] - BASE[0]), (a, b)  # C1 整体反号
    assert abs(a[0] - BASE[0]) > 10, a                # 且确实有量（不是 0 对 0）


def test_k_sign_flips_output():
    """同一目标、两种 k 符号 ⇒ 三路输出整体反号（符号只由 k 决定，代码不写死）。"""
    p = make_p(kp=0.6)
    a, _ = wrist_control_step_pid(p, CALIB_PAY, WristPidState(), 0.0, 0.0,
                                  2.0, 1.0, 0.01, feedforward=True,
                                  ref_roll_deg=0.0, ref_pitch_deg=0.0)
    b, _ = wrist_control_step_pid(p, CALIB_REEL, WristPidState(), 0.0, 0.0,
                                  2.0, 1.0, 0.01, feedforward=True,
                                  ref_roll_deg=0.0, ref_pitch_deg=0.0)
    for i in range(3):
        assert (a[i] - BASE[i]) == -(b[i] - BASE[i]), (i, a, b)


def test_pure_pid_target_step_has_no_derivative_kick():
    """微分作用在反馈上：目标阶跃那一拍 D 项不出现（不会砸尖峰）。"""
    p = _pid_p(kp=0.3, kd=1.0)
    st = WristPidState()
    # 首拍：误差 5°，但 primed=False ⇒ D=0，只有 P
    out1, _ = wrist_control_step_pid(p, CALIB_NEG, st, 0.0, 0.0, 5.0, 0.0,
                                     0.01, feedforward=False, base_counts=BASE)
    p_only, _ = wrist_control_step_pid(_pid_p(kp=0.3, kd=0.0), CALIB_NEG,
                                       WristPidState(),
                                       0.0, 0.0, 5.0, 0.0, 0.01,
                                       feedforward=False, base_counts=BASE)
    assert out1 == p_only
    # 第二拍反馈没动（速度 0）⇒ D 仍为 0
    out2, _ = wrist_control_step_pid(p, CALIB_NEG, st, 0.0, 0.0, 5.0, 0.0,
                                     0.01, feedforward=False, base_counts=BASE)
    p_only2, _ = wrist_control_step_pid(_pid_p(kp=0.3, kd=0.0), CALIB_NEG,
                                        WristPidState(),
                                        0.0, 0.0, 5.0, 0.0, 0.01,
                                        feedforward=False, base_counts=BASE)
    assert out2 == p_only2


def test_derivative_damps_motion():
    """反馈在朝目标跑（速度 +）时，D 项应让本拍修正量变小。"""
    p = _pid_p(kp=0.3, kd=0.2)
    st = WristPidState()
    wrist_control_step_pid(p, CALIB_NEG, st, 0.0, 0.0, 5.0, 0.0, 0.01,
                           feedforward=False, base_counts=BASE)     # 播种 prev_fb=0
    out_mv, _ = wrist_control_step_pid(p, CALIB_NEG, st, 0.01, 0.0, 5.0, 0.0,
                                       0.01, feedforward=False, base_counts=BASE)
    p_only, _ = wrist_control_step_pid(_pid_p(kp=0.3, kd=0.0), CALIB_NEG,
                                       WristPidState(),
                                       0.01, 0.0, 5.0, 0.0, 0.01,
                                       feedforward=False, base_counts=BASE)
    # 朝正方向跑 ⇒ 修正量绝对值应更小
    assert abs(out_mv[1] - BASE[1]) < abs(p_only[1] - BASE[1])


def test_integral_grows_and_is_clamped():
    p = _pid_p(kp=0.0, ki=10.0, limit=5.0)
    st = WristPidState()
    base = [0, 0, 0]
    for _ in range(500):
        _, fl = wrist_control_step_pid(p, CALIB_NEG, st, 0.0, 0.0, 4.0, 0.0,
                                       0.01, feedforward=False, base_counts=base)
    # 4° 恒定误差 ⇒ ∫e 一路涨到 i_limit/ki，然后被钳住
    assert fl & FLAG_I_CLAMPED
    assert st.integ_deg[0] == pytest.approx(p.i_limit_deg / p.ki, rel=1e-9)


def test_integral_kills_steady_state_offset():
    """纯PID + 恒定偏置（模拟重力下垂）：纯P 收敛到有残差，加 I 后把残差吃掉。

    对象模型：一阶 + 每拍固定下垂量（不追求真实，只验证"有 I 比没 I 更靠目标"）。
    """
    base = [0, 0, 0]
    # 先标定"该环 1° 对应多少 counts"（用 kp=1 探一次，避免手写几何常数）
    probe, _ = wrist_control_step_pid(_pid_p(kp=1.0), CALIB_NEG, WristPidState(),
                                      0.0, 0.0, 1.0, 0.0, 0.01,
                                      feedforward=False, base_counts=base)
    cpd = probe[1] - base[1]               # counts/deg（C2，带符号）
    assert abs(cpd) > 1.0

    def run(ki):
        p = _pid_p(kp=0.5, ki=ki)
        st = WristPidState()
        ang = 0.0
        for _ in range(2000):
            out, _ = wrist_control_step_pid(p, CALIB_NEG, st, ang, 0.0, 5.0, 0.0,
                                            0.01, feedforward=False,
                                            base_counts=base)
            cmd_deg = ang + (out[1] - base[1]) / cpd
            ang += (cmd_deg - ang) * 0.3 - 0.02      # 一阶对象 + 0.02°/拍下垂
        return abs(5.0 - ang)

    e_p = run(0.0)
    e_pi = run(2.0)
    assert e_p > 0.05, e_p            # 纯 P 有残差（下垂 0.02 撑不住）
    assert e_pi < e_p * 0.5, (e_p, e_pi)   # 积分把残差压下去


def test_pure_pid_needs_base_counts():
    p = _pid_p()
    out, fl = wrist_control_step_pid(p, CALIB_NEG, WristPidState(), 0.0, 0.0,
                                     1.0, 0.0, 0.01, feedforward=False,
                                     base_counts=None)
    assert out is None and fl & FLAG_NONFINITE


def test_axis_disable_removes_term():
    """分轴关掉后：该轴的 PID 与前馈都不再进输出。"""
    p = _pid_p(kp=0.6, ki=5.0, kd=0.01)
    st = WristPidState()
    both, _ = wrist_control_step_pid(p, CALIB_NEG, st, 1.0, 1.0, 3.0, 4.0,
                                     0.01, feedforward=True, ref_roll_deg=1.0,
                                     ref_pitch_deg=1.0)
    st2 = WristPidState()
    roll_only, _ = wrist_control_step_pid(p, CALIB_NEG, st2, 1.0, 1.0, 3.0, 4.0,
                                          0.01, feedforward=True, ref_roll_deg=1.0,
                                          ref_pitch_deg=1.0, pitch_enabled=False)
    assert both != roll_only
    # 关掉 PITCH 后第二次调用与"pitch 目标=当前"的纯 roll 调用一致
    st3 = WristPidState()
    eq, _ = wrist_control_step_pid(p, CALIB_NEG, st3, 1.0, 1.0, 3.0, 1.0,
                                   0.01, feedforward=True, ref_roll_deg=1.0,
                                   ref_pitch_deg=1.0, pitch_enabled=False)
    assert roll_only == eq


def test_feedforward_direction_follows_k_sign():
    """k 的符号只决定"放/收"：+5° ROLL 在 k>0 时 C2 放长(counts↑)、k<0 时 C2 收(counts↓)。

    出厂标定是 k=+130380（counts↑=放绳）；这里两种都断言，防止有人把符号写死。
    """
    p = make_p(kp=0.0)
    pay, _ = wrist_control_step_pid(p, CALIB_PAY, WristPidState(), 0.0, 0.0,
                                    5.0, 0.0, 0.01, feedforward=True,
                                    ref_roll_deg=0.0)
    reel, _ = wrist_control_step_pid(p, CALIB_REEL, WristPidState(), 0.0, 0.0,
                                     5.0, 0.0, 0.01, feedforward=True,
                                     ref_roll_deg=0.0)
    d_pay = [o - org for o, org in zip(pay, BASE)]
    d_reel = [o - org for o, org in zip(reel, BASE)]
    assert d_pay[1] > 0 and d_pay[2] < 0, d_pay     # C2 放、C3 收（几何决定）
    assert d_reel[1] < 0 and d_reel[2] > 0, d_reel   # 整体反号
    for i in range(3):
        assert d_pay[i] == -d_reel[i], (i, d_pay, d_reel)

