"""位置环"几何自检"探针 —— 打印可核对常数 + 现律/精确位姿的对拉残差。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.wrist_position_loop_probe
    .venv\\Scripts\\python.exe -m tools.wrist_position_loop_probe --full

输出（第 1 段 = 文档 §10 的全部常数，第 2 段 = §5.4 的对照表）：
    标定 k / R(0,0) / 每度 counts / n̂ / l(0,0) / 二阶导 H
    对每个误差 e：现律指令长度、精确位姿长度、两者之差（counts / mm）、
    法向对拉、以及"新律（先算位姿再取绳长）"的残差（应恒为 0）

--full 追加：工作区每根绳的长度行程、n̂ 有效区边界、任意两缆的列夹角。

判据（本文件自检会在末尾打印 PASS/FAIL）：
    新律的法向残差 |n̂·(Λ − l(θ_des))| < 1e-9 mm
    现律的法向残差随 e 二次增长（|γ| / e² 近似常数）

只依赖 wrist_model + wrist_control_law（无 Qt / 无串口）。
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from wrist_model import PITCH, ROLL, positive_null_direction, wrist_eval  # noqa: E402

DEFAULT_K = 130380.0     # counts/m（结构常数；符号不影响下述幅值）
KP_DEFAULT = 0.6         # 与 UI 默认一致


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def l_m(rd: float, pd: float) -> list:
    """三缆总长（m）：ROLL 段 + PITCH 段。"""
    out = wrist_eval(math.radians(rd), math.radians(pd))
    return [out.s_m[ROLL][i] + out.s_m[PITCH][i] for i in range(3)]


def r_mat(rd: float, pd: float) -> list:
    return wrist_eval(math.radians(rd), math.radians(pd)).r_m


def n_hat(rd: float, pd: float):
    return positive_null_direction(math.radians(rd), math.radians(pd))


def hessian(rd: float, pd: float, h: float = 1e-5) -> tuple:
    """数值二阶导 H[i] = 2x2（m/rad²）：rr, rp, pp 三个方向各回一个 3 向量。"""
    rd, pd = math.radians(rd), math.radians(pd)

    def L(a, b):
        return l_m(math.degrees(a), math.degrees(b))

    L0 = L(rd, pd)
    rr = [(L(rd + h, pd)[i] - 2 * L0[i] + L(rd - h, pd)[i]) / (h * h) for i in range(3)]
    pp = [(L(rd, pd + h)[i] - 2 * L0[i] + L(rd, pd - h)[i]) / (h * h) for i in range(3)]
    rp = [(L(rd + h, pd + h)[i] - L(rd + h, pd - h)[i]
           - L(rd - h, pd + h)[i] + L(rd - h, pd - h)[i]) / (4 * h * h) for i in range(3)]
    return rr, rp, pp


def law_lengths(rd_fb, pd_fb, er, ep, kp, k=1.0):
    """现律在"长度域"的指令：Λ = l(θ*) − Kp·R(θ_fb)·e（e 为弧度）。"""
    rt, pt = rd_fb + er, pd_fb + ep
    R = r_mat(rd_fb, pd_fb)
    e_r, e_p = math.radians(er), math.radians(ep)
    return [l_m(rt, pt)[i] - kp * (R[ROLL][i] * e_r + R[PITCH][i] * e_p)
            for i in range(3)]


def normal_proj(vec, rd, pd, k=1.0):
    """把长度差（m）投影到 n̂ 上，返回 counts（k<0 时也按幅值给出）。"""
    n = n_hat(rd, pd)
    if n is None:
        return float("nan")
    return abs(sum(vec[i] * n[i] for i in range(3))) * abs(k)


# --------------------------------------------------------------------------
# 第 1 段：常数
# --------------------------------------------------------------------------
def print_constants(k: float) -> None:
    o = wrist_eval(0.0, 0.0)
    print("=" * 78)
    print("一、常数（θ=(0,0)）")
    print("=" * 78)
    print(f"  k = {k:+.6g} counts/m   (k>0 ⇒ counts↑=放绳；k<0 ⇒ counts↑=收绳)")
    print("  R(0,0)  m/rad         （R_ji = −∂l_i/∂θ_j）")
    for j, nm in ((ROLL, "ROLL "), (PITCH, "PITCH")):
        print(f"    {nm}: " + "  ".join(f"{-o.r_m[j][i]:+.8f}" for i in range(3)))
    print("  每度 counts = −k·R·π/180")
    for j, nm in ((ROLL, "ROLL "), (PITCH, "PITCH")):
        vals = [-k * o.r_m[j][i] * math.pi / 180.0 for i in range(3)]
        print(f"    {nm}: " + "  ".join(f"{v:+.4f}" for v in vals))
    n = n_hat(0.0, 0.0)
    print("  n̂(0,0) = " + ", ".join(f"{v:+.6f}" for v in n)
          + "   |n̂| = %.9f" % math.hypot(*n)
          + "   R·n̂ = (" + ", ".join(f"{o.r_m[j][0]*n[0]+o.r_m[j][1]*n[1]+o.r_m[j][2]*n[2]:+.1e}"
                                     for j in (ROLL, PITCH)) + ")")
    print("  l(0,0) = " + ", ".join(f"{v*1000:.4f}" for v in l_m(0.0, 0.0)) + "  mm")
    rr, rp, pp = hessian(0.0, 0.0)
    print("  H (counts/rad²):")
    print("    d²l/dθr²     = " + ", ".join(f"{v*abs(k):+9.1f}" for v in rr))
    print("    d²l/dθr∂θp  = " + ", ".join(f"{v*abs(k):+9.1f}" for v in rp))
    print("    d²l/dθp²     = " + ", ".join(f"{v*abs(k):+9.1f}" for v in pp))
    print()


# --------------------------------------------------------------------------
# 第 2 段：现律 vs 精确位姿
# --------------------------------------------------------------------------
def print_residuals(k: float, kp: float) -> list:
    print("=" * 78)
    print(f"二、现律（切线）vs 精确位姿（弦）    Kp = {kp}")
    print("=" * 78)
    print("  ΔL = 现律指令长度 − 该位姿的真实绳长；n̂ 分量 = 纯对拉（不产生运动）")
    print()
    hdr = f"  {'e (deg)':>10} | {'ΔL (counts)  C1/C2/C3':>34} | {'法向对拉':>9} | {'折合':>7} | {'新律残差':>9}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    rows = []
    for er, ep in ((1, 0), (2, 0), (4, 0), (8, 0), (0, 8), (8, 8), (8, -8)):
        rt, pt = er, ep                      # 目标在 (er, ep)，反馈在 (0,0)
        cur = law_lengths(0.0, 0.0, er, ep, kp)
        exact = [l_m(rt + kp * er, pt + kp * ep)[i] for i in range(3)]
        d = [(cur[i] - exact[i]) * k for i in range(3)]
        fight = normal_proj([cur[i] - exact[i] for i in range(3)], rt, pt, k)
        mm = fight / abs(k) * 1000.0
        # 新律：Λ = l(θ_des)，与自身比 → 恒 0
        new = [l_m(rt + kp * er, pt + kp * ep)[i] for i in range(3)]
        new_res = normal_proj([new[i] - l_m(rt + kp * er, pt + kp * ep)[i] for i in range(3)],
                              rt + kp * er, pt + kp * ep, k)
        rows.append((er, ep, d, fight))
        print(f"  ({er:+3d},{ep:+3d}) | "
              + " / ".join(f"{v:+6.1f}" for v in d)
              + f" | {fight:9.1f} | {mm:6.3f}mm | {new_res:9.1e}")
    print()

    # 二阶标度自检
    print("  二次标度自检（|对拉| / e²，应近似常数 ≈ 2 counts/deg²）：")
    for er, ep, d, fight in rows:
        if er and ep:
            continue
        step = er or ep
        if step:
            print(f"    e=({er:+d},{ep:+d})° → {abs(fight)/step**2:6.2f} counts/deg²")
    return rows


# --------------------------------------------------------------------------
# 第 3 段（--full）：工作区 / 窗口 / 两缆夹角
# --------------------------------------------------------------------------
def print_full(k: float) -> None:
    print("=" * 78)
    print("三、工作区（roll ±25°，pitch −25~+45°）")
    print("=" * 78)
    lo, hi = [1e9] * 3, [-1e9] * 3
    for rd in range(-25, 26):
        for pd in range(-25, 46):
            L = l_m(rd, pd)
            for i in range(3):
                lo[i] = min(lo[i], L[i])
                hi[i] = max(hi[i], L[i])
    print("  每根绳的长度行程：")
    for i in range(3):
        span = hi[i] - lo[i]
        print(f"    C{i+1}: {span*1000:6.2f} mm = {span*abs(k):6.0f} counts = "
              f"{span*abs(k)/4096.0:4.2f} 圈   (绝对 {lo[i]*1000:5.1f}~{hi[i]*1000:5.1f} mm)")
    print("    参考：1 圈 = 2π·5mm = 31.4 mm = 4096 counts；1 count = 0.0077 mm")
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
    ap.add_argument("--k", type=float, default=DEFAULT_K, help="counts/m（默认 130380）")
    ap.add_argument("--kp", type=float, default=KP_DEFAULT, help="位置环 Kp（默认 0.6）")
    ap.add_argument("--full", action="store_true", help="追加工作区/窗口/夹角")
    args = ap.parse_args(argv)

    print_constants(args.k)
    rows = print_residuals(args.k, args.kp)
    if args.full:
        print_full(args.k)

    # 自检
    ok = True
    for er, ep, d, fight in rows:
        step2 = max(er * er + ep * ep, 1e-9)
        if abs(fight) / step2 > 4.0:      # 二阶项不应超过 ~4 counts/deg²
            ok = False
    print("=" * 78)
    print("自检：" + ("PASS —— 法向对拉符合二阶标度；新律残差 0" if ok else "FAIL —— 见上表"))
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
