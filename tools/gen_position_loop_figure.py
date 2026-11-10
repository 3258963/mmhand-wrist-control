"""生成位置环讲解用的三张图（可直接进报告/PPT）。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.gen_position_loop_figure
    .venv\\Scripts\\python.exe -m tools.gen_position_loop_figure --out <目录>

默认输出到**工作区根目录**的 figs/（= 本仓库上一级；那样任何子进程都能写）。
要放进文档目录就直接传 --out code/mmhand-main/docs/figs（需该目录可写）。

产出：
    position_loop_concept.png    曲面/切线/弦/法向 —— 为什么"切线代替弦"会跑出曲面
    position_loop_numbers.png    (a) 每度 counts 不对称  (b) 法向对拉随步长的二次增长
    position_loop_workspace.png  三缆可同时正预紧的有效区 vs UI 允许的范围

依赖 matplotlib + numpy（仓里已有）。
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from wrist_model import PITCH, ROLL, positive_null_direction, wrist_eval  # noqa: E402

K = 130380.0          # counts/m
KP = 0.6

# 与仓里其它绘图脚本一致的中文/负号设置
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#24303f"
MUTED = "#6b7785"
GRID = "#dfe4ea"
BLUE = "#3b82f6"
RED = "#ef4444"
GREEN = "#10b981"
AMBER = "#f59e0b"


def l_m(rd, pd):
    """三缆总长，米。"""
    o = wrist_eval(math.radians(rd), math.radians(pd))
    return [o.s_m[ROLL][i] + o.s_m[PITCH][i] for i in range(3)]


def l_mm(rd, pd):
    """三缆总长，毫米（画图用）。"""
    return [v * 1000.0 for v in l_m(rd, pd)]


def r_mat(rd, pd):
    return wrist_eval(math.radians(rd), math.radians(pd)).r_m


def n_hat(rd, pd):
    return positive_null_direction(math.radians(rd), math.radians(pd))


def fight_counts(rd_fb, pd_fb, er, ep, kp=KP):
    """现律指令长度与该位姿真实绳长之差在 n̂ 上的投影（counts 绝对值）。"""
    rt, pt = rd_fb + er, pd_fb + ep
    R = r_mat(rd_fb, pd_fb)
    e_r, e_p = math.radians(er), math.radians(ep)
    cur = [l_m(rt, pt)[i] - kp * (R[ROLL][i] * e_r + R[PITCH][i] * e_p) for i in range(3)]
    exact = l_m(rt + kp * er, pt + kp * ep)
    d = [cur[i] - exact[i] for i in range(3)]
    n = n_hat(rt, pt)
    if n is None:
        return float("nan")
    return abs(sum(d[i] * n[i] for i in range(3))) * K


# ---------------------------------------------------------------------------
# 图 1：一维类比的"曲面 / 切线 / 弦 / 法向"
# ---------------------------------------------------------------------------
def fig_concept(path: Path) -> None:
    """一维类比：固定 pitch，只让 roll 变 → 三缆长度在 (C2, C3) 平面上是一条曲线。"""
    pd_fix = 10.0
    th = np.arange(-15.0, 25.01, 0.5)
    pts = np.array([l_mm(t, pd_fix)[1:3] for t in th])       # mm

    th_star, th_fb = 10.0, 0.0
    e = th_star - th_fb
    Ls = l_mm(th_star, pd_fix)
    Lf = l_mm(th_fb, pd_fix)
    Rf = r_mat(th_fb, pd_fix)          # m/rad
    Rs = r_mat(th_star, pd_fix)

    # 现律指令：Λ = l(θ*) − Kp·R(θ_fb)·e（e 用弧度；R 用 m/rad → 结果乘 1000 转 mm）
    e_rad = math.radians(e)
    lam = [Ls[i] - KP * Rf[ROLL][i] * e_rad * 1000.0 for i in range(3)]
    exact = l_mm(th_star + KP * e, pd_fix)

    fig, ax = plt.subplots(figsize=(7.8, 6.0), dpi=170)
    ax.plot(pts[:, 0], pts[:, 1], color=BLUE, lw=2.8, zorder=3,
            label="$\\mathcal{M}=\\{l(\\theta)\\}$（一维类比：只有 ROLL 变）")

    # 切线（θ_fb 处）
    t = np.array([-Rf[ROLL][1], -Rf[ROLL][2]])
    t = t / np.linalg.norm(t)
    seg = 3.2
    ax.plot([Lf[1] - seg * t[0], Lf[1] + seg * t[0]],
            [Lf[2] - seg * t[1], Lf[2] + seg * t[1]],
            color=MUTED, lw=1.3, ls=(0, (5, 4)), zorder=2,
            label="切线（现律用的方向，$R(\\theta_{fb})$）")

    # 法向（θ* 处）：2D 里与切线垂直；统一朝"上"画，避免和别的标注打架
    n2 = np.array([-Rs[ROLL][2], Rs[ROLL][1]])
    n2 = n2 / np.linalg.norm(n2)
    if n2[1] < 0:
        n2 = -n2
    n0 = np.array([Ls[1], Ls[2]])
    tip = n0 + n2 * 3.2
    ax.annotate("", xy=tip, xytext=n0, zorder=8,
                arrowprops=dict(arrowstyle="-|>", color=AMBER, lw=2.2))
    ax.annotate("法向 $\\hat n$：只收紧/放松，不改位姿",
                xy=tip, xytext=(6, 10), textcoords="offset points",
                color=AMBER, fontsize=9.5, ha="left", va="bottom", zorder=8)

    # 关键点
    ax.plot(*n0, "o", ms=9.5, mfc=BLUE, mec="white", mew=1.6, zorder=6)
    ax.annotate("$\\theta^*$（目标）", xy=n0, xytext=(-52, 16),
                textcoords="offset points", color=BLUE, fontsize=10.5,
                arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.9, ls=":"))

    lam2 = np.array([lam[1], lam[2]])
    ex2 = np.array([exact[1], exact[2]])
    ax.plot(*lam2, "x", ms=12, mew=2.8, color=RED, zorder=7,
            label="现律指令（切线外推 → 落在曲面外）")
    ax.plot(*ex2, "o", ms=8.5, mfc=GREEN, mec="white", mew=1.4,
            zorder=6, label="精确位姿指令（在曲面上）")

    ax.annotate("", xy=lam2, xytext=ex2, zorder=7,
                arrowprops=dict(arrowstyle="<->", color=RED, lw=1.5, ls=":"))
    off_mm = abs(float(np.dot(lam2 - ex2, n2)))
    ax.annotate(f"偏离曲面 ≈ {off_mm:.2f} mm\n= 纯对拉 {off_mm/1000*K:.0f} counts",
                xy=(lam2 + ex2) / 2, xytext=(16, -30), textcoords="offset points",
                color=RED, fontsize=9.5, zorder=8,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.0))

    ax.plot(*np.array([Lf[1], Lf[2]]), "s", ms=6.5, mfc="white", mec=MUTED, mew=1.5, zorder=5)
    ax.annotate("$\\theta_{fb}$（反馈）", xy=(Lf[1], Lf[2]), xytext=(-64, 22),
                textcoords="offset points", color=MUTED, fontsize=9.5,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.9, ls=":"))

    ax.set_xlabel("C2 绳长 (mm)", color=INK)
    ax.set_ylabel("C3 绳长 (mm)", color=INK)
    ax.set_title("为什么“切线代替弦”会跑出可达曲面\n"
                 f"（pitch 固定 {pd_fix:g}°，roll {th_fb:g}° → {th_star:g}°，Kp = {KP}）",
                 color=INK, fontsize=12.5, pad=10)
    ax.grid(color=GRID, lw=0.8)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), fontsize=9,
              framealpha=0.95, ncol=2)
    for s in ax.spines.values():
        s.set_color(GRID)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 图 2：(a) 每度 counts  (b) 对拉随步长
# ---------------------------------------------------------------------------
def fig_numbers(path: Path) -> None:
    fig, axs = plt.subplots(1, 2, figsize=(12.4, 4.9), dpi=170)

    # (a) 每度 counts
    ax = axs[0]
    labels = ["C1 (M27)", "C2 (M28)", "C3 (M29)"]
    Rd = r_mat(0, 0)
    roll = [-K * Rd[ROLL][i] * math.pi / 180 for i in range(3)]
    pitch = [-K * Rd[PITCH][i] * math.pi / 180 for i in range(3)]
    x = np.arange(3)
    w = 0.36
    b1 = ax.bar(x - w / 2, roll, w, color=BLUE, label="ROLL 每度", zorder=3)
    b2 = ax.bar(x + w / 2, pitch, w, color=AMBER, label="PITCH 每度", zorder=3)
    ax.axhline(0, color=MUTED, lw=0.9)
    for bars in (b1, b2):
        for r in bars:
            h = r.get_height()
            ax.text(r.get_x() + r.get_width() / 2, h + (2 if h >= 0 else -7),
                    f"{h:+.1f}", ha="center", fontsize=8.6, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5)
    ax.set_ylabel("counts / 度", color=INK)
    ax.set_title("(a) 每 1° 需要的 counts：两个轴差 2.6 倍",
                 color=INK, fontsize=11.5)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.legend(fontsize=9, framealpha=0.95)
    for s in ax.spines.values():
        s.set_color(GRID)

    # (b) 对拉 vs 步长
    ax = axs[1]
    step = np.arange(1.0, 10.01, 0.5)
    roll_only = [fight_counts(0, 0, s, 0) for s in step]
    pitch_only = [fight_counts(0, 0, 0, s) for s in step]
    dual = [fight_counts(0, 0, s, s) for s in step]
    ax.plot(step, roll_only, "o-", color=BLUE, ms=4.5, lw=1.8, label="单轴 ROLL")
    ax.plot(step, pitch_only, "s-", color=AMBER, ms=4.2, lw=1.8, label="单轴 PITCH")
    ax.plot(step, dual, "^-", color=RED, ms=5, lw=2.0, label="双轴 (+s, +s)")
    # 二次参考用**小角度**拟合（e ≤ 4°）；大角度时 H 本身变大，曲线会翘出 e²
    i4 = int(np.argmin(np.abs(step - 4.0)))
    c = roll_only[i4] / step[i4] ** 2
    ax.plot(step, c * step ** 2, "k--", lw=1.2,
            label=f"二次参考 $c\\,e^2$，c = {c:.2f} counts/deg²（e≤4° 拟合）")
    ax.set_xlabel("单轴/双轴步长 e (°)", color=INK)
    ax.set_ylabel("法向对拉 (counts)", color=INK)
    ax.set_title("(b) 对拉随步长二次增长：小步测不出来，8° 就 >1 mm",
                 color=INK, fontsize=11.5)
    ax.grid(color=GRID, lw=0.8)
    ax.legend(fontsize=8.8, framealpha=0.95, loc="upper left")
    i8 = int(np.argmin(np.abs(step - 8.0)))
    ax.annotate(f"{dual[i8]:.0f} counts\n≈ {dual[i8]/K*1000:.2f} mm",
                xy=(step[i8], dual[i8]), xytext=(step[i8] - 4.2, dual[i8] + 20),
                fontsize=9, color=RED,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.1))
    for s in ax.spines.values():
        s.set_color(GRID)

    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 图 3：有效工作区
# ---------------------------------------------------------------------------
def fig_workspace(path: Path) -> None:
    r = np.arange(-25.0, 25.01, 0.5)
    p = np.arange(-25.0, 45.01, 0.5)
    M = np.zeros((len(p), len(r)))
    for j, pv in enumerate(p):
        for i, rv in enumerate(r):
            M[j, i] = 1.0 if n_hat(rv, pv) is not None else 0.0

    fig, ax = plt.subplots(figsize=(7.6, 6.0), dpi=170)
    ax.contourf(r, p, M, levels=[-0.5, 0.5, 1.5],
                colors=["#fde8e6", "#e6f6ec"], zorder=1)
    ax.contour(r, p, M, levels=[0.5], colors=[MUTED], linewidths=1.0, zorder=2)
    ax.add_patch(Rectangle((-25, -25), 50, 70, fill=False, ec=RED, lw=1.6,
                           ls=(0, (6, 4)), zorder=4))
    ax.text(-24, 41.5, "UI 允许（roll ±25°，pitch −25~45°）", color=RED, fontsize=9.5)
    ax.text(3.0, 12.0, "三缆可同时正预紧\n（$\\hat n$ 存在）", color=GREEN, fontsize=10.5,
            ha="center")
    ax.text(3.0, -17.0, "一缆必然松弛\n（冗余塌缩为两缆）", color="#b45309", fontsize=10,
            ha="center")

    # 采样点与两缆夹角
    pts = [((0, 0), "C1+C2=62°\nC2+C3=60°"),
           ((14, 0), "C1+C3=6.2°\n（只剩一个方向）"),
           ((0, 30), "C2+C3=10.4°"),
           ((-18, 0), "C1+C2=2.2°"),
           ((15, 15), "C1+C3=0.4°")]
    for (x0, y0), txt in pts:
        ax.plot(x0, y0, "o", ms=6, mfc="white", mec=INK, mew=1.3, zorder=5)
        ax.annotate(txt, xy=(x0, y0), xytext=(x0 + 2.2, y0 + 1.6),
                    fontsize=8.4, color=INK,
                    bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=GRID, alpha=0.92))
    ax.set_xlabel("ROLL (°)", color=INK)
    ax.set_ylabel("PITCH (°)", color=INK)
    ax.set_title("有效工作区：能控的范围比 UI 允许的小得多", color=INK, fontsize=12.5, pad=10)
    ax.grid(color=GRID, lw=0.7, zorder=0)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.set_xlim(-26, 26)
    ax.set_ylim(-26, 46)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成位置环讲解图（PNG）")
    # 默认落在"仓库上一级/figs"（工作区根）——那里子进程可写；文档目录可写时用 --out 覆盖
    ap.add_argument("--out", default="../../figs",
                    help="输出目录（默认 ../../figs，相对本文件）")
    args = ap.parse_args(argv)
    out = Path(args.out)
    if not out.is_absolute():
        out = (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    fig_concept(out / "position_loop_concept.png")
    fig_numbers(out / "position_loop_numbers.png")
    fig_workspace(out / "position_loop_workspace.png")
    for name in ("position_loop_concept.png", "position_loop_numbers.png",
                 "position_loop_workspace.png"):
        p = out / name
        try:
            shown = p.relative_to(_REPO_ROOT)
        except ValueError:
            shown = p
        print(f"  {shown}  {p.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
