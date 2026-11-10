"""k_winch 识别脚本测试：合成数据恢复已知 k、退化抛错、迟滞分解。"""
import math
import random

import pytest

from tools.identify_wrist_calib import fit_k_counts_per_m, identify
from wrist_model import PITCH, ROLL, wrist_eval


def _model_dl(roll_deg, pitch_deg, roll0=0.0, pitch0=0.0):
    def L(r, p):
        out = wrist_eval(math.radians(r), math.radians(p))
        return [out.s_m[ROLL][i] + out.s_m[PITCH][i] for i in range(3)]
    l0 = L(roll0, pitch0)
    l1 = L(roll_deg, pitch_deg)
    return [l1[i] - l0[i] for i in range(3)]


def test_fit_recovers_known_k():
    rng = random.Random(42)
    k_true = 1e5
    d_l = [rng.uniform(-0.004, 0.004) for _ in range(200)]   # ±4mm
    d_c = [k_true * l + rng.gauss(0.0, 5.0) for l in d_l]
    k_hat = fit_k_counts_per_m(d_l, d_c)
    assert abs(k_hat - k_true) / k_true < 0.01


def test_fit_degenerate_raises():
    with pytest.raises(ValueError):
        fit_k_counts_per_m([0.0] * 50, [1.0] * 50)


def _sweep_rows(k=1e5, backward_offset=3.0):
    """roll 单轴 -20→20→-20 合成记录；返程 counts 加 +3 偏置（迟滞）。"""
    rows = []
    t = 0.0

    def add(roll, backward):
        nonlocal t
        dl = _model_dl(roll, 0.0)
        base = {"t_s": f"{t:.3f}", "roll_deg": f"{roll:.3f}", "pitch_deg": "0.000"}
        for i, key in enumerate(("m27_abs", "m28_abs", "m29_abs")):
            base[key] = f"{100000.0 + k * dl[i] + (backward_offset if backward else 0.0):.2f}"
        rows.append(base)
        t += 0.01

    for i in range(101):            # 正程 -20 → +20
        add(-20.0 + 0.4 * i, backward=False)
    for i in range(101):            # 返程 +20 → -20
        add(20.0 - 0.4 * i, backward=True)
    return rows


def test_hysteresis_split():
    rep = identify(_sweep_rows())
    for key in ("m27_abs", "m28_abs", "m29_abs"):
        m = rep["motors"][key]
        assert m["hysteresis_diff"] == pytest.approx(3.0, abs=1.0)


def test_k_sign_and_magnitude_from_sweep():
    # 无迟滞偏置：k̂ 精确恢复（带偏置时 LS 斜率受 dl 分布不对称影响，
    # 见 test_hysteresis_split —— 迟滞量由迟滞列单独暴露，不混入量值断言）
    rep = identify(_sweep_rows(k=-1e5, backward_offset=0.0))
    for key in ("m27_abs", "m28_abs", "m29_abs"):
        m = rep["motors"][key]
        assert m["k_counts_per_m"] == pytest.approx(-1e5, rel=1e-5)


def test_missing_tension_column():
    rows = _sweep_rows()   # 本就不含 f1_n..f3_n 列
    rep = identify(rows)
    assert rep["n_rows"] == 202


def test_identify_rejects_insufficient_rows():
    with pytest.raises(ValueError):
        identify([{"t_s": "0.0", "roll_deg": "0", "pitch_deg": "0",
                   "m27_abs": "1", "m28_abs": "1", "m29_abs": "1"}])
