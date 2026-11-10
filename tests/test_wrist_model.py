"""wrist_model 几何核心对拍测试。

参考基准：
- H7 包 data/derived_constants.json（source_sha256=952e9c40…）六段投影常数；
- tests/fixtures/R_grid_corrected.csv
  SHA256=32e7111d503728a95ed460259a30bd8fc4c9610dd9039dd6c847736cf63bec09
  该 CSV 是 0.2° 差分参考表：解析式（本模块口径）与它的差包含已知有限差分
  截断（最大约 0.0327mm @ pitch/C1，见解析公式 PDF 第 8 节），不是模型误差，
  因此对拍容差取 3.5e-5 m；
- 文档零位矩阵（解析公式 PDF 第 7 节）。
"""
import csv
import math
import os

import pytest

import wrist_model
from wrist_model import (
    LOW_PITCH_LIMIT_DEG,
    NUMERICAL_MIN_LENGTH_M,
    PITCH,
    RANGE_DEG,
    ROLL,
    wrist_eval,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "R_grid_corrected.csv")

# 文档零位矩阵（mm → m，按 rad 求导的有效力臂数值）
DOC_R0 = [
    [-0.25943726e-3, -22.04970101e-3, 17.37198247e-3],   # roll 行 C1/C2/C3
    [-58.10461556e-3, 11.80488412e-3, 10.99035112e-3],   # pitch 行
]

# 零位全正零空间方向（由六段常数独立预计算）
DOC_NULL0 = (0.2644, 0.5949, 0.7590)

GRID_TOL = 3.5e-5   # m，含 0.2° 差分截断的参考表对拍容差


def test_zero_pose_matrix_matches_doc():
    out = wrist_eval(0.0, 0.0)
    assert out.math_valid is True
    assert out.angle_in_range is True
    for j in range(2):
        for i in range(3):
            assert out.r_m[j][i] == pytest.approx(DOC_R0[j][i], abs=1e-8)


def test_zero_pose_null_direction():
    n = wrist_model.positive_null_direction(0.0, 0.0)
    assert n is not None
    for got, want in zip(n, DOC_NULL0):
        assert got == pytest.approx(want, abs=1e-3)


def _load_grid():
    """返回 [(roll_deg, pitch_deg, L[3], R6[6], positive_null), ...]。"""
    rows = []
    with open(FIXTURE, newline="", encoding="utf-8-sig") as fh:
        for rec in csv.DictReader(fh):
            rows.append((
                float(rec["yaw_deg"]),
                float(rec["pitch_deg"]),
                [float(rec[f"L{k}_m"]) for k in (1, 2, 3)],
                [
                    float(rec["R_yaw_C1_m"]), float(rec["R_pitch_C1_m"]),
                    float(rec["R_yaw_C2_m"]), float(rec["R_pitch_C2_m"]),
                    float(rec["R_yaw_C3_m"]), float(rec["R_pitch_C3_m"]),
                ],
                rec["positive_null"] == "True",
            ))
    assert len(rows) == 3621
    return rows


def test_grid_R_and_lengths_and_flags():
    rows = _load_grid()
    zero = min(rows, key=lambda r: abs(r[0]) + abs(r[1]))
    assert abs(zero[0]) < 1e-9 and abs(zero[1]) < 1e-9
    zero_out = wrist_eval(0.0, 0.0)
    s_zero = [zero_out.s_m[ROLL][i] + zero_out.s_m[PITCH][i] for i in range(3)]
    for roll_deg, pitch_deg, L_ref, r6_ref, pn_ref in rows:
        out = wrist_eval(math.radians(roll_deg), math.radians(pitch_deg))
        assert out.math_valid is True, (roll_deg, pitch_deg)
        assert out.angle_in_range is True, (roll_deg, pitch_deg)
        assert out.low_pitch_zone == (pitch_deg <= LOW_PITCH_LIMIT_DEG)
        for i in range(3):
            assert out.r_m[ROLL][i] == pytest.approx(r6_ref[2 * i], abs=GRID_TOL)
            assert out.r_m[PITCH][i] == pytest.approx(r6_ref[2 * i + 1], abs=GRID_TOL)
        for i in range(3):
            d_ref = L_ref[i] - zero[2][i]
            d_model = (out.s_m[ROLL][i] + out.s_m[PITCH][i]) - s_zero[i]
            assert d_model == pytest.approx(d_ref, abs=GRID_TOL)
        n = wrist_model.positive_null_direction(
            math.radians(roll_deg), math.radians(pitch_deg))
        assert (n is not None) == pn_ref, (roll_deg, pitch_deg)


def test_range_constants():
    assert RANGE_DEG[ROLL] == (-25.0, 25.0)
    assert RANGE_DEG[PITCH] == (-25.0, 45.0)
    assert LOW_PITCH_LIMIT_DEG == -24.0
    assert NUMERICAL_MIN_LENGTH_M == 1e-8


def test_out_of_range_flag():
    out = wrist_eval(math.radians(30.0), 0.0)
    assert out.angle_in_range is False
    # 越界仍给出数学结果（离线可核对），但调用方必须检查标志
    assert out.math_valid is True
