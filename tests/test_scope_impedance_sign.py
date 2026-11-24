"""阻抗外环 roll 输出取反（2026-11-23 台架方向修正）的接线测试。

只验证一件事：`_cl_tick_impedance` 把 `wrist_impedance_torque` 返回的 roll
乘 `IMPEDANCE_ROLL_SIGN`（=−1）后再交给力矩链；pitch 原样。

不建 Qt 窗口：用 `ScopeWindow.__new__` 之外的纯 stub 调未绑定方法。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import mmhand_scope as scope


class _Stub:
    """只提供 `_cl_tick_impedance` 用到的成员，不碰 Qt。"""

    def __init__(self):
        self._imp_tau = None
        self._imp_flags = None
        self._imp_ff = None
        self.force_calls = []

    def _impedance_params(self, roll, pitch):
        return SimpleNamespace(tau_ff=(0.0, 0.0))

    def _cl_fval(self, key, default, lo, hi):
        return 0.0

    def _stop_closed_loop(self, reason):        # 不该走到这里
        raise AssertionError(f"不应停环：{reason}")

    def _cl_tick_force(self, roll, pitch):
        self.force_calls.append((roll, pitch))


def test_impedance_roll_output_is_negated(monkeypatch):
    monkeypatch.setattr(scope, "wrist_impedance_torque",
                        lambda *a, **k: (0.10, 0.20, scope.IMP_OK))
    d = _Stub()
    scope.ScopeWindow._cl_tick_impedance(d, 1.0, -2.0)
    assert d._imp_tau == (-0.10, 0.20), d._imp_tau
    assert d.force_calls == [(1.0, -2.0)]


def test_impedance_roll_sign_constant():
    assert scope.IMPEDANCE_ROLL_SIGN == -1.0


def test_impedance_no_target_still_stops(monkeypatch):
    """NaN 路径不能被取反掩盖：仍然停环、不调力矩链。"""
    monkeypatch.setattr(scope, "wrist_impedance_torque",
                        lambda *a, **k: (float("nan"), float("nan"), scope.IMP_NO_TARGET))
    d = _Stub()
    stopped = []
    d._stop_closed_loop = lambda reason: stopped.append(reason)
    scope.ScopeWindow._cl_tick_impedance(d, 0.0, 0.0)
    assert stopped and "非有限" in stopped[0]
    assert d.force_calls == []
