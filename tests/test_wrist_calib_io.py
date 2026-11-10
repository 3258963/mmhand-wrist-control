"""wrist_calib.json 解析校验测试（parse_wrist_calib）。

格式：{"version":1,"k_counts_per_m":[k1,k2,k3],"zero_offset_deg":[δr,δp],
       "saved_at":"..."}（zero_offset_deg 可缺省=0；saved_at 仅溯源）。
"""
import math

from wrist_control_law import WristCalib, parse_wrist_calib


def _valid():
    return {"version": 1, "k_counts_per_m": [1e5, -2e5, 1.5e5],
            "zero_offset_deg": [0.5, -0.2], "saved_at": "2026-10-25"}


def test_valid():
    calib, err = parse_wrist_calib(_valid())
    assert err is None and calib is not None
    assert calib.k_counts_per_m == [1e5, -2e5, 1.5e5]
    assert calib.zero_offset_deg == [0.5, -0.2]


def test_defaults_and_sign_kept():
    calib, err = parse_wrist_calib({"version": 1, "k_counts_per_m": [-1e5, -1e5, -1e5]})
    assert err is None
    assert calib.zero_offset_deg == [0.0, 0.0]     # δ 可缺省
    assert all(k < 0 for k in calib.k_counts_per_m)  # 负 k（绕向）合法


def test_rejects_missing_or_bad_version():
    data = _valid(); del data["version"]
    calib, err = parse_wrist_calib(data)
    assert calib is None and "version" in err
    calib, err = parse_wrist_calib({**_valid(), "version": 2})
    assert calib is None and "version" in err


def test_rejects_missing_k():
    data = _valid(); del data["k_counts_per_m"]
    calib, err = parse_wrist_calib(data)
    assert calib is None and "k_counts_per_m" in err


def test_rejects_wrong_length():
    calib, err = parse_wrist_calib({**_valid(), "k_counts_per_m": [1e5, 2e5]})
    assert calib is None and "3" in err
    calib, err = parse_wrist_calib({**_valid(), "zero_offset_deg": [0.0]})
    assert calib is None


def test_rejects_zero_k():
    calib, err = parse_wrist_calib({**_valid(), "k_counts_per_m": [1e5, 0.0, 1e5]})
    assert calib is None and "k" in err


def test_rejects_nonfinite_or_nonnumeric():
    calib, err = parse_wrist_calib({**_valid(), "k_counts_per_m": [1e5, math.nan, 1e5]})
    assert calib is None
    calib, err = parse_wrist_calib({**_valid(), "k_counts_per_m": [1e5, "big", 1e5]})
    assert calib is None
    calib, err = parse_wrist_calib({**_valid(), "zero_offset_deg": [math.inf, 0.0]})
    assert calib is None


def test_rejects_none_input():
    calib, err = parse_wrist_calib(None)
    assert calib is None and err
