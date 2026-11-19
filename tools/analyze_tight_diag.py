"""分析「🔬 诊断 CSV」（`run_data/scope_exports/diag_*.csv`）。

回答一个问题：**张紧模式名义上 τ=0，实际 τ 有多大、由什么造成？**

用法（在 code/mmhand-main 下）：

    .venv\\Scripts\\python.exe -m tools.analyze_tight_diag                # 自动取最新 diag_*.csv
    .venv\\Scripts\\python.exe -m tools.analyze_tight_diag <path.csv>

输出分四段：

1. **概况**：时长、样本、位姿范围、预紧
2. **τ 统计**：均值（偏置）/ 标准差（抖动）/ 峰峰值 / 漂移（前后 20% 均值差）
3. **能力对照**：用同一套 `tda_solve` 反查该位姿+预紧下能给出多大力矩 → 算 τ 占比
4. **误差分解**：把实测张力偏差 δf = f_meas − t*·n̂ 拆成
   - **共模**（沿 n̂ 的分量）：只改预紧，不产生力矩
   - **差模**（垂直 n̂ 的分量）：**这才是力矩的来源**
   并给出"若把差模压到 0，τ 会降到多少"的上界估计。

自动结论（最后一行）会把结果归到三类之一：
    A. 以偏置为主 → 模型/R 或 n̂ 有系统偏差（要前馈补偿）
    B. 以抖动为主 → 迟滞/摩擦/分辨率（要低增益反馈或提高预紧）
    C. 随时间单调漂移 → 绳蠕变/热漂/零点（要慢积分或重新归零）
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402

from mmhand_scope_export import EXPORT_DIR  # noqa: E402
from wrist_control_law import MODEL_AXIS_SIGN  # noqa: E402
from wrist_model import PITCH, ROLL, positive_null_direction, wrist_eval  # noqa: E402
from wrist_tda import tda_solve  # noqa: E402

FMIN, FMAX = 0.5, 25.0
MODE_NAMES = {1: "张力", 2: "张紧", 3: "力矩"}


def _load(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("CSV 没有数据行")
    cols = {}
    for k in rows[0]:
        vals = []
        for r in rows:
            try:
                vals.append(float(r[k]))
            except (TypeError, ValueError):
                vals.append(float("nan"))
        cols[k] = np.array(vals)
    return cols


def _n_hat(roll_deg: float, pitch_deg: float):
    """UI 角 → 模型角（含 MODEL_AXIS_SIGN）→ n̂。"""
    o = wrist_eval(np.radians(MODEL_AXIS_SIGN[0] * roll_deg),
                   np.radians(MODEL_AXIS_SIGN[1] * pitch_deg))
    if not o.math_valid:
        return None, None
    n = positive_null_direction(np.radians(MODEL_AXIS_SIGN[0] * roll_deg),
                                np.radians(MODEL_AXIS_SIGN[1] * pitch_deg),
                                out_model=o)
    return o, n


def _capacity(r_m, n, preload: float, fmin=FMIN, fmax=FMAX):
    """该位姿+预紧下，两个轴各能给出多大力矩（二分 α=1 边界）。"""
    caps = []
    for axis in (0, 1):
        lo, hi = 0.0, 3.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            tau = [0.0, 0.0]
            tau[axis] = mid
            f, _fl, a = tda_solve(r_m, n, tau[0], tau[1], preload, fmin, fmax)
            if f is not None and a >= 1.0 - 1e-12:
                lo = mid
            else:
                hi = mid
        caps.append(lo)
    return caps


def main(argv) -> int:
    if len(argv) > 1:
        path = Path(argv[1])
    else:
        cands = sorted(EXPORT_DIR.glob("diag_*.csv"))
        if not cands:
            print(f"没找到 {EXPORT_DIR}/diag_*.csv —— 先在上位机点「🔬 诊断 CSV」")
            return 1
        path = cands[-1]
    print(f"文件：{path.name}")
    c = _load(path)

    t = c["t_s"]
    dt = float(np.median(np.diff(t))) if len(t) > 2 else 0.0
    print(f"\n【1. 概况】")
    print(f"  时长 {t[-1] - t[0]:.1f} s，样本 {len(t)}，采样 {1/dt:.1f} Hz"
          if dt > 0 else f"  样本 {len(t)}")
    modes = sorted({int(v) for v in c["mode"] if not np.isnan(v)})
    print(f"  模式：{', '.join(MODE_NAMES.get(m, str(m)) for m in modes)}")
    print(f"  roll  {np.nanmin(c['roll_deg']):+.2f} … {np.nanmax(c['roll_deg']):+.2f} °"
          f"   pitch {np.nanmin(c['pitch_deg']):+.2f} … {np.nanmax(c['pitch_deg']):+.2f} °")
    pre = c["preload_N"]
    pre_val = float(np.nanmedian(pre)) if not np.all(np.isnan(pre)) else float("nan")
    print(f"  预紧（中位）{pre_val:.2f} N")

    tr = c["tau_r_mNm"] / 1000.0
    tp = c["tau_p_mNm"] / 1000.0
    print(f"\n【2. τ 统计】（N·m）")
    for name, v in (("roll ", tr), ("pitch", tp)):
        v = v[~np.isnan(v)]
        if not len(v):
            continue
        n20 = max(1, len(v) // 5)
        drift = float(np.mean(v[-n20:]) - np.mean(v[:n20]))
        print(f"  τ_{name}: 均值 {np.mean(v):+.4f}  标准差 {np.std(v):.4f}"
              f"  峰峰 {np.max(v) - np.min(v):.4f}  漂移(首尾20%) {drift:+.4f}")

    # 3. 能力对照（用中位位姿与预紧）
    rd = float(np.nanmedian(c["roll_deg"]))
    pd_ = float(np.nanmedian(c["pitch_deg"]))
    o, n = _n_hat(rd, pd_)
    if o is not None and n is not None:
        cap = _capacity(o.r_m, n, pre_val if not np.isnan(pre_val) else 5.0)
        print(f"\n【3. 能力对照】({rd:+.1f}, {pd_:+.1f})° 预紧 {pre_val:.1f} N")
        print(f"  最多能给：roll {cap[0]:.3f} / pitch {cap[1]:.3f} N·m")
        for name, v, ccap in (("roll ", tr, cap[0]), ("pitch", tp, cap[1])):
            v = v[~np.isnan(v)]
            if len(v) and ccap > 1e-9:
                print(f"  |τ_{name}| 均值占能力 {np.mean(np.abs(v)) / ccap * 100:5.1f}%"
                      f"   峰峰值占 {np.ptp(v) / ccap * 100:5.1f}%")

    # 4. 误差分解（需要三缆张力）
    f1, f2, f3 = c["f1_N"], c["f2_N"], c["f3_N"]
    if not (np.all(np.isnan(f1)) or o is None or n is None):
        nv = np.array(n)
        f = np.vstack([f1 - f1, f2 - f2, f3 - f3])  # 占位，下面逐点算
        dev_com, dev_dif, tau_norm = [], [], []
        idx = range(0, len(t), max(1, len(t) // 400))
        for i in idx:
            oo, nn = _n_hat(c["roll_deg"][i], c["pitch_deg"][i])
            if oo is None or nn is None:
                continue
            nvec = np.array(nn)
            fm = np.array([f1[i], f2[i], f3[i]])
            fd = t_star = c["t_meas_N"][i]
            dev = fm - t_star * nvec
            com = float(dev @ nvec) * nvec          # 共模（沿 n̂）
            dif = dev - com                          # 差模（垂直 n̂）
            dev_com.append(np.linalg.norm(com))
            dev_dif.append(np.linalg.norm(dif))
            R = np.array([oo.r_m[ROLL], oo.r_m[PITCH]])
            tau_norm.append(float(np.linalg.norm(R @ dev)))
        if dev_com:
            print(f"\n【4. 误差分解】δf = f_meas − t*·n̂")
            print(f"  共模分量（只改预紧，不产生 τ） 典型 {np.median(dev_com):.3f} N")
            print(f"  差模分量（**τ 的全部来源**）   典型 {np.median(dev_dif):.3f} N")
            print(f"  差模→τ 换算后 |τ| 典型 {np.median(tau_norm) * 1000:.1f} mN·m")

    # 结论
    print("\n【结论】")
    vr, vp = tr[~np.isnan(tr)], tp[~np.isnan(tp)]
    if not len(vr) or not len(vp):
        print("  数据不足，无法判断")
        return 0
    bias = max(abs(np.mean(vr)), abs(np.mean(vp)))
    jit = max(np.std(vr), np.std(vp))
    n20r = max(1, len(vr) // 5)
    drift = max(abs(np.mean(vr[-n20r:]) - np.mean(vr[:n20r])),
                abs(np.mean(vp[-n20r:]) - np.mean(vp[:n20r])))
    if drift > max(bias, jit) * 0.8:
        print(f"  C. 以漂移为主（{drift * 1000:.1f} mN·m）→ 绳蠕变/热漂/零点，需慢积分或重新归零")
    elif jit > abs(bias) * 1.5:
        print(f"  B. 以抖动为主（σ={jit * 1000:.1f} mN·m）→ 迟滞/摩擦/分辨率，"
              "低增益反馈或提高预紧")
    else:
        print(f"  A. 以偏置为主（{bias * 1000:.1f} mN·m）→ 模型/R 或 n̂ 系统偏差，"
              "值得做前馈补偿（A1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
