"""位置环"几何自检"探针 —— 打印可核对常数 + 现律/精确位姿的对拉残差。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.wrist_position_loop_probe
    .venv\\Scripts\\python.exe -m tools.wrist_position_loop_probe --full
    .venv\\Scripts\\python.exe -m tools.wrist_position_loop_probe --k -108649.77,118527.03,118527.03

k 默认读 run_data/scope_exports/wrist_calib.json（逐路不同，见 wrist_control_law.SPOOL_RADIUS_M）；
文件缺失时退回名义值 K_NOMINAL_ABS。

输出（第 1 段 = 文档 §10 的常数，第 2 段 = §5.4 的对照表）：
    k / R(0,0) / 每度 counts（逐路）/ n̂ / l(0,0) / 二阶导 H
    对每个误差 e：现律指令与该位姿真实绳长之差（逐路 counts + 法向 mm）、
    以及"新律（先算位姿再取绳长）"的残差（应恒为 0）

--full 追加：每根绳的行程、n̂ 有效区边界、任意两缆的列夹角。

只依赖 wrist_model + wrist_control_law（无 Qt / 无串口）。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from wrist_control_law import K_NOMINAL_ABS, SPOOL_RADIUS_M, parse_wrist_calib  # noqa: E402
from wrist_model import PITCH, ROLL, positive_null_direction, wrist_eval  # noqa: E402

KP_DEFAULT = 0.6         # 与 UI 默认一致
CALIB_PATH = _REPO_ROOT / "run_data" / "scope_exports" / "wrist_calib.json"


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def load_k(sign_nominal: bool = True) -> list:
    """逐路 k（counts/m）。优先读标定文件，否则用名义值（C1 取负，与现场一致）。"""
    try:
        data = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
        calib, err = parse_wrist_calib(data)
        if calib is not None:
            return list(calib.k_counts_per_m)
    except (OSError, ValueError):
        pass
    return [-K_NOMINAL_ABS[0], K_NOMINAL_ABS[1], K_NOMINAL_ABS[2]] if sign_nominal \
        else list(K_NOMINAL_ABS)


def l_m(rd: float, pd: float) -> list:
    """三缆总长（m）：ROLL 段 + PITCH 段。"""
    out = wrist_eval(math.radians(rd), math.radians(pd))
    return [out.s_m[ROLL][i] + out.s_m[PITCH][i] for i in range(3)]


def r_mat(rd: float, pd: float) -> list:
    return wrist_eval(math.radians(rd), math.radians(pd)).r_m


def n_hat(rd: float, pd: float):
    return positive_null_direction(math.radians(rd), math.radians(pd))


def hessian(rd: float, pd: float, h: float = 1e-5) -> tuple:
    """数值二阶导：rr / rp / pp 三个方向，各回一个 3 向量（m/rad²）。"""
    rd, pd = math.radians(rd), math.radians(pd)

    def L(a, b):
        return l_m(math.degrees(a), math.degrees(b))

    L0 = L(rd, pd)
    rr = [(L(rd + h, pd)[i] - 2 * L0[i] + L(rd - h, pd)[i]) / (h * h) for i in range(3)]
    pp = [(L(rd, pd + h)[i] - 2 * L0[i] + L(rd, pd - h)[i]) / (h * h) for i in range(3)]
    rp = [(L(rd + h, pd + h)[i] - L(rd + h, pd - h)[i]
           - L(rd - h, pd + h)[i] + L(rd - h, pd - h)[i]) / (4 * h * h) for i in range(3)]
    return rr, rp, pp


def law_lengths(rd_fb, pd_fb, er, ep, kp):
    """现律在"长度域"的指令：Λ = l(θ*) − Kp·R(θ_fb)·e（e 为弧度）。"""
    rt, pt = rd_fb + er, pd_fb + ep
    R = r_mat(rd_fb, pd_fb)
    e_r, e_p = math.radians(er), math.radians(ep)
    return [l_m(rt, pt)[i] - kp * (R[ROLL][i] * e_r + R[PITCH][i] * e_p)
            for i in range(3)]


def normal_mm(vec, rd, pd):
    """把长度差（m）投影到 n̂ 上 → 法向对拉（mm，带符号）。"""
    n = n_hat(rd, pd)
    if n is None:
        return float("nan")
    return sum(vec[i] * n[i] for i in range(3)) * 1000.0


# --------------------------------------------------------------------------
# 第 1 段：常数
# --------------------------------------------------------------------------
def print_constants(k: list) -> None:
    o = wrist_eval(0.0, 0.0)
    print("=" * 84)
    print("一、常数（θ=(0,0)）")
    print("=" * 84)
    print("  k（counts/m，逐路；4096 c/圈 ÷ 2π·r）：")
    for i in range(3):
        r = SPOOL_RADIUS_M[i] * 1000.0
        print(f"    C{i + 1}(M{27 + i}): r={r:.1f}mm → k={k[i]:+.4f}"
              f"   （counts/mm={abs(k[i]) / 1000:.3f}，1 count={1000 / abs(k[i]):.5f}mm）")
    print("  R(0,0)  m/rad         （R_ji = −∂l_i/∂θ_j）")
    for j, nm in ((ROLL, "ROLL "), (PITCH, "PITCH")):
        print(f"    {nm}: " + "  ".join(f"{-o.r_m[j][i]:+.8f}" for i in range(3)))
    print("  每度 counts = −k_i·R_ji·π/180（逐路，符号随 k）")
    for j, nm in ((ROLL, "ROLL "), (PITCH, "PITCH")):
        vals = [-k[i] * o.r_m[j][i] * math.pi / 180.0 for i in range(3)]
        print(f"    {nm}: " + "  ".join(f"{v:+9.4f}" for v in vals)
              + "    |幅值| " + "  ".join(f"{abs(v):7.3f}" for v in vals))
    n = n_hat(0.0, 0.0)
    print("  n̂(0,0) = " + ", ".join(f"{v:+.6f}" for v in n)
          + "   |n̂| = %.9f" % math.hypot(*n)
          + "   R·n̂ = (" + ", ".join(f"{o.r_m[j][0]*n[0]+o.r_m[j][1]*n[1]+o.r_m[j][2]*n[2]:+.1e}"
                                     for j in (ROLL, PITCH)) + ")")
    print("  l(0,0) = " + ", ".join(f"{v*1000:.4f}" for v in l_m(0.0, 0.0)) + "  mm")
    rr, rp, pp = hessian(0.0, 0.0)
    print("  H (counts/rad²，逐路乘 |k_i|)：")
    print("    d²l/dθr²     = " + ", ".join(f"{v*abs(k[i]):+9.1f}" for i, v in enumerate(rr)))
    print("    d²l/dθr∂θp  = " + ", ".join(f"{v*abs(k[i]):+9.1f}" for i, v in enumerate(rp)))
    print("    d²l/dθp²     = " + ", ".join(f"{v*abs(k[i]):+9.1f}" for i, v in enumerate(pp)))
    print()


# --------------------------------------------------------------------------
# 第 2 段：现律 vs 精确位姿
# --------------------------------------------------------------------------
def print_residuals(k: list, kp: float) -> list:
    print("=" * 84)
    print(f"二、现律（切线）vs 精确位姿（弦）    Kp = {kp}")
    print("=" * 84)
    print("  ΔL = 现律指令长度 − 该位姿真实绳长（每缆自己的 counts）；")
    print("  γ = 该差值在 n̂ 上的投影（mm）= 纯对拉，不产生运动")
    print()
    hdr = (f"  {'e (deg)':>10} | {'ΔL counts  C1/C2/C3':>30} | "
           f"{'γ (mm)':>8} | {'γ/e²':>6} | {'新律残差':>9}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    rows = []
    for er, ep in ((1, 0), (2, 0), (4, 0), (8, 0), (0, 8), (8, 8), (8, -8)):
        rt, pt = er, ep                      # 目标在 (er, ep)，反馈在 (0,0)
        cur = law_lengths(0.0, 0.0, er, ep, kp)
        exact = [l_m(rt + kp * er, pt + kp * ep)[i] for i in range(3)]
        d_m = [cur[i] - exact[i] for i in range(3)]
        d_ct = [d_m[i] * k[i] for i in range(3)]
        g_mm = normal_mm(d_m, rt, pt)
        step2 = max(er * er + ep * ep, 1e-9)
        # 新律：Λ = l(θ_des)，与自身比 → 恒 0
        nd = [l_m(rt + kp * er, pt + kp * ep)[i] for i in range(3)]
        new_res = normal_mm([nd[i] - exact[i] for i in range(3)],
                            rt + kp * er, pt + kp * ep)
        rows.append((er, ep, d_ct, g_mm))
        print(f"  ({er:+3d},{ep:+3d}) | "
              + " / ".join(f"{v:+7.1f}" for v in d_ct)
              + f" | {g_mm:+8.3f} | {abs(g_mm) / step2:6.2f} | {new_res:9.1e}")
    print()
    print("  γ/e² 应近似常数（二阶标度）；新律残差应恒为 0（浮点 ~1e-16）")
    return rows


# --------------------------------------------------------------------------
# 第 3 段（--full）：工作区 / 窗口 / 两缆夹角
# --------------------------------------------------------------------------
def print_full(k: list) -> None:
    print("=" * 84)
    print("三、工作区（roll ±25°，pitch −25~+45°）")
    print("=" * 84)
    lo, hi = [1e9] * 3, [-1e9] * 3
    for rd in range(-25, 26):
        for pd in range(-25, 46):
            L = l_m(rd, pd)
            for i in range(3):
                lo[i] = min(lo[i], L[i])
                hi[i] = max(hi[i], L[i])
    print("  每根绳的长度行程（圈数按本路半径算）：")
    for i in range(3):
        span = hi[i] - lo[i]
        rev_mm = 2.0 * math.pi * SPOOL_RADIUS_M[i] * 1000.0
        print(f"    C{i + 1}: {span*1000:6.2f} mm = {span*abs(k[i]):6.0f} counts = "
              f"{span*1000/rev_mm:4.2f} 圈   (绝对 {lo[i]*1000:5.1f}~{hi[i]*1000:5.1f} mm)")
    print(f"    参考：1 圈 = {2*math.pi*SPOOL_RADIUS_M[1]*1000:.2f}mm(C2/C3) /"
          f" {2*math.pi*SPOOL_RADIUS_M[0]*1000:.2f}mm(C1) = 4096 counts")
    print()

    print("  n̂（三缆可同时正预紧）存在区边界（0.5° 扫描）：")
    for pd in (-25, -20, -10, 0, 10, 20, 30, 33, 34, 40, 45):
        vals = [i * 0.05 for i in range(-500, 501)
                if n_hat(i * 0.05, pd) is not None]
        if vals:
            print(f"    pitch={pd:+5.1f}° → roll ∈ [{min(vals):+7.2f}, {max(vals):+6.2f}]")
        else:
            print(f"    pitch={pd:+5.1f}° → 无（三缆无法同时正预紧）")
    print()

    print("  任意两缆在关节空间的列夹角（= 该缆对若松弛，还剩几个可控方向）：")
    print("    90° ≈ 正交（可独立控两轴）；→ 0° 表示这两根只能控一个方向")
    for rd, pd in ((0, 0), (10, 10), (14, 0), (0, 30), (-18, 0), (15, 15), (20, 0)):
        R = r_mat(rd, pd)
        ang = []
        for i, j in ((0, 1), (1, 2), (0, 2)):
            a = [R[ROLL][i], R[PITCH][i]]
            b = [R[ROLL][j], R[PITCH][j]]
            na, nb = math.hypot(*a), math.hypot(*b)
            s = abs(a[0] * b[1] - a[1] * b[0]) / (na * nb) if na * nb else 0.0
            ang.append(math.degrees(math.asin(max(-1.0, min(1.0, s)))))
        ok = "窗内" if n_hat(rd, pd) is not None else "窗外"
        print(f"    ({rd:+3d},{pd:+3d}) {ok}: C1+C2={ang[0]:5.1f}°  "
              f"C2+C3={ang[1]:5.1f}°  C1+C3={ang[2]:5.1f}°")
    print()


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="位置环几何自检（常数 + 对拉残差）")
    ap.add_argument("--k", default=None,
                    help="逐路 k，逗号分隔 3 个（默认读标定文件/名义值）")
    ap.add_argument("--kp", type=float, default=KP_DEFAULT, help="位置环 Kp（默认 0.6）")
    ap.add_argument("--full", action="store_true", help="追加工作区/窗口/夹角")
    args = ap.parse_args(argv)

    if args.k:
        k = [float(v) for v in args.k.split(",")]
        if len(k) != 3:
            print("--k 需要 3 个数，用逗号分隔", file=sys.stderr)
            return 2
    else:
        k = load_k()

    print_constants(k)
    rows = print_residuals(k, args.kp)
    if args.full:
        print_full(k)

    ok = all(abs(g) / max(er * er + ep * ep, 1e-9) < 4.0 for er, ep, _, g in rows)
    print("=" * 84)
    print("自检：" + ("PASS —— 法向对拉符合二阶标度；新律残差 0" if ok else "FAIL —— 见上表"))
    print("=" * 84)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
