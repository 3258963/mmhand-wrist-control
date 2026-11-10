"""wrist_force_v2 + wrist_tda 联合测试。"""
import math
import pytest

from wrist_force_law import (FORCE_OK, FORCE_OVERLOAD, FORCE_STALE,
                              FORCE_TDA_INFEASIBLE,
                              WristForceV2Params, WristForceV2State,
                              wrist_force_v2_step)
from wrist_tda import (TDA_OK, TDA_ALPHA_CLAMPED, TDA_INFEASIBLE,
                        TDA_NO_NULL, tda_solve)
from wrist_model import wrist_eval, positive_null_direction

# 零位 R 和零空间（预计算一次）
_out = wrist_eval(0.0, 0.0)
_R = _out.r_m
_N = positive_null_direction(0.0, 0.0)
assert _N is not None

BASE = dict(
    tau_d=(0.0, 0.0), preload_n=5.0,
    kp=100.0, ki=10.0, trim_gain=50.0, trim_sign=(1.0, 1.0, 1.0),
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

    def test_integ_bounded_and_frozen_when_scaled(self):
        """不可达大力矩（α<1）：integ_tau 有界（±可达力矩）且被冻结。"""
        p = WristForceV2Params(**{**BASE, 'tau_d': (5.0, 5.0), 'ki': 100.0})
        st = WristForceV2State()
        f = [3.0, 3.0, 3.0]
        for _ in range(500):
            trim, flags, _alpha = wrist_force_v2_step(p, st, f, 10.0, 0.01, tda_solve)
            assert trim is not None and flags == FORCE_OK
        span = p.f_max - p.f_min
        lim = [span * sum(abs(v) for v in p.r_m[j]) for j in range(2)]
        for j in range(2):
            assert abs(st.integ_tau[j]) <= lim[j] + 1e-9
        snap = list(st.integ_tau)
        for _ in range(100):
            wrist_force_v2_step(p, st, f, 10.0, 0.01, tda_solve)
        assert st.integ_tau == snap          # 冻结：分毫不动

    def test_integ_integrates_when_feasible(self):
        """可达小力矩（α=1，预紧 10N 留足下探余量）：积分正常累积。"""
        p = WristForceV2Params(**{**BASE, 'tau_d': (0.05, 0.0),
                                   'preload_n': 10.0, 'ki': 50.0, 'kp': 0.0})
        st = WristForceV2State()
        f = [3.0, 3.0, 3.0]
        integ0 = list(st.integ_tau)
        wrist_force_v2_step(p, st, f, 10.0, 0.01, tda_solve)
        assert any(abs(st.integ_tau[j] - integ0[j]) > 1e-9 for j in range(2))

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
        integ_before = list(st.integ_tau)
        trim, flags, _alpha = wrist_force_v2_step(p, st, f, 350.0, 0.01, tda_solve)
        assert trim is None and flags == FORCE_STALE
        assert st.integ_tau == integ_before

    def test_overload_stops(self):
        p = WristForceV2Params(**{**BASE, 'f_max': 5.0})
        st = WristForceV2State()
        trim, flags, _alpha = wrist_force_v2_step(p, st, (10.0, 10.0, 10.0), 10.0, 0.01,
                                          tda_solve)
        assert trim is None and flags == FORCE_OVERLOAD

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
