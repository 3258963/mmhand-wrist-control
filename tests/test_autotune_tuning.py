"""自动迭代调参的**决策规则** —— `wrist_autotune.tune`。

2026-11-25 用户要求：「你每一次改完自动运行帮我调参」。
做法：每轮 110 s 跑完 → 用本轮 CSV 算指标 → 按规则改增益 → 立刻再跑一轮，
直到轮数用完或收敛。这里锁住规则本身（纯函数，不碰硬件）。

规则（每缆独立）：
    超调 >50%          → kp×0.80, kd+0.04
    超调 30~50%        → kp×0.88, kd+0.02
    超调 <12% 且 r(0.3)<0.92（且不封顶）→ kp×1.10
    稳态差 >6%         → i_term_lim×1.4（>10% 再 ki×1.15）
    稳态差 <2% 且 itl>25 → itl×0.9（别一直占着大权限）
    已有 kd 且超调<12% 且 r(0.5)<0.85 → kd×1.1
"""

import pytest

import wrist_autotune as at


def _mk(os_up=0.0, os_dn=0.0, ss=0.0, r03=1.0, r05=1.0):
    """造一份两档阶跃 + 0.3/0.5 Hz 正弦的指标（三缆同值）。"""
    def cab(v):
        return [{"cable": i + 1, **v} for i in range(3)]
    return [
        {"stage": 1, "kind": "step", "hz": 0.0,
         "cables": cab({"overshoot": os_up, "ss_err": ss, "ok": True})},
        {"stage": 2, "kind": "step", "hz": 0.0,
         "cables": cab({"overshoot": os_dn, "ss_err": -ss, "ok": True})},
        {"stage": 6, "kind": "sine", "hz": 0.3,
         "cables": cab({"ratio": r03, "lag_deg": 30.0})},
        {"stage": 8, "kind": "sine", "hz": 0.5,
         "cables": cab({"ratio": r05, "lag_deg": 55.0})},
    ]


def _g(kp=15.0, ki=15.0, itl=20.0, kd=0.0):
    return {"kp": [kp] * 3, "ki": [ki] * 3, "itl": [itl] * 3, "kd": [kd] * 3}


def test_big_overshoot_lowers_kp_and_adds_d():
    new, notes, conv = at.tune(_mk(os_up=60), _g(kp=20.0))
    assert new["kp"][0] == pytest.approx(16.0)     # 20×0.80
    assert new["kd"][0] == pytest.approx(0.04)
    assert conv is False


def test_mid_overshoot_gentler():
    new, _, _ = at.tune(_mk(os_up=40), _g(kp=20.0))
    assert new["kp"][0] == pytest.approx(17.6)     # 20×0.88
    assert new["kd"][0] == pytest.approx(0.02)


def test_low_overshoot_raises_kp_when_ratio_short():
    new, _, _ = at.tune(_mk(os_up=8, r03=0.85), _g(kp=12.0))
    assert new["kp"][0] == pytest.approx(13.2)     # 12×1.10


def test_low_overshoot_keeps_kp_when_ratio_ok():
    new, _, conv = at.tune(_mk(os_up=8, r03=0.98), _g(kp=12.0))
    assert new["kp"][0] == pytest.approx(12.0)
    assert conv is True


def test_steady_error_raises_integral_limit():
    new, _, _ = at.tune(_mk(os_up=20, ss=8.0), _g(itl=15.0))
    assert new["itl"][0] == pytest.approx(21.0)    # 15×1.4


def test_big_steady_error_also_raises_ki():
    new, _, _ = at.tune(_mk(os_up=20, ss=12.0), _g(itl=15.0, ki=15.0))
    assert new["itl"][0] == pytest.approx(21.0)
    assert new["ki"][0] == pytest.approx(17.25)    # 15×1.15


def test_small_steady_error_releases_integral():
    new, _, _ = at.tune(_mk(os_up=20, ss=1.0), _g(itl=40.0))
    assert new["itl"][0] == pytest.approx(36.0)    # 40×0.9


def test_bounds_are_respected():
    new, _, _ = at.tune(_mk(os_up=90), _g(kp=40.0, kd=0.30))
    assert 6.0 <= new["kp"][0] <= 40.0
    assert 0.0 <= new["kd"][0] <= 0.30
    new2, _, _ = at.tune(_mk(os_up=5, r03=0.5), _g(kp=6.0))
    assert new2["kp"][0] >= 6.0


def test_max_rounds_hit_stops_exploration():
    """轮数用完：只降不升（不再提速探索）。"""
    a, _, _ = at.tune(_mk(os_up=8, r03=0.85), _g(kp=12.0), max_rounds_hit=True)
    assert a["kp"][0] == pytest.approx(12.0)


def test_fmt_rounds_nicely():
    assert at.fmt([12.0, 17.6, 18.4]) == "12,17.6,18.4"
    assert at.fmt([15, 15, 15]) == "15,15,15"
    assert at.fmt([0.0, 0.02, 0.04]) == "0,0.02,0.04"


def test_per_cable_independent():
    """一缆超调大、另一缆正常 → 只动超调那根。"""
    m = _mk(os_up=60)
    # 把 C3 的超调改小
    for r in m:
        for c in r["cables"]:
            if c["cable"] == 3 and "overshoot" in c:
                c["overshoot"] = 5.0
    new, notes, _ = at.tune(m, _g(kp=20.0))
    assert new["kp"][0] < 20.0        # C1 降
    assert new["kp"][2] == pytest.approx(20.0)   # C3 不动
