# -*- coding: utf-8 -*-
"""Figures for the Feishu dynamic-R document."""
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Arc, FancyArrowPatch

from verify_dynamic_R import (DEG, load_model, load_points, model_R, null_vector,
                              condition)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
FIG = OUT / "figs"
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Deng"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11
plt.rcParams["axes.titlesize"] = 12.5
plt.rcParams["axes.labelsize"] = 11
plt.rcParams["figure.dpi"] = 200
plt.rcParams["savefig.dpi"] = 200
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.25
plt.rcParams["grid.linestyle"] = "--"

C_BLUE = "#2F5597"
C_RED = "#C00000"
C_GREEN = "#2E7D32"
C_ORANGE = "#C55A11"
C_GRAY = "#666666"

summary = json.loads((OUT / "verify_summary.json").read_text(encoding="utf-8"))
dc, seg, mp = load_model()
points = load_points(mp)
gt = {(r["axis"], r["cable"]): r for r in summary["geometry_table"]}


# ------------------------------------------------------------------ fig 1 geometry
def fig_geometry():
    g = gt[("roll", "C2")]
    a, b, delta = g["a"] * 1e3, g["b"] * 1e3, math.radians(g["delta_deg"])
    h = g["h"] * 1e3
    th = math.radians(30.0)

    fig = plt.figure(figsize=(11.2, 4.6))
    ax = fig.add_subplot(1, 2, 1)
    A = np.array([a, 0.0])
    B0 = b * np.array([math.cos(delta), math.sin(delta)])
    B1 = b * np.array([math.cos(delta + th), math.sin(delta + th)])

    ax.add_patch(plt.Circle((0, 0), a, fill=False, ls=":", lw=1.0, color=C_GRAY))
    ax.add_patch(plt.Circle((0, 0), b, fill=False, ls=":", lw=1.0, color=C_GRAY))
    ax.plot([0, A[0]], [0, A[1]], color=C_BLUE, lw=2.2, label="a（固定端半径）")
    ax.plot([0, B0[0]], [0, B0[1]], color="#7030A0", lw=2.2, label="b（动端半径，零位）")
    ax.plot([0, B1[0]], [0, B1[1]], color="#7030A0", lw=1.4, ls="--")
    ax.plot([A[0], B0[0]], [A[1], B0[1]], color=C_ORANGE, lw=2.4, label="s(0)")
    ax.plot([A[0], B1[0]], [A[1], B1[1]], color=C_ORANGE, lw=1.5, ls="--", label="s(θ)")
    ax.plot(*A, "o", color=C_BLUE, ms=6)
    ax.plot(*B0, "o", color="#7030A0", ms=6)
    ax.plot(*B1, "o", mfc="white", mec="#7030A0", ms=6)
    ax.plot(0, 0, "o", mfc="white", mec="k", ms=7)
    ax.text(0, -3.2, "O（轴心）", ha="center", va="top")

    ax.add_patch(Arc((0, 0), 2 * 13, 2 * 13, theta1=0, theta2=g["delta_deg"], color=C_GREEN, lw=1.6))
    ax.text(13.4 * math.cos(delta / 2), 13.4 * math.sin(delta / 2), r"$\Delta$",
            color=C_GREEN, fontsize=13)
    ax.add_patch(Arc((0, 0), 2 * 21, 2 * 21, theta1=g["delta_deg"],
                     theta2=g["delta_deg"] + 30, color=C_RED, lw=1.6))
    ax.text(21.6 * math.cos(delta + th / 2), 21.6 * math.sin(delta + th / 2), r"$\theta$",
            color=C_RED, fontsize=13)

    ax.annotate("固定端 A（P4）", A, xytext=(A[0] - 1, A[1] - 7.2), fontsize=9.5, color=C_BLUE,
                arrowprops=dict(arrowstyle="-", color=C_BLUE, lw=0.7))
    ax.annotate("动端 $B_0$（P5，零位）", B0, xytext=(39, 7.0), fontsize=9.5, color="#7030A0",
                arrowprops=dict(arrowstyle="-", color="#7030A0", lw=0.7))
    ax.annotate("B(θ)", B1, xytext=(B1[0] + 1.5, B1[1] + 1.0), fontsize=9.5, color="#7030A0")
    ax.text((A[0] + B1[0]) / 2 + 1.5, (A[1] + B1[1]) / 2 + 2.5, "s(θ)", color=C_ORANGE, fontsize=10)
    ax.text(0.55 * a, -4.0, "a", color=C_BLUE, fontsize=10)
    ax.text(0.5 * b * math.cos(delta) + 1.5, 0.5 * b * math.sin(delta) + 1.2, "b",
            color="#7030A0", fontsize=10)
    ax.set_aspect("equal")
    ax.set_xlim(-10, 62)
    ax.set_ylim(-12, 44)
    ax.set_xlabel("$e_1=+X$  / mm")
    ax.set_ylabel("$e_2=-Z$  / mm")
    ax.set_title("(a) 沿 +Y 看：C2 / roll 段的平面几何（零位 + 转 30°）", loc="left")
    ax.legend(loc="upper left", fontsize=7.8, framealpha=0.9)
    ax.grid(False)

    # (b) h correction triangle
    ax2 = fig.add_subplot(1, 2, 2)
    d0 = np.linalg.norm(B0 - A)
    p0 = np.array([0.0, 0.0])
    p1 = np.array([d0, 0.0])
    p2 = np.array([d0, h])
    ax2.plot([p0[0], p1[0]], [p0[1], p1[1]], color=C_ORANGE, lw=2.4)
    ax2.plot([p1[0], p2[0]], [p1[1], p2[1]], color=C_GRAY, lw=1.4, ls="--")
    ax2.plot([p0[0], p2[0]], [p0[1], p2[1]], color=C_RED, lw=2.4)
    ax2.plot(*p0, "o", color=C_BLUE, ms=6)
    ax2.plot(*p2, "o", color=C_RED, ms=6)
    ax2.text(d0 / 2, -1.4, r"平面内距离 $d_0$", ha="center", va="top", color=C_ORANGE)
    ax2.text(d0 + 0.8, h / 2, r"$h=4.00$ mm", color=C_GRAY, va="center")
    ax2.text(d0 / 2 - 1.0, h / 2 + 1.2, r"$s=\sqrt{d_0^2+h^2}$", color=C_RED,
             ha="right", va="center")
    ax2.text(0.5, 0.92, "轴向错开 h 不参与平面转角，\n只把长度平方加一个常数项。",
             transform=ax2.transAxes, ha="center", fontsize=9.5,
             bbox=dict(boxstyle="round,pad=0.4", fc="#FFF2CC", ec="#D6B656", lw=0.8))
    ax2.set_xlim(-4, d0 + 8)
    ax2.set_ylim(-7, max(h + 5, 10))
    ax2.set_aspect("equal")
    ax2.set_xlabel("沿绳的平面投影 / mm")
    ax2.set_ylabel("沿轴 / mm")
    ax2.set_title("(b) 轴向错位只加 $h^2$", loc="left")
    ax2.grid(False)

    fig.tight_layout()
    fig.savefig(FIG / "fig1_geometry.png", bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ fig 2 R vs angle
def fig_curves():
    roll = np.linspace(-25, 25, 401)
    pitch = np.linspace(-25, 45, 501)
    Rr = np.array([model_R(seg, t * DEG, 0.0)[0] for t in roll]) * 1e3
    Rp = np.array([model_R(seg, 0.0, t * DEG)[1] for t in pitch]) * 1e3

    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.4))
    ax = axes[0]
    for i, (c, col) in enumerate(zip(("C1", "C2", "C3"), (C_BLUE, C_RED, C_GREEN))):
        ax.plot(roll, Rr[:, i], color=col, lw=2.0, label=c)
        ax.plot(0, Rr[np.argmin(np.abs(roll)), i], "o", color=col, ms=5)
    ax.axhline(0, color="k", lw=0.8)
    ax.axvline(0, color=C_GRAY, lw=0.8, ls=":")
    ax.set_xlabel("roll 角 θr / °")
    ax.set_ylabel("力臂 r / mm")
    ax.set_title("(a) R 的 roll 行：只随 θr 变", loc="left")
    ax.legend(loc="best", fontsize=9)

    ax = axes[1]
    for i, (c, col) in enumerate(zip(("C1", "C2", "C3"), (C_BLUE, C_RED, C_GREEN))):
        ax.plot(pitch, Rp[:, i], color=col, lw=2.0, label=c)
        ax.plot(0, Rp[np.argmin(np.abs(pitch)), i], "o", color=col, ms=5)
    ax.axhline(0, color="k", lw=0.8)
    ax.axvline(0, color=C_GRAY, lw=0.8, ls=":")
    ax.axvspan(-25, -24, color="#F4CCCC", alpha=0.55, lw=0, label="低置信区 ≤ −24°")
    ax.set_xlabel("pitch 角 θp / °")
    ax.set_ylabel("力臂 r / mm")
    ax.set_title("(b) R 的 pitch 行：只随 θp 变", loc="left")
    ax.legend(loc="best", fontsize=8.4)
    ax.annotate("C1 在 −25° 只剩 −9.55 mm\n（短段，力臂变化最快）", xy=(-25, Rp[0, 0]),
                xytext=(-22, -30),
                fontsize=8.4, color=C_BLUE,
                arrowprops=dict(arrowstyle="->", lw=0.7, color=C_BLUE))

    fig.tight_layout()
    fig.savefig(FIG / "fig2_R_curves.png", bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ fig 3 error chain
def fig_errors():
    items = [
        ("5 常数 vs 3D 链式雅可比（double，3621 姿态）", 4.34e-12, C_GREEN),
        ("段长 vs CAD 表（double，3621 姿态）", 2.69e-11, C_GREEN),
        ("float32 vs double（9224 姿态，本文复算）", 6.32e-5, C_BLUE),
        ("float32 vs double（H7 官方 9249 姿态）", 4.67e-5, C_BLUE),
        ("CAD 表 vs 解析式：内部点（0.2° 中心差分）", 2.53e-2, C_ORANGE),
        ("CAD 表 vs 解析式：pitch=−25° 边界（二阶单边）", 3.27e-2, C_RED),
    ]
    fig, ax = plt.subplots(figsize=(11.4, 4.2))
    y = np.arange(len(items))
    vals = [v for _, v, _ in items]
    ax.barh(y, vals, color=[c for _, _, c in items], height=0.55)
    ax.set_xscale("log")
    ax.set_xlim(1e-13, 3e-1)
    ax.axvline(1e-3, color="k", ls="--", lw=1.2)
    ax.text(1.25e-3, -0.62, "软件验收线 0.001 mm",
            va="bottom", fontsize=8.6, bbox=dict(fc="white", ec="none", pad=1.0))
    for yi, v in zip(y, vals):
        ax.text(v * 1.18, yi, f"{v:.2e}", va="center", fontsize=8.8,
                bbox=dict(fc="white", ec="none", pad=0.8))
    ax.set_yticks(y)
    ax.set_yticklabels([n for n, _, _ in items], fontsize=9)
    ax.invert_yaxis()
    ax.set_ylim(len(items) - 0.35, -1.05)
    ax.set_xlabel("最大绝对误差 / mm（对数坐标）")
    ax.set_title("误差链：模型代数精确；差异来自 float32 与参考表的差分截断", loc="left")
    ax.grid(True, axis="x", which="both", alpha=0.25)

    fig.tight_layout()
    fig.savefig(FIG / "fig3_error_chain.png", bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ fig 4 workspace
def fig_workspace():
    rolls = np.arange(-25, 25.001, 1.0)
    pitches = np.arange(-25, 45.001, 1.0)
    cond = np.zeros((len(pitches), len(rolls)))
    pos = np.zeros_like(cond)
    for j, pd in enumerate(pitches):
        for i, rd in enumerate(rolls):
            R = model_R(seg, rd * DEG, pd * DEG)
            cond[j, i] = condition(R)
            n, _ = null_vector(R)
            pos[j, i] = 1.0 if (n is not None and np.all(n > 1e-6)) else 0.0

    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.6), gridspec_kw={"width_ratios": [1.05, 1]})
    ax = axes[0]
    im = ax.pcolormesh(rolls, pitches, cond, shading="auto", cmap="viridis",
                       vmin=1.0, vmax=3.3)
    cs = ax.contour(rolls, pitches, cond, levels=[2.0, 2.5, 3.0], colors="white",
                    linewidths=0.7, alpha=0.75)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%.1f")
    tr = np.loadtxt(OUT / "trajectory.csv", delimiter=",", skiprows=1)
    ax.plot(tr[:, 1], tr[:, 2], color="white", lw=1.2, ls="--", alpha=0.9,
            label="示例轨迹（2 s）")
    ax.legend(loc="lower right", fontsize=8, framealpha=0.85)
    ax.set_xlabel("roll θr / °")
    ax.set_ylabel("pitch θp / °")
    ax.set_title("(a) 条件数 $\\kappa_2(R)$：1.08–3.16，无奇异", loc="left")
    cb = fig.colorbar(im, ax=ax, pad=0.02)
    cb.set_label("$\\kappa_2$", fontsize=9)
    ax.grid(False)

    ax = axes[1]
    cmap = ListedColormap(["#E6B8B7", "#C6E0B4"])
    ax.pcolormesh(rolls, pitches, pos, shading="auto", cmap=cmap, vmin=0, vmax=1)
    ax.set_xlabel("roll θr / °")
    ax.set_ylabel("pitch θp / °")
    ax.set_title("(b) 是否存在全正零空间方向（预紧方向）", loc="left")
    ax.text(-23.5, 41.5, "绿色：存在  n>0\n红色：不存在（1664/3621）", fontsize=8.8,
            va="top", bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#999999", lw=0.7))
    ax.grid(False)

    fig.tight_layout()
    fig.savefig(FIG / "fig4_workspace.png", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_geometry()
    fig_curves()
    fig_errors()
    fig_workspace()
    print("figures written to", FIG)




