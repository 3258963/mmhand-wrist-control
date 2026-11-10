"""wrist_tension_step（张力模式）+ wrist_tight_step（张紧模式）联合测试。"""
import math
import pytest

from wrist_force_law import (FORCE_OK, FORCE_OVERLOAD, FORCE_STALE,
                              FORCE_NO_NULL,
                              WristTensionParams, WristTensionState,
                              WristTightParams, WristTightState,
                              wrist_tension_step, wrist_tight_step)
from wrist_model import wrist_eval, positive_null_direction

_out = wrist_eval(0.0, 0.0)
_R = _out.r_m
_N = positive_null_direction(0.0, 0.0)
assert _N is not None

T_BASE = dict(f_target=(2.0, 2.0, 2.0), kp=10.0, ki=5.0,
              trim_sign=(1.0, 1.0, 1.0), max_trim=3000.0,
              f_max=30.0, deadband=0.05)
G_BASE = dict(t_target=5.0, kp=50.0, ki=10.0,
              trim_sign=(1.0, 1.0, 1.0), max_trim=3000.0,
              f_max=30.0, deadband=0.05, null_dir=_N)


class TestTensionMode:
    def test_hold_at_target(self):
        p = WristTensionParams(**T_BASE)
        st = WristTensionState()
        trim, fl = wrist_tension_step(p, st, (2.0, 2.0, 2.0), 10.0, 0.01)
        assert trim is not None and fl == FORCE_OK
        assert all(abs(t) < 0.5 for t in trim)          # 误差在死区内→trim≈0

    def test_error_direction(self):
        p = WristTensionParams(**T_BASE)
        trim, fl = wrist_tension_step(p, WristTensionState(),
                                      (1.0, 2.0, 3.0), 10.0, 0.01)
        assert fl == FORCE_OK
        assert trim[0] > 0 and trim[1] == pytest.approx(0, abs=0.5) and trim[2] < 0

    def test_sign_flip(self):
        p_pos = WristTensionParams(**T_BASE)
        p_neg = WristTensionParams(**{**T_BASE, 'trim_sign': (-1.0, 1.0, -1.0)})
        t_pos, _ = wrist_tension_step(p_pos, WristTensionState(),
                                      (1.0, 2.0, 3.0), 10.0, 0.01)
        t_neg, _ = wrist_tension_step(p_neg, WristTensionState(),
                                      (1.0, 2.0, 3.0), 10.0, 0.01)
        assert t_neg[0] == -t_pos[0] and t_neg[1] == t_pos[1] and t_neg[2] == -t_pos[2]

    def test_params_validation(self):
        with pytest.raises(ValueError):
            WristTensionParams(**{**T_BASE, 'f_target': (2.0, 2.0)})
        with pytest.raises(ValueError):
            WristTensionParams(**{**T_BASE, 'trim_sign': (0, 1, 1)})
        with pytest.raises(ValueError):
            WristTensionParams(**{**T_BASE, 'kp': -1.0})
        with pytest.raises(ValueError):
            WristTensionParams(**{**T_BASE, 'max_step': 0.0})

    def test_step_capped_by_max_step(self):
        """增益巨大时每拍步长被 max_step 封顶（限速语义）。"""
        p = WristTensionParams(**{**T_BASE, 'kp': 10000.0, 'ki': 0.0,
                                   'max_step': 3.0})
        st = WristTensionState()
        for _ in range(50):
            trim, fl = wrist_tension_step(p, st, (0.0, 2.0, 2.0), 10.0, 0.01)
            assert trim is not None and abs(trim[0]) <= 3

    def test_resid_carry_exact(self):
        """小数步长靠残差进位不丢：du=0.4c/拍 × 10 拍 → Σstep=4（精确）。"""
        p = WristTensionParams(**{**T_BASE, 'kp': 0.4, 'ki': 0.0})
        st = WristTensionState()
        total = 0
        for _ in range(10):
            trim, fl = wrist_tension_step(p, st, (1.0, 2.0, 2.0), 10.0, 0.01)
            total += trim[0]                # e=1N 恒定 → du=0.4c/拍
        assert total == 4, total

    def test_stale_and_overload(self):
        p = WristTensionParams(**T_BASE)
        st = WristTensionState()
        trim, fl = wrist_tension_step(p, st, (2.0, 2.0, 2.0), 350.0, 0.01)
        assert trim is None and fl == FORCE_STALE
        trim, fl = wrist_tension_step(p, st, (2.0, 2.0, 40.0), 10.0, 0.01)
        assert trim is None and fl == FORCE_OVERLOAD

    def test_negative_clamped(self):
        p = WristTensionParams(**T_BASE)
        trim, fl = wrist_tension_step(p, WristTensionState(),
                                      (-1.0, 2.0, 2.0), 10.0, 0.01)
        assert trim is not None and fl == FORCE_OK     # 钳0继续控，不再冻结

    def test_convergence_sim(self):
        """一阶张力植物 + 逐缆 PI → 收敛到目标。"""
        p = WristTensionParams(**{**T_BASE, 'kp': 200.0, 'ki': 40.0,
                                   'f_target': (3.0, 1.5, 2.5)})
        st = WristTensionState()
        f = [2.0, 2.0, 2.0]
        for _ in range(800):
            trim, fl = wrist_tension_step(p, st, f, 10.0, 0.01)
            assert trim is not None
            for i in range(3):
                f[i] = max(0.0, f[i] + p.trim_sign[i] * trim[i] * 0.001)
        for i in range(3):
            assert abs(f[i] - p.f_target[i]) < 0.1, (i, f[i])


class TestTightMode:
    def test_hold_at_target(self):
        """t_meas 已等于 t_target → trim≈0。"""
        p = WristTightParams(**G_BASE)
        st = WristTightState()
        f0 = [5.0 * v for v in _N]                     # f = t·n̂ → t_meas=5
        trim, fl = wrist_tight_step(p, st, f0, 10.0, 0.01)
        assert trim is not None and fl == FORCE_OK
        assert all(abs(t) < 0.5 for t in trim)

    def test_no_null_rejected(self):
        p = WristTightParams(**{**G_BASE, 'null_dir': None})
        trim, fl = wrist_tight_step(p, WristTightState(),
                                    (3.0, 3.0, 3.0), 10.0, 0.01)
        assert trim is None and fl == FORCE_NO_NULL

    def test_torque_invariance(self):
        """性质测试：步长 du∝n̂ ⇒ R·Δf≈0（力矩守恒）——100 随机位姿。

        增量式输出是整数步长：round 引入 ≤0.5c/缆 的分配偏差 →
        τ 守恒精确到 ~2e-7 N·m（物理可忽略），容差相应放宽。"""
        import random
        random.seed(11)
        for _ in range(100):
            r = math.radians(random.uniform(-25, 25))
            pt = math.radians(random.uniform(-25, 45))
            out = wrist_eval(r, pt)
            n = positive_null_direction(r, pt)
            if n is None or not out.math_valid:
                continue
            p = WristTightParams(**{**G_BASE, 'null_dir': n, 't_target': 8.0})
            f0 = [3.0, 3.0, 3.0]
            trim, fl = wrist_tight_step(p, WristTightState(), f0, 10.0, 0.01)
            assert trim is not None and fl == FORCE_OK
            df = [trim[i] / 130380.0 for i in range(3)]   # counts→m 假想换算
            d_tau = [sum(out.r_m[a][i] * df[i] for i in range(3)) for a in (0, 1)]
            assert abs(d_tau[0]) < 1e-5 and abs(d_tau[1]) < 1e-5, d_tau

    def test_tighten_direction(self):
        """欠预紧 → err>0 → 各缆张力齐升、t_meas 收敛到目标。

        教训重演（"仿真不收敛先查测试自己的假设"）：植物=纯积分器时
        kp=0 的纯 I 环是无阻尼双积分器必振荡——P 项提供阻尼（ζ=0.5）
        后收敛。真实系统另有舵机内环+缆阻尼。"""
        p = WristTightParams(**{**G_BASE, 't_target': 8.0, 'kp': 200.0, 'ki': 40.0})
        st = WristTightState()
        f0 = [3.0, 3.0, 3.0]
        f = list(f0)
        for _ in range(800):
            trim, fl = wrist_tight_step(p, st, f, 10.0, 0.01)
            assert trim is not None
            for i in range(3):
                f[i] = max(0.0, f[i] + p.trim_sign[i] * trim[i] * 0.001)
        t_meas = sum(f[i] * _N[i] for i in range(3))
        assert abs(t_meas - 8.0) < 0.3, t_meas            # 收敛到目标预紧
        # 且逐缆张力全升（n̂ 全正 + 植物同号）
        assert all(f[i] > f0[i] for i in range(3))

    def test_stale_and_overload(self):
        p = WristTightParams(**G_BASE)
        trim, fl = wrist_tight_step(p, WristTightState(),
                                    (3.0, 3.0, 3.0), 350.0, 0.01)
        assert trim is None and fl == FORCE_STALE
        trim, fl = wrist_tight_step(p, WristTightState(),
                                    (3.0, 3.0, 40.0), 10.0, 0.01)
        assert trim is None and fl == FORCE_OVERLOAD

    def test_params_validation(self):
        with pytest.raises(ValueError):
            WristTightParams(**{**G_BASE, 't_target': -1.0})
        with pytest.raises(ValueError):
            WristTightParams(**{**G_BASE, 'trim_sign': (1, 1, 2)})
        with pytest.raises(ValueError):
            WristTightParams(**{**G_BASE, 'max_step': -1.0})

    def test_step_capped_by_max_step(self):
        """张紧模式同款限速语义：步长 ≤ max_step。"""
        p = WristTightParams(**{**G_BASE, 'kp': 10000.0, 'ki': 0.0,
                                 'max_step': 2.0})
        st = WristTightState()
        for _ in range(50):
            trim, fl = wrist_tight_step(p, st, (0.0, 0.0, 0.0), 10.0, 0.01)
            assert trim is not None and all(abs(t) <= 2 for t in trim)


class TestTightFloor:
    """方向地板（v8.2 D4 / v8.3 裁定）：统一不变式 f_i终 ≥ min(f_i起, fmin) − ε。

    期望全部用不变式断言；括号里的终态数值是 ki=10/kp=50/max_step=5/
    植物 0.002N/c 的仿真参考（windup 依赖，勿作 golden）。t=0.2/0.5/1.0
    为纯律行为、UI 不可达（_tight_params 拒 t < fmin_eff/min(n̂)≈1.89）。
    """

    FLOOR = 0.5

    def _sim(self, tgt, ki, f0, ticks=40000, sign=(1, 1, 1)):
        n = positive_null_direction(0.0, 0.0)
        p = WristTightParams(tgt, 50, ki, sign, 3000, 30, 0.05,
                             tuple(n), max_step=5, f_min=self.FLOOR)
        st = WristTightState()
        f = list(f0)
        plant, last = 0.002, [0, 0, 0]
        for _ in range(ticks):
            trim, fl = wrist_tight_step(p, st, f, 10.0, 0.01)
            if trim is None:
                break
            last = trim
            for i in range(3):
                f[i] = max(0.0, f[i] + sign[i] * trim[i] * plant)
        return p, st, f, last

    def _assert_invariants(self, f0, f, t_meas, tgt, p, last):
        for i in range(3):   # ① 统一不变式（v8.3：从地板两行直接可证）
            assert f[i] >= min(f0[i], self.FLOOR) - 0.02, (i, f)
        assert all(v <= p.f_max for v in f)              # ② 无过载
        conv = abs(t_meas - tgt) <= p.deadband + 0.1     # ③ 收敛或驻停
        stalled = all(v == 0 for v in last)
        assert conv or stalled, (t_meas, tgt, last)

    def test_floor_low_target_0_2_stall(self):
        """参考终态 (0.50,0.49,0.00) t≈0.42：目标低于可达底→驻停。"""
        p, st, f, last = self._sim(0.2, 10, (10.0, 3.0, 0.0))
        t_meas = sum(f[i] * p.null_dir[i] for i in range(3))
        self._assert_invariants((10, 3, 0), f, t_meas, 0.2, p, last)
        assert all(v == 0 for v in last)

    def test_floor_low_target_0_5(self):
        """参考终态 (0.50,0.55,0.10)：C3 允许 <fmin（起始即低，地板不抬）。"""
        p, st, f, last = self._sim(0.5, 10, (10.0, 3.0, 0.0))
        t_meas = sum(f[i] * p.null_dir[i] for i in range(3))
        self._assert_invariants((10, 3, 0), f, t_meas, 0.5, p, last)

    def test_floor_target_1_0(self):
        """参考终态 (0.50,0.75,0.50)：windup 过冲把 C1/C3 砸到地板再回程。"""
        p, st, f, last = self._sim(1.0, 10, (10.0, 3.0, 0.0))
        t_meas = sum(f[i] * p.null_dir[i] for i in range(3))
        self._assert_invariants((10, 3, 0), f, t_meas, 1.0, p, last)

    def test_floor_high_target_3_0_two_gains(self):
        """ki=10 参考 (0.50,0.50,3.40)；ki=0 参考 (8.51,1.34,0.00)——
        同一不变式两者都必须过（钉死 v8.2 的 t 分域错误：目标值≠保证来源）。"""
        for ki in (10, 0):
            p, st, f, last = self._sim(3.0, ki, (10.0, 3.0, 0.0))
            t_meas = sum(f[i] * p.null_dir[i] for i in range(3))
            self._assert_invariants((10, 3, 0), f, t_meas, 3.0, p, last)

    def test_floor_neg_sign_block_release_not_tighten(self):
        """sign=(-1,1,1)、C1=0.4 贴地板、t=8：地板禁放不禁紧。"""
        p, st, f, last = self._sim(8.0, 10, (0.4, 3.0, 3.0), sign=(-1, 1, 1))
        assert f[0] > 0.4
        t_meas = sum(f[i] * p.null_dir[i] for i in range(3))
        self._assert_invariants((0.4, 3, 3), f, t_meas, 8.0, p, last)

    def test_floor_disabled_when_fmin_zero(self):
        """f_min=0（默认）= 地板禁用：不因新参数改变旧律行为。"""
        n = positive_null_direction(0.0, 0.0)
        p = WristTightParams(1.0, 50, 10, (1, 1, 1), 3000, 30, 0.05,
                             tuple(n), max_step=5, f_min=0.0)
        st = WristTightState()
        f = [10.0, 3.0, 0.0]
        for _ in range(200):
            trim, fl = wrist_tight_step(p, st, f, 10.0, 0.01)
            for i in range(3):
                f[i] = max(0.0, f[i] + trim[i] * 0.002)
        assert sum(f[i] * n[i] for i in range(3)) < 4.0   # 放行未受阻

    def test_fmin_validation(self):
        n = positive_null_direction(0.0, 0.0)
        base = dict(kp=50, ki=10, trim_sign=(1, 1, 1), max_trim=3000,
                    f_max=30, deadband=0.05, null_dir=tuple(n))
        WristTightParams(3.0, f_min=0.5, **base)
        WristTightParams(3.0, f_min=0.0, **base)
        with pytest.raises(ValueError):
            WristTightParams(3.0, f_min=30.0, **base)     # ≥f_max 非法
        with pytest.raises(ValueError):
            WristTightParams(3.0, f_min=-0.1, **base)     # 负值非法
