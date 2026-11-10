"""wrist_calib_capture CSV → 每电机 k̂（counts/m）与残差报告（离线识别）。

用法（仓库根目录）：
    .venv\\Scripts\\python.exe -m tools.identify_wrist_calib <capture.csv> [--write]

输入 CSV 列：t_s, roll_deg, pitch_deg, m27_abs, m28_abs, m29_abs[, f1_n, f2_n, f3_n]
（张力列可选，当前识别不消费；NaN/缺数行自动跳过）。
--write：把 k̂ 写成 run_data/scope_exports/wrist_calib.json 草案
（zero_offset_deg 占位 0 —— δ 与 β/γ 相位耦合，必须由机械基准确定，
不得由本数据识别；写入前请人工核对本报告）。

识别原理：闭环记录 (θ, counts)，模型给出 Δl(θ)（δ=0），每电机按过原点
最小二乘 k̂ = Σ(Δl·Δc)/Σ(Δl²) 拟合；残差 RMSE/95%分位/最大差与正/返程
中位差（迟滞）一并报告。角度零偏 δ 会轻微移动 Δl 曲线，对全行程斜率的
影响为二阶；δ 最终以机械基准为准。
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from wrist_model import PITCH, ROLL, wrist_eval

MOTOR_KEYS = ("m27_abs", "m28_abs", "m29_abs")
MOTOR_LABELS = ("M27", "M28", "M29")


def fit_k_counts_per_m(d_l: list, d_counts: list) -> float:
    """过原点最小二乘：k̂ = Σ(Δl·Δc)/Σ(Δl²)。Δl 全零/退化时抛 ValueError。"""
    num = sum(l * c for l, c in zip(d_l, d_counts))
    den = sum(l * l for l in d_l)
    if den < 1e-12:
        raise ValueError("Δl 全零/退化：无角度变化信息，k 不可辨识")
    return num / den


def _model_cable_lengths(roll_deg: float, pitch_deg: float) -> list:
    out = wrist_eval(math.radians(roll_deg), math.radians(pitch_deg))
    return [out.s_m[ROLL][i] + out.s_m[PITCH][i] for i in range(3)]


def _median(vals: list) -> float:
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return math.nan
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _p95(vals: list) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(0.95 * (len(s) - 1) + 0.5))] if s else math.nan


def identify(rows: list) -> dict:
    """DictReader 行列表 -> 识别报告。有效行 <10 抛 ValueError。"""
    data = []
    for rec in rows:
        try:
            t = float(rec["t_s"])
            r = float(rec["roll_deg"])
            p = float(rec["pitch_deg"])
            m = [float(rec[k]) for k in MOTOR_KEYS]
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (t, r, p, *m)):
            continue
        data.append((t, r, p, m))
    if len(data) < 10:
        raise ValueError(f"有效行不足（{len(data)} < 10）")

    l0 = _model_cable_lengths(data[0][1], data[0][2])
    m0 = data[0][3]

    # 每行模型 Δl（一次算好）与运动方向（取变化大的轴）
    dls = []
    dirs = [0]   # dirs[i] 对应 data[i]，首行无方向
    for i, (t, r, p, m) in enumerate(data):
        L = _model_cable_lengths(r, p)
        dls.append([L[k] - l0[k] for k in range(3)])
        if i > 0:
            dr = r - data[i - 1][1]
            dp = p - data[i - 1][2]
            d = dr if abs(dr) >= abs(dp) else dp
            dirs.append(1 if d > 0 else (-1 if d < 0 else 0))

    report = {"n_rows": len(data), "motors": {}}
    for idx, key in enumerate(MOTOR_KEYS):
        d_l = [dl[idx] for dl in dls]
        d_c = [m[idx] - m0[idx] for *_x, m in data]
        k = fit_k_counts_per_m(d_l, d_c)
        residuals = [c - k * l for l, c in zip(d_l, d_c)]
        fwd = [residuals[i] for i in range(len(data)) if dirs[i] > 0]
        bwd = [residuals[i] for i in range(len(data)) if dirs[i] < 0]
        med_f, med_b = _median(fwd), _median(bwd)
        report["motors"][key] = {
            "k_counts_per_m": k,
            "residual_rmse": math.sqrt(sum(r * r for r in residuals) / len(residuals)),
            "residual_p95": _p95([abs(r) for r in residuals]),
            "residual_max": max(abs(r) for r in residuals),
            "hysteresis_median_fwd": med_f,
            "hysteresis_median_bwd": med_b,
            "hysteresis_diff": med_b - med_f if math.isfinite(med_f) and math.isfinite(med_b) else math.nan,
        }
    return report


def _format_report(rep: dict) -> str:
    lines = [f"有效行数: {rep['n_rows']}",
             f"{'电机':<6}{'k̂ (counts/m)':>16}{'RMSE':>9}{'95%':>9}{'max':>9}"
             f"{'正程中位':>10}{'返程中位':>10}{'迟滞差':>9}"]
    for key, label in zip(MOTOR_KEYS, MOTOR_LABELS):
        m = rep["motors"][key]
        lines.append(
            f"{label:<6}{m['k_counts_per_m']:>16.0f}{m['residual_rmse']:>9.1f}"
            f"{m['residual_p95']:>9.1f}{m['residual_max']:>9.1f}"
            f"{m['hysteresis_median_fwd']:>10.1f}{m['hysteresis_median_bwd']:>10.1f}"
            f"{m['hysteresis_diff']:>9.1f}")
    lines.append("注：k̂ 为全行程斜率；迟滞差大说明存在摩擦回差/弹性，"
                 "不同预紧档位应分别记录识别。")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="腕部 k_winch 离线识别")
    parser.add_argument("capture", help="wrist_calib_capture_*.csv 路径")
    parser.add_argument("--write", action="store_true",
                        help="把 k̂ 写成 wrist_calib.json 草案（δ 占位 0，须机械基准确定）")
    args = parser.parse_args(argv)

    with open(args.capture, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    try:
        rep = identify(rows)
    except ValueError as exc:
        print(f"识别失败：{exc}", file=sys.stderr)
        return 1
    print(_format_report(rep))

    if args.write:
        from mmhand_scope_export import EXPORT_DIR, safe_export_path
        path = safe_export_path("wrist_calib.json")
        if path is None:
            print("写出失败：路径校验不过", file=sys.stderr)
            return 1
        import json
        k_list = [rep["motors"][key]["k_counts_per_m"] for key in MOTOR_KEYS]
        path.write_text(json.dumps({
            "version": 1,
            "k_counts_per_m": k_list,
            "zero_offset_deg": [0.0, 0.0],
            "note": "k 由 identify_wrist_calib --write 生成草案；"
                    "zero_offset_deg 为占位 0，δ 须由机械基准确定后才可用模型前馈",
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已写出草案: {path}")
        print(f"（scope 载入路径同目录：{EXPORT_DIR / 'wrist_calib.json'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
