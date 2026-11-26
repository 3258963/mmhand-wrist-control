"""张力环（`wrist_tension_step`）与张紧新结构的联合测试。

2026-11-19 清理：老张紧律 `wrist_tight_step` / `WristTightState` 已从生产路径退役
（张紧改为「逐缆绝对目标 f_d = t*·n̂ + 同一个张力环」），对应测试一并删除；
只保留 `WristTightParams` 的校验用例（该参数类仍在用）。
"""
import math
import pytest

from wrist_force_law import (FORCE_OK, FORCE_OVERLOAD, FORCE_STALE, STALE_MS,
                              WristTensionParams, WristTensionState,
                              WristTightParams,
                              wrist_tension_step)
from wrist_model import wrist_eval, positive_null_direction

_out = wrist_eval(0.0, 0.0)
_R = _out.r_m
_N = positive_null_direction(0.0, 0.0)
assert _N is not None

T_BASE = dict(f_target=(2.0, 2.0, 2.0), kp=10.0, ki=5.0,
              trim_sign=(1.0, 1.0, 1.0), max_trim=3000.0,
              f_max=30.0, deadband=0.05)


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
        trim, fl = wrist_tension_step(p, st, (2.0, 2.0, 2.0), STALE_MS + 50.0, 0.01)
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


class TestTightParamsValidation:
    """`WristTightParams` 仍在生产路径（张紧模式的参数容器），保留校验用例。"""

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


class TestTightAsPerCableTargets:
    """2026-11-17 新结构：张紧 = f_d = t*·n̂ + 三缆各自 PID（复用张力环）。

    旧结构（合成 1 个标量 t 再按 n̂ 分配）反馈秩只有 1，n̂_i 小的绳看不见；
    新结构每缆有绝对目标 → 误差 3 维 → 可观测。
    """

    def test_fd_preload_and_zero_torque(self):
        n = _N
        fd = [5.0 * v for v in n]
        # 预紧仍为 t*：n̂·f_d = 5
        assert sum(fd[i] * n[i] for i in range(3)) == pytest.approx(5.0, abs=1e-9)
        # 目标分布零力矩：R·f_d = 0
        for row in (_R[0], _R[1]):
            assert abs(sum(row[i] * fd[i] for i in range(3))) < 1e-12

    def test_c3_error_is_seen(self):
        """(−18,0)：n̂₃=0.017，C3 比目标紧 2.8 N。

        旧结构：被 n̂₃ 压成 0.045 N < 死区 → 一动不动（盲区）。
        新结构：这就是 C3 自己的 2.8 N 误差 → 50 拍内纠回 0.1 N 以内。
        """
        n = positive_null_direction(math.radians(-18.0), 0.0)
        assert n is not None
        assert n[2] < 0.05                       # 该位姿 C3 权重极小
        fd = [5.0 * v for v in n]
        p = WristTensionParams(f_target=tuple(fd), kp=10.0, ki=20.0,
                               trim_sign=(1.0, 1.0, 1.0), max_trim=5000.0,
                               max_step=20.0, f_max=25.0, deadband=0.05)
        st = WristTensionState()
        f = [fd[0], fd[1], fd[2] + 2.8]
        for _ in range(50):
            trim, fl = wrist_tension_step(p, st, tuple(f), 0.0, 0.01)
            assert trim is not None and fl == FORCE_OK
            f = [max(0.0, f[i] + 0.0464029 * trim[i]) for i in range(3)]
        assert f[2] == pytest.approx(fd[2], abs=0.1)
