"""逐缆参数解析与逐缆增益执行 —— `parse_per_cable` / `_per_cable`。

背景（2026-11-24 用户要求）：三根绳的摩擦、绳长、预紧、导管弯折都不同，
一套 `kp/ki/i_term_lim/max_step` 不可能同时最优。现场症状很典型：
**C1 在大幅摆动，C2 却一直爬不上去**（同一组增益，一根过冲一根迟钝）。

界面做法（不新开 9 个框）：同一个框支持两种填法

    "15"       → [15, 15, 15]     三缆共用（旧行为，完全兼容）
    "15,15,8"  → [15, 15, 8]      C1/C2=15、C3=8

解析失败**必须返回 None**（由调用方拒绝开环）：宁可不开，也不能拿错增益
去驱动电机。
"""

import pytest

from wrist_force_law import (_per_cable, parse_per_cable,
                             WristTensionParams, wrist_tension_step,
                             IncrPiState)


# ---------------- 解析 ----------------

def test_single_value_broadcasts():
    assert parse_per_cable("15", 0.0, 0.0, 1e9) == [15.0, 15.0, 15.0]


def test_three_values_kept():
    assert parse_per_cable("15,15,8", 0.0, 0.0, 1e9) == [15.0, 15.0, 8.0]


def test_spaces_and_fullwidth_comma():
    assert parse_per_cable(" 1 , 2 ，3 ", 0.0, 0.0, 1e9) == [1.0, 2.0, 3.0]


def test_empty_uses_default():
    assert parse_per_cable("", 7.0, 0.0, 1e9) == [7.0, 7.0, 7.0]
    assert parse_per_cable(None, (1.0, 2.0, 3.0), 0.0, 1e9) == [1.0, 2.0, 3.0]


def test_two_values_rejected():
    assert parse_per_cable("15,8", 0.0, 0.0, 1e9) is None


def test_four_values_rejected():
    assert parse_per_cable("1,2,3,4", 0.0, 0.0, 1e9) is None


def test_non_numeric_rejected():
    assert parse_per_cable("15,abc,8", 0.0, 0.0, 1e9) is None


def test_out_of_range_rejected():
    assert parse_per_cable("15,-1,8", 0.0, 0.0, 1e9) is None
    assert parse_per_cable("15,15,1e9", 0.0, 0.0, 100.0) is None


def test_negative_default_allowed_when_range_permits():
    assert parse_per_cable("", -0.5, -10.0, 10.0) == [-0.5, -0.5, -0.5]


def test_degenerate_lo_hi_accepts_single_point():
    assert parse_per_cable("0", 0.0, 0.0, 0.0) == [0.0, 0.0, 0.0]


# ---------------- 取值 ----------------

def test_per_cable_prefers_list():
    assert _per_cable([1.0, 2.0, 3.0], 9.0, 1) == 2.0


def test_per_cable_falls_back_to_scalar():
    assert _per_cable(None, 9.0, 2) == 9.0


def test_per_cable_bad_list_falls_back():
    assert _per_cable([1.0], 9.0, 2) == 9.0


# ---------------- 逐缆实际生效（行为测试） ----------------

def _params(**kw):
    base = dict(f_target=(5.0, 5.0, 5.0), kp=10.0, ki=0.0, trim_sign=(1, 1, 1),
                max_trim=100000.0, f_max=30.0, deadband=0.0, max_step=100.0,
                i_term_lim=100.0)
    base.update(kw)
    return WristTensionParams(**base)


def test_per_cable_kp_changes_step_proportionally():
    """同误差下，C3 用一半 Kp → 步长约为 C1 的一半（四舍五入前）。"""
    p = _params(kp=10.0, ki=0.0, kp3=[10.0, 10.0, 5.0])
    st = IncrPiState()
    trim, _fl = wrist_tension_step(p, st, [3.0, 3.0, 3.0], 0.0, 0.01)
    # 误差 2 N：C1/C2 → 20 counts，C3 → 10 counts
    assert trim == [20.0, 20.0, 10.0]


def test_per_cable_max_step_clamps_each_cable():
    """逐缆 `max_step` 只夹对应那根，不影响其它缆。"""
    p = _params(kp=10.0, ki=0.0, max_step=100.0, max_step3=[100.0, 3.0, 100.0])
    st = IncrPiState()
    trim, _fl = wrist_tension_step(p, st, [3.0, 3.0, 3.0], 0.0, 0.01)
    assert trim == [20.0, 3.0, 20.0]


def test_without_per_cable_keeps_old_behavior():
    """不给逐缆字段 → 三缆同一步长（与改动前逐位一致）。"""
    p = _params(kp=10.0, ki=0.0)
    st = IncrPiState()
    trim, _fl = wrist_tension_step(p, st, [3.0, 3.0, 3.0], 0.0, 0.01)
    assert trim[0] == trim[1] == trim[2]


def test_trim_sign_still_applies_per_cable():
    """逐缆增益与逐缆符号叠加：C2 反向 → 步长取负。"""
    p = _params(kp=10.0, ki=0.0, trim_sign=(1, -1, 1))
    st = IncrPiState()
    trim, _fl = wrist_tension_step(p, st, [3.0, 3.0, 3.0], 0.0, 0.01)
    assert trim[1] == -trim[0]


def test_bad_per_cable_length_rejected():
    with pytest.raises(ValueError):
        _params(kp3=[1.0, 2.0])


def test_bad_per_cable_value_rejected():
    with pytest.raises(ValueError):
        _params(ki3=[1.0, -2.0, 3.0])


def test_slots_clone_keeps_per_cable_fields():
    """回归：**只换目标**时必须按 `__slots__` 全量拷贝。

    2026-11-24 现场事故：正弦跟随每拍换目标，手写
    `WristTensionParams(f_target=..., kp=p.kp, ...)` 漏掉了逐缆字段 →
    三缆全部退回标量（= 逐缆列表的第一个值），表现为
    "一开正弦，三根缆都只看第一个参数"。
    这里锁住"按 slots 拷贝就能保全"这个前提。
    """
    p = _params(kp3=[10.0, 10.0, 4.0], ki3=[1.0, 2.0, 3.0],
                max_step3=[200.0, 200.0, 50.0], i_term_lim3=[25.0, 26.0, 27.0])
    clone = WristTensionParams.__new__(WristTensionParams)
    for name in WristTensionParams.__slots__:
        setattr(clone, name, getattr(p, name, None))
    clone.f_target = [1.0, 2.0, 3.0]
    assert clone.kp3 == [10.0, 10.0, 4.0]
    assert clone.ki3 == [1.0, 2.0, 3.0]
    assert clone.max_step3 == [200.0, 200.0, 50.0]
    assert clone.i_term_lim3 == [25.0, 26.0, 27.0]
    assert clone.f_target == [1.0, 2.0, 3.0]
    # 原对象不被改
    assert p.f_target == [5.0, 5.0, 5.0]


def test_clone_still_drives_per_cable():
    """克隆后行为不变：C3 的步长仍按它自己的 Kp 算。"""
    p = _params(kp3=[10.0, 10.0, 4.0], ki3=[0.0, 0.0, 0.0])
    clone = WristTensionParams.__new__(WristTensionParams)
    for name in WristTensionParams.__slots__:
        setattr(clone, name, getattr(p, name, None))
    clone.f_target = [3.0, 3.0, 3.0]
    st = IncrPiState()
    trim, _fl = wrist_tension_step(clone, st, [1.0, 1.0, 1.0], 0.0, 0.01)
    assert trim == [20.0, 20.0, 8.0]        # 误差 2 N × [10,10,4]
