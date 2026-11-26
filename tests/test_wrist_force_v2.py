"""wrist_force_v2 + wrist_tda 联合测试。"""
import math
import pytest

from wrist_force_law import (STALE_MS, F_SENSOR_MIN_N, FORCE_OK, FORCE_OVERLOAD,
                              FORCE_SENSOR_FAULT, FORCE_STALE,
                              FORCE_TDA_INFEASIBLE,
                              WristForceV2Params, WristForceV2State,
                              wrist_force_v2_step)
from wrist_tda import (TDA_OK, TDA_ALPHA_CLAMPED, TDA_INFEASIBLE,
                        TDA_NO_NULL, tda_solve, preload_window)
from wrist_model import wrist_eval, positive_null_direction

# 零位 R 和零空间（预计算一次）
_out = wrist_eval(0.0, 0.0)
_R = _out.r_m
_N = positive_null_direction(0.0, 0.0)
assert _N is not None

BASE = dict(
    tau_d=(0.0, 0.0), preload_n=5.0,
    kp=100.0, ki=10.0, kp_inner=50.0, ki_inner=50.0,
    trim_sign=(1.0, 1.0, 1.0),
    max_trim=3000.0, f_max=30.0, f_min=0.5,
    deadband=0.01, r_m=_R, null_dir=_N,
)


class TestTDA:
    def test_zero_torque_pure_preload(self):
        f, fl, a = tda_solve(_R, _N, 0, 0, 5.0, 0.5, 30.0)
        assert f is not None and fl == TDA_OK and a == 1.0
        assert all(0.5 <= v <= 30.0 for v in f)
        # 验证 τ=Rf≈0
        tau_r = sum(_R[0][i] * f[i] for i in range(3))
        tau_p = sum(_R[1][i] * f[i] for i in range(3))
        assert abs(tau_r) < 1e-10 and abs(tau_p) < 1e-10

    def test_nonzero_torque(self):
        f, fl, a = tda_solve(_R, _N, 0.05, -0.03, 5.0, 0.5, 30.0)
        assert f is not None and fl == TDA_OK and a == 1.0
        tau_r = sum(_R[0][i] * f[i] for i in range(3))
        tau_p = sum(_R[1][i] * f[i] for i in range(3))
        assert tau_r == pytest.approx(0.05, abs=1e-10)
        assert tau_p == pytest.approx(-0.03, abs=1e-10)

    def test_alpha_saturation(self):
        f, fl, a = tda_solve(_R, _N, 5.0, 5.0, 5.0, 0.5, 30.0)
        assert f is not None and fl & TDA_ALPHA_CLAMPED and a < 1.0
        assert all(0.5 - 1e-6 <= v <= 30.0 + 1e-6 for v in f)

    def test_infeasible_preload(self):
        f, fl, a = tda_solve(_R, _N, 0, 0, 100.0, 0.5, 30.0)
        assert f is None and fl & TDA_INFEASIBLE

    def test_no_null_direction(self):
        out = wrist_eval(0.3, -0.2)  # 该位姿无全正预紧
        n = positive_null_direction(0.3, -0.2)
        assert n is None
        f, fl, a = tda_solve(out.r_m if out.math_valid else _R, n,
                              0, 0, 5.0, 0.5, 30.0)
        assert f is None and fl & TDA_NO_NULL

    def test_constraint_satisfaction_random(self):
        """随机力矩+预紧，验证输出始终满足约束。"""
        import random
        random.seed(42)
        for _ in range(100):
            tr = random.uniform(-2, 2)
            tp = random.uniform(-2, 2)
            t = random.uniform(0, 20)
            fmin = random.uniform(0.1, 2)
            fmax = fmin + random.uniform(5, 40)
            f, fl, a = tda_solve(_R, _N, tr, tp, t, fmin, fmax)
            if f is not None:
                assert all(fmin - 1e-6 <= v <= fmax + 1e-6 for v in f), \
                    f"violated: {f} not in [{fmin},{fmax}]"


class TestForceV2:
    def test_params_validation(self):
        with pytest.raises(ValueError):
            WristForceV2Params(tau_d=(float('nan'), 0), **{k: v for k, v in BASE.items() if k != 'tau_d'})
        with pytest.raises(ValueError):
            WristForceV2Params(**{**BASE, 'f_min': 30.0, 'f_max': 0.5})
        with pytest.raises(ValueError):
            WristForceV2Params(**{**BASE, 'kp': -1.0})

    def test_trim_sign_validation(self):
        """方向符号必须是 3 个 ±1——错符号=正反馈，无默认可瞒。"""
        for bad in ((0, 1, 1), (2, 1, 1), (-2, 1, 1), (-1, 1),
                    (-1, 1, 1, 1), "(-1,1,1)"):
            with pytest.raises(ValueError):
                WristForceV2Params(**{**BASE, 'trim_sign': bad})
        # 合法：±1（int/float 皆可）
        WristForceV2Params(**{**BASE, 'trim_sign': (-1, 1, 1.0)})

    def test_trim_sign_flips_output(self):
        """同输入下 trim 符号逐缆翻转；积分状态存纠错方向量不受影响。"""
        f = [1.0, 3.0, 3.0]
        st_neg, st_pos = WristForceV2State(), WristForceV2State()
        p_neg = WristForceV2Params(**{**BASE, 'trim_sign': (-1.0, 1.0, -1.0)})
        p_pos = WristForceV2Params(**BASE)
        t_neg, fl_neg, _a = wrist_force_v2_step(p_neg, st_neg, f, 10.0, 0.01, tda_solve)
        t_pos, fl_pos, _a = wrist_force_v2_step(p_pos, st_pos, f, 10.0, 0.01, tda_solve)
        assert t_neg is not None and t_pos is not None
        for i in range(3):
            assert t_neg[i] == pytest.approx((-1 if i in (0, 2) else 1) * t_pos[i])

    def test_alpha_scaled_when_torque_unreachable(self):
        """不可达大力矩（τ_d 远超能力）：TDA 打折，输出仍是界内的张力目标。

        （2026-11-19：外环删除后不再有 `integ_tau`，这里改为验证"打折后仍合法"。）
        """
        p = WristForceV2Params(**{**BASE, 'tau_d': (5.0, 5.0)})
        st = WristForceV2State()
        f = [3.0, 3.0, 3.0]
        for _ in range(500):
            trim, flags, alpha = wrist_force_v2_step(p, st, f, 10.0, 0.01, tda_solve)
            assert trim is not None and flags == FORCE_OK
            assert alpha < 1.0                      # 目标不可达 → 打折
        assert not hasattr(st, "integ_tau")         # 外环积分器已彻底移除

    def test_outer_pi_removed(self):
        """2026-11-18：力矩 PI 外环已移除，改为纯前馈。

        旧断言是"α=1 时 integ_tau 会累积"；现在外环不存在（连字段都删了），改为断言：
        ① 没有 `integ_tau`；
        ② 输出与 `kp`/`ki` 无关（TDA 直接吃 τ_d，不再加 u）。
        """
        f = [3.0, 3.0, 3.0]
        outs = []
        for kp, ki in ((0.0, 0.0), (100.0, 50.0)):
            p = WristForceV2Params(**{**BASE, 'tau_d': (0.05, 0.0),
                                      'preload_n': 10.0, 'kp': kp, 'ki': ki})
            st = WristForceV2State()
            trim, fl, _a = wrist_force_v2_step(p, st, f, 10.0, 0.01, tda_solve)
            assert trim is not None and fl == FORCE_OK
            assert not hasattr(st, "integ_tau")
            outs.append(list(trim))
        assert outs[0] == outs[1]                  # kp/ki 不再影响任何输出

    def test_zero_torque_hold(self):
        """零力矩+预紧 → trim 应趋稳（张力在目标附近）。"""
        p = WristForceV2Params(**BASE)
        st = WristForceV2State()
        # 模拟初始张力 = TDA 零力矩输出（理想状态）
        f_ideal, _, _ = tda_solve(_R, _N, 0, 0, 5.0, 0.5, 30.0)
        trim, flags, _alpha = wrist_force_v2_step(p, st, f_ideal, 10.0, 0.01,
                                          tda_solve)
        assert trim is not None and flags == FORCE_OK
        # 误差接近零 → trim 很小
        assert all(abs(t) < 10.0 for t in trim), trim

    def test_negative_sample_clamped(self):
        """负张力样本被钳位到 0，不再误报过期。"""
        p = WristForceV2Params(**BASE)
        st = WristForceV2State()
        trim, flags, _alpha = wrist_force_v2_step(p, st, (-2.0, 3.0, 4.0), 10.0, 0.01,
                                          tda_solve)
        assert trim is not None and flags == FORCE_OK

    def test_stale_freezes(self):
        p = WristForceV2Params(**BASE)
        st = WristForceV2State()
        f, _, _ = tda_solve(_R, _N, 0, 0, 5.0, 0.5, 30.0)
        wrist_force_v2_step(p, st, f, 10.0, 0.01, tda_solve)  # 预热
        integ_before = list(st.integ)
        trim, flags, _alpha = wrist_force_v2_step(p, st, f, STALE_MS + 50.0, 0.01, tda_solve)
        assert trim is None and flags == FORCE_STALE
        assert st.integ == integ_before          # 过期 → 内环积分也不动

    def test_overload_stops(self):
        p = WristForceV2Params(**{**BASE, 'f_max': 5.0})
        st = WristForceV2State()
        trim, flags, _alpha = wrist_force_v2_step(p, st, (10.0, 10.0, 10.0), 10.0, 0.01,
                                          tda_solve)
        assert trim is None and flags == FORCE_OVERLOAD

    def test_sensor_fault_stops(self):
        """2026-11-23 现场事故回归：C2 报 −396.65 N（物理不可能）。

        旧行为：`max(0, f)` 钳 0 继续控 → 误差恒为正 → 每拍满步收绳，永不收敛。
        新行为：低于 `F_SENSOR_MIN_N` 立即返回 FORCE_SENSOR_FAULT，由调用方停环。
        """
        p = WristForceV2Params(**BASE)
        st = WristForceV2State()
        trim, flags, _alpha = wrist_force_v2_step(
            p, st, (-0.01, -396.65, -0.09), 10.0, 0.01, tda_solve)
        assert trim is None
        assert flags & FORCE_SENSOR_FAULT

    def test_small_negative_still_clamped(self):
        """零点漂移级的小负值（−0.5 N）仍按松绳处理：钳 0 继续控。"""
        p = WristForceV2Params(**BASE)
        st = WristForceV2State()
        trim, flags, _alpha = wrist_force_v2_step(
            p, st, (-0.5, 3.0, 3.0), 10.0, 0.01, tda_solve)
        assert not (flags & FORCE_SENSOR_FAULT)

    def test_torque_tracking_convergence(self):
        """给非零 τ_d，模拟一阶张力响应，验证 τ 误差收敛。"""
        p = WristForceV2Params(**{**BASE, 'tau_d': (0.1, -0.05),
                                   'kp': 500.0, 'ki': 50.0})
        st = WristForceV2State()
        # 初始张力 = 零力矩 TDA 输出（τ≈0）
        f_cur = list(tda_solve(_R, _N, 0, 0, 5.0, 0.5, 30.0)[0])
        tau_err_history = []
        for _ in range(500):  # 5 秒 @ 100Hz
            # 模拟一阶张力响应：f 向 f_d 移动（时间常数 0.1s）
            f_d, _, _ = tda_solve(_R, _N, p.tau_d[0], p.tau_d[1],
                                  p.preload_n, p.f_min, p.f_max)
            for i in range(3):
                f_cur[i] += (f_d[i] - f_cur[i]) * 0.1
            trim, flags, _alpha = wrist_force_v2_step(p, st, f_cur, 10.0, 0.01,
                                              tda_solve)
            if trim is None:
                break
            # 简化执行：trim 直接影响 f（单位增益）
            for i in range(3):
                f_cur[i] += trim[i] * 0.001
                f_cur[i] = max(0.0, f_cur[i])
            tau_r = sum(_R[0][j] * f_cur[j] for j in range(3))
            tau_p = sum(_R[1][j] * f_cur[j] for j in range(3))
            tau_err_history.append(math.hypot(tau_r - 0.1, tau_p + 0.05))
        # 误差应明显减小（不必到零——纯 P+I 在一阶滞后下有残余）
        if tau_err_history:
            assert tau_err_history[-1] < tau_err_history[0] * 0.5, \
                f"no convergence: first={tau_err_history[0]:.6f} last={tau_err_history[-1]:.6f}"

    def test_torque_tracking_with_sign(self):
        """带 trim_sign 的闭环收敛：仿真植物按符号翻 trim 后再作用于张力。"""
        p = WristForceV2Params(**{**BASE, 'tau_d': (0.1, -0.05),
                                   'trim_sign': (-1.0, 1.0, 1.0),
                                   'kp': 500.0, 'ki': 50.0})
        st = WristForceV2State()
        f_cur = list(tda_solve(_R, _N, 0, 0, 5.0, 0.5, 30.0)[0])
        hist = []
        for _ in range(500):
            trim, flags, _alpha = wrist_force_v2_step(p, st, f_cur, 10.0, 0.01,
                                              tda_solve)
            if trim is None:
                break
            for i in range(3):
                f_cur[i] += p.trim_sign[i] * trim[i] * 0.001   # 符号在植物侧
                f_cur[i] = max(0.0, f_cur[i])
            tau_r = sum(_R[0][j] * f_cur[j] for j in range(3))
            tau_p = sum(_R[1][j] * f_cur[j] for j in range(3))
            hist.append(math.hypot(tau_r - 0.1, tau_p + 0.05))
        assert hist and hist[-1] < hist[0] * 0.5, \
            f"no convergence with sign: first={hist[0]:.6f} last={hist[-1]:.6f}"

    def test_tda_infeasible_when_null_missing(self):
        """位姿无零空间 → 不可行。"""
        p = WristForceV2Params(**{**BASE, 'null_dir': None})
        st = WristForceV2State()
        trim, flags, _alpha = wrist_force_v2_step(p, st, (3, 3, 3), 10.0, 0.01,
                                          tda_solve)
        assert trim is None
        assert flags & FORCE_TDA_INFEASIBLE


class TestInnerGainSplit:
    """2026-11-17：内环 P/I 分离（2026-11-19 起 `trim_gain` 彻底删除）。

    旧设计 `trim_gain` 同时当 P 和 I（P=I=50）⇒ S·Kp = 2.32 > 2，
    实测力矩模式 50 Hz 极限环、稳态跟不上目标。改成 kp_inner/ki_inner 后
    与张力环共用同一组增益（S·Kp = 0.70）。
    """

    def test_gains_taken_as_given(self):
        p = WristForceV2Params(**{**BASE, 'kp_inner': 15.0, 'ki_inner': 20.0})
        assert (p.kp_inner, p.ki_inner) == (15.0, 20.0)

    def test_requires_both_inner_gains(self):
        with pytest.raises(ValueError):
            WristForceV2Params(**{**BASE, 'kp_inner': None})
        with pytest.raises(ValueError):
            WristForceV2Params(**{**BASE, 'ki_inner': None})
        with pytest.raises(ValueError):
            WristForceV2Params(**{**BASE, 'kp_inner': None, 'ki_inner': None})

    def test_inner_gains_and_i_term_lim_honoured(self):
        """2026-11-20：力矩模式必须真的吃进 i_term_lim。

        曾经这里有个 bug —— `_check_common` 收到 None 后返回 max_trim(5000)，
        把调用方给的 5.0 覆盖掉，等于积分钳制对力矩模式完全没生效。
        """
        p = WristForceV2Params(**{**BASE, 'kp_inner': 15.0, 'ki_inner': 20.0,
                                  'i_term_lim': 5.0})
        assert p.i_term_lim == 5.0
        # 不显式给时回退到全局常量（当前 5.0）
        p2 = WristForceV2Params(**{**BASE, 'kp_inner': 15.0, 'ki_inner': 20.0})
        assert p2.i_term_lim == pytest.approx(5.0)

    def test_split_gains_track_torque_target(self):
        """S·Kp=0.70：600 拍后 τ 稳定跟住 τ_d，抖动 < 0.005 N·m。"""
        p = WristForceV2Params(**{**BASE, 'tau_d': (0.01, 0.03),
                                  'kp_inner': 15.0, 'ki_inner': 20.0,
                                  'max_step': 20.0})
        st = WristForceV2State()
        f = [5.0 * v for v in _N]
        hist = []
        for _ in range(600):
            trim, fl, _a = wrist_force_v2_step(p, st, f, 0.0, 0.01, tda_solve)
            assert trim is not None and fl == FORCE_OK
            f = [max(0.0, f[i] + 0.0464029 * trim[i]) for i in range(3)]
            hist.append((sum(_R[0][i] * f[i] for i in range(3)),
                         sum(_R[1][i] * f[i] for i in range(3))))
        tail = hist[int(len(hist) * 0.6):]
        rip = (max(v[0] for v in tail) - min(v[0] for v in tail),
               max(v[1] for v in tail) - min(v[1] for v in tail))
        assert rip[0] < 0.005 and rip[1] < 0.005, f"ripple too large: {rip}"
        assert tail[-1][0] == pytest.approx(0.01, abs=0.003)
        assert tail[-1][1] == pytest.approx(0.03, abs=0.003)


class TestPreloadWindow:
    """2026-11-18 A2：可行域改成带 τ 项的通用式（wrist_tda.preload_window）。

    旧实现 `t_min = f_min/min(n̂)`、`t_max = f_max/max(n̂)` 只在 τ=0 时成立；
    接重力补偿后会误判。新函数在 τ=0 时应与旧式**逐位一致**。
    """

    def test_tau_zero_equals_closed_form(self):
        for n in (_N,):
            w = preload_window(_R, n, 0.0, 0.0, 0.5, 30.0)
            assert w is not None
            assert w[0] == pytest.approx(0.5 / min(n), abs=1e-9)
            assert w[1] == pytest.approx(30.0 / max(n), abs=1e-9)

    def test_window_shifts_up_with_torque(self):
        """正 pitch 力矩会吃掉 C1 的余量 → 预紧下界抬高。"""
        w0 = preload_window(_R, _N, 0.0, 0.0, 0.5, 25.0)
        w1 = preload_window(_R, _N, 0.0, 0.10, 0.5, 25.0)
        assert w0 is not None and w1 is not None
        assert w1[0] > w0[0]                 # 下界升（0.1 N·m → 约 7.94 N）
        assert w1[0] == pytest.approx(7.94, abs=0.05)

    def test_none_when_torque_unreachable(self):
        """力矩远超能力 → 区间为空 → None。"""
        assert preload_window(_R, _N, 0.0, 0.5, 0.5, 25.0) is None

    def test_none_without_null(self):
        assert preload_window(_R, None, 0.0, 0.0, 0.5, 25.0) is None
        assert preload_window(_R, (0.5, -0.5, 0.7), 0.0, 0.0, 0.5, 25.0) is None

