"""混合模式自动调参序列（`wrist_hybrid_autotune`）的测试。

覆盖三块：
  1. `command_at` —— 序列时序、目标夹紧、正弦起点不跳变、跑完返回 None
  2. `metrics`    —— 从 CSV 列字典里按 stage 切段、算超调/幅值比
  3. `tune`       —— 高/低超调分别怎么改增益、收敛判定
  4. `_c1_test_override` —— 上位机侧的接线（用 stub，不建 Qt 窗口）
"""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import mmhand_scope as scope
import wrist_hybrid_autotune as ha
from wrist_hybrid_autotune import (KIND_ANGLE_STEP, KIND_C1_SINE, KIND_C1_STEP,
                                   KIND_HOLD)


# ---------------- 1. command_at ----------------

def _at(t, **kw):
    kw.setdefault("c1_base_n", 5.0)
    return ha.command_at(t, **kw)


def test_sequence_covers_all_kinds():
    kinds = {k for _n, k, _d, _p in ha.stages()}
    assert kinds == {KIND_HOLD, KIND_C1_STEP, KIND_C1_SINE, KIND_ANGLE_STEP}
    assert ha.total_seconds() == pytest.approx(sum(s[2] for s in ha.stages()))
    assert ha.stage_count() == len(ha.stages())


def test_first_stage_holds_base():
    idx, name, kind, c1, roll, pitch, local = _at(0.0)
    assert idx == 0 and kind == KIND_HOLD
    assert c1 == pytest.approx(5.0)
    assert (roll, pitch) == (0.0, 0.0)


def test_c1_step_up_and_down():
    # 第 1 档 = 阶跃上
    _i, _n, kind, c1, *_ = _at(ha.HOLD_S + 0.1)
    assert kind == KIND_C1_STEP
    assert c1 == pytest.approx(5.0 + ha.C1_STEP_SPAN_N)
    # 第 2 档 = 阶跃下
    _i, _n, kind, c1, *_ = _at(ha.HOLD_S + ha.C1_STEP_HOLD_S + 0.1)
    assert kind == KIND_C1_STEP
    assert c1 == pytest.approx(5.0 - ha.C1_STEP_SPAN_N)


def test_sine_starts_at_base_without_jump():
    t0 = ha.HOLD_S + 2 * ha.C1_STEP_HOLD_S
    _i, _n, kind, c1, *_ = _at(t0 + 1e-6)
    assert kind == KIND_C1_SINE
    assert c1 == pytest.approx(5.0, abs=1e-3)      # sin(0)=0 → 起点就是基值


def test_sine_reaches_amplitude_at_quarter_period():
    t0 = ha.HOLD_S + 2 * ha.C1_STEP_HOLD_S
    quarter = 0.25 / ha.C1_SINE_FREQS_HZ[0]
    _i, _n, kind, c1, *_ = _at(t0 + quarter)
    assert c1 == pytest.approx(5.0 + ha.C1_SINE_AMP_N, abs=1e-3)


def test_sine_target_is_clamped():
    # 基值贴近上限时，正弦正峰必须被夹住而不是撞界
    _i, _n, kind, c1, *_ = _at(ha.HOLD_S + 2 * ha.C1_STEP_HOLD_S + 1.0,
                               c1_base_n=24.0, c1_max=25.0)
    assert c1 <= 25.0 + 1e-9


def test_angle_step_moves_one_axis_only():
    t_ang = sum(s[2] for s in ha.stages()[:8])     # 前 8 档之后是角度档
    _i, _n, kind, _c1, roll, pitch, _l = _at(t_ang + 0.1)
    assert kind == KIND_ANGLE_STEP
    assert roll == pytest.approx(ha.ANGLE_STEP_DEG)
    assert pitch == pytest.approx(0.0)


def test_angle_target_respects_limit():
    t_ang = sum(s[2] for s in ha.stages()[:8])
    _i, _n, _k, _c1, roll, _p, _l = _at(t_ang + 0.1, angle_limit_deg=3.0)
    assert abs(roll) <= 3.0 + 1e-9


def test_after_end_returns_none():
    idx, _n, _k, c1, roll, pitch, _l = _at(ha.total_seconds() + 1.0)
    assert idx is None and c1 is None
    assert (roll, pitch) == (0.0, 0.0)             # 回落到基准


def test_negative_time_is_treated_as_zero():
    a = _at(-5.0)
    b = _at(0.0)
    assert a[0] == b[0] and a[3] == pytest.approx(b[3])


# ---------------- 2. metrics ----------------

def _mk_rows(dur_s, hz, fn_c1, fn_roll, fn_pitch):
    n = int(dur_s * hz)
    t = [k / hz for k in range(n)]
    return t, [fn_c1(x) for x in t], [fn_roll(x) for x in t], [fn_pitch(x) for x in t]


def test_metrics_step_overshoot():
    """构造一个 40% 超调的阶跃 → metrics 要量出来。"""
    dt = 0.01
    n = 600
    t = [k * dt for k in range(n)]
    tgt = [0.0] * n            # 用相对变化：先 5 后 8
    mea = []
    roll, rp = [], []
    tgt = [8.0] * n
    for k in range(n):
        if k < 100:
            mea.append(5.0)
        else:
            # 峰值 9.2（超调 40% of 3N），然后回到 8.0
            mea.append(9.2 - 1.2 * min(1.0, (k - 100) / 200.0))
        roll.append(0.0)
        rp.append(0.0)
    data = {
        "t_s": t, "roll_deg": roll, "pitch_deg": rp,
        "f1_tgt": tgt, "f2_tgt": [math.nan] * n, "f3_tgt": [math.nan] * n,
        "f1": mea, "f2": [math.nan] * n, "f3": [math.nan] * n,
        "trim1": [0.0] * n, "trim2": [0.0] * n, "trim3": [0.0] * n,
        "roll_tgt_deg": [0.0] * n, "pitch_tgt_deg": [0.0] * n,
        "c1_tgt_n": tgt,
        "stage": ["1"] * n, "kind": ["c1_step"] * n,
    }
    rows = ha.metrics(data)
    assert len(rows) == 1
    assert rows[0]["kind"] == KIND_C1_STEP
    assert rows[0]["c1"]["ok"] is True
    assert rows[0]["c1"]["overshoot"] == pytest.approx(40.0, abs=3.0)


def test_metrics_sine_ratio_and_lag():
    """理想跟随 → 幅值比 ≈1、滞后 ≈0。"""
    hz, f0 = 100.0, 0.1
    n = 2000
    t = [k / hz for k in range(n)]
    v = [5.0 + 3.0 * math.sin(2 * math.pi * f0 * x) for x in t]
    data = {
        "t_s": t, "roll_deg": [0.0] * n, "pitch_deg": [0.0] * n,
        "f1_tgt": v, "f2_tgt": [math.nan] * n, "f3_tgt": [math.nan] * n,
        "f1": v, "f2": [math.nan] * n, "f3": [math.nan] * n,
        "trim1": [0.0] * n, "trim2": [0.0] * n, "trim3": [0.0] * n,
        "roll_tgt_deg": [0.0] * n, "pitch_tgt_deg": [0.0] * n,
        "c1_tgt_n": v,
        "stage": ["3"] * n, "kind": ["c1_sine"] * n,
    }
    rows = ha.metrics(data)
    assert rows and rows[0]["hz"] == pytest.approx(0.1)
    assert rows[0]["c1"]["ratio"] == pytest.approx(1.0, abs=0.02)
    assert abs(rows[0]["c1"]["lag_deg"]) < 3.0


def test_metrics_skips_short_stage():
    data = {"stage": ["0"] * 5, "kind": ["hold"] * 5, "t_s": [0, 0.1, 0.2, 0.3, 0.4]}
    assert ha.metrics(data) == []


# ---------------- 3. tune ----------------

def _gains(kp=10.0, ki=0.0, itl=20.0, kd=0.0, akp=0.2, aki=0.0):
    return {"c1": {"kp": kp, "ki": ki, "itl": itl, "kd": kd},
            "ang": {"kp": akp, "ki": aki}}


def test_tune_lowers_kp_on_big_overshoot():
    rows = [{"stage": 1, "kind": KIND_C1_STEP, "hz": 0.0,
             "c1": {"ok": True, "overshoot": 60.0, "ss_err": 0.0},
             "roll": {}, "pitch": {}},
            {"stage": 3, "kind": KIND_C1_SINE, "hz": 0.3,
             "c1": {"ratio": 0.9, "lag_deg": 10.0}, "roll": {}, "pitch": {}}]
    new, notes, conv = ha.tune(rows, _gains())
    assert new["c1"]["kp"] < 10.0
    assert new["c1"]["kd"] > 0.0          # 超调大 → 加点阻尼
    assert conv is False
    assert any("C1" in n for n in notes)


def test_tune_raises_kp_when_conservative():
    rows = [{"stage": 1, "kind": KIND_C1_STEP, "hz": 0.0,
             "c1": {"ok": True, "overshoot": 5.0, "ss_err": 0.0},
             "roll": {}, "pitch": {}},
            {"stage": 3, "kind": KIND_C1_SINE, "hz": 0.3,
             "c1": {"ratio": 0.5, "lag_deg": 40.0}, "roll": {}, "pitch": {}}]
    new, _n, _c = ha.tune(rows, _gains())
    assert new["c1"]["kp"] > 10.0


def test_tune_respects_bounds():
    rows = [{"stage": 1, "kind": KIND_C1_STEP, "hz": 0.0,
             "c1": {"ok": True, "overshoot": 500.0, "ss_err": 40.0},
             "roll": {}, "pitch": {}}]
    new, _n, _c = ha.tune(rows, _gains(kp=3.0, itl=5.0))
    assert new["c1"]["kp"] >= ha.C1_BOUNDS["kp"][0]
    assert new["c1"]["itl"] >= ha.C1_BOUNDS["itl"][0]
    assert new["c1"]["kd"] <= ha.C1_BOUNDS["kd"][1]


def test_tune_angle_kp_reacts_to_angle_overshoot():
    rows = [{"stage": 8, "kind": KIND_ANGLE_STEP, "hz": 0.0, "c1": {},
             "roll": {"ok": True, "overshoot": 70.0, "ss_err": 0.0},
             "pitch": {"ok": True, "overshoot": 60.0, "ss_err": 12.0}}]
    new, _n, _c = ha.tune(rows, _gains())
    assert new["ang"]["kp"] < 0.2
    assert new["ang"]["ki"] > 0.0


# ---------------- 4. 上位机接线（stub，不建 Qt 窗口）----------------

class _FakeCheck:
    def __init__(self, on=False):
        self._on = on

    def isChecked(self):
        return self._on


class _StubWin:
    MIX_STAGE_MANUAL = -1
    MIX_STAGE_DONE = -2

    def __init__(self, auto=False, sine=False):
        self.cl_c1_auto_check = _FakeCheck(auto)
        self.cl_c1_sine_check = _FakeCheck(sine)
        self._auto_t0_pc = None
        self._auto_stage = -1
        self._auto_kind = ""
        self._sine_t0 = 0.0
        self.edits = {"c1_pos_min_n": "0.2", "c1_pos_max_n": "25",
                      "pos_limit": "25", "sine_amp": "3", "sine_hz": "0.25",
                      "sine_phase": "0"}
        self._c1_pos = None

    # 复刻真实方法
    _c1_fval = scope.ScopeWindow._c1_fval
    _c1_test_override = scope.ScopeWindow._c1_test_override

    def _cl_fval(self, key, default, lo, hi):
        try:
            return float(self.edits.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _cl_fval3(self, key, default, lo, hi):
        return [1.0, 1.0, 1.0]

    def _c1_position_edits_get(self, key):
        return self.edits[key]


class _FakeEdit:
    def __init__(self, text):
        self._t = text

    def text(self):
        return self._t


class _StubWin2(_StubWin):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._c1_position_edits = {k: _FakeEdit(v) for k, v in self.edits.items()}


def test_override_off_returns_params_unchanged():
    from wrist_hybrid_control import C1TensionParams, HybridWristParams
    from wrist_control_law import WristControlParams
    w = _StubWin2(auto=False, sine=False)
    p = HybridWristParams(WristControlParams(), 5.0, -10.0,
                          C1TensionParams(5.0, 5.0, 0.0, 0.0, 0.0, 5, 3000, 5, 0.2, 25))
    p2, stage, kind, note, done = w._c1_test_override(p)
    assert p2 is p and stage == -1 and not done and note == ""


def test_override_sine_starts_at_base():
    from wrist_hybrid_control import C1TensionParams, HybridWristParams
    from wrist_control_law import WristControlParams
    w = _StubWin2(auto=False, sine=True)
    p = HybridWristParams(WristControlParams(), 5.0, -10.0,
                          C1TensionParams(5.0, 5.0, 0.0, 0.0, 0.0, 5, 3000, 5, 0.2, 25))
    import time as _t
    w._sine_t0 = _t.monotonic()          # 让 t≈0
    p2, stage, kind, note, done = w._c1_test_override(p)
    assert kind == "sine" and not done
    assert p2.c1.target_n == pytest.approx(5.0, abs=0.05)
    assert p2.roll_target_deg == 5.0 and p2.pitch_target_deg == -10.0


def test_override_auto_hold_stage_keeps_targets():
    from wrist_hybrid_control import C1TensionParams, HybridWristParams
    from wrist_control_law import WristControlParams
    w = _StubWin2(auto=True)
    p = HybridWristParams(WristControlParams(), 5.0, -10.0,
                          C1TensionParams(5.0, 5.0, 0.0, 0.0, 0.0, 5, 3000, 5, 0.2, 25))
    p2, stage, kind, note, done = w._c1_test_override(p)
    assert stage == 0 and kind == "hold" and not done
    assert p2.c1.target_n == pytest.approx(5.0)
