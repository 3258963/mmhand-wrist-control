# -*- coding: utf-8 -*-
"""Two figures for the focused dynamic-R note: why it matters, and the pipeline."""
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from verify_dynamic_R import DEG, load_model, model_R

ROOT = Path(__file__).resolve().parent
FIG = ROOT / "out" / "figs"
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Deng"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11
plt.rcParams["axes.titlesize"] = 12.5
plt.rcParams["axes.labelsize"] = 11
plt.rcParams["figure.dpi"] = 200
plt.rcParams["savefig.dpi"] = 200

C_BLUE = "#2F5597"
C_RED = "#C00000"
C_GREEN = "#2E7D32"
C_ORANGE = "#C55A11"
C_GRAY = "#666666"

dc, seg, mp = load_model()


def fig_why():
    roll = np.linspace(-25, 25, 501)
    pitch = np.linspace(-25, 45, 601)
    rr = np.array([model_R(seg, t * DEG, 0.0)[0][1] for t in roll]) * 1e3
    rp = np.array([model_R(seg, 0.0, t * DEG)[1][0] for t in pitch]) * 1e3
    r0_roll = model_R(seg, 0.0, 0.0)[0][1] * 1e3
    r0_pitch = model_R(seg, 0.0, 0.0)[1][0] * 1e3

    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.5))
    ax = axes[0]
    ax.fill_between(roll, rr, r0_roll, color=C_RED, alpha=0.13, lw=0)
    ax.plot(roll, rr, color=C_RED, lw=2.4, label="真实 r(θ)，随位姿变")
    ax.axhline(r0_roll, color=C_BLUE, lw=1.8, ls="--", label="零位常数 r(0)")
    ax.axhline(0, color="k", lw=0.8)
    ax.axvline(0, color=C_GRAY, lw=0.7, ls=":")
    ax.plot(0, r0_roll, "o", color=C_BLUE, ms=5)
    ax.plot(-25, rr[0], "o", color=C_RED, ms=6)
    ax.plot(25, rr[-1], "o", color=C_RED, ms=6)
    ax.annotate("−25°：真实 +10.43\n常数 −22.05 → 方向反",
                xy=(-25, rr[0]), xytext=(-21.0, 8.0), fontsize=8.6, color=C_RED,
                arrowprops=dict(arrowstyle="->", lw=0.8, color=C_RED))
    ax.annotate("+25°：真实 −27.12\n常数 −22.05，差 5.07",
                xy=(25, rr[-1]), xytext=(2.0, -31.5), fontsize=8.6, color=C_RED,
                arrowprops=dict(arrowstyle="->", lw=0.8, color=C_RED))
    ax.set_xlabel("roll 角 θr / °")
    ax.set_ylabel("C2 对 roll 的力臂 r / mm")
    ax.set_ylim(-34, 12)
    ax.set_title("(a) C2 / roll：力臂穿过零点，常数 R 会反号", loc="left")
    ax.legend(loc="lower left", fontsize=8.5, framealpha=0.9)
    ax.grid(alpha=0.25, ls="--")

    ax = axes[1]
    ax.fill_between(pitch, rp, r0_pitch, color=C_RED, alpha=0.13, lw=0)
    ax.plot(pitch, rp, color=C_GREEN, lw=2.4, label="真实 r(θ)，随位姿变")
    ax.axhline(r0_pitch, color=C_BLUE, lw=1.8, ls="--", label="零位常数 r(0)")
    ax.axhline(0, color="k", lw=0.8)
    ax.axvline(0, color=C_GRAY, lw=0.7, ls=":")
    ax.plot(0, r0_pitch, "o", color=C_BLUE, ms=5)
    ax.plot(-25, rp[0], "o", color=C_GREEN, ms=6)
    ax.annotate("−25°：真实 −9.55\n零位 −58.10，差 48.55",
                xy=(-25, rp[0]), xytext=(-19.0, -4.0), fontsize=8.6, color=C_GREEN,
                arrowprops=dict(arrowstyle="->", lw=0.8, color=C_GREEN))
    ax.set_xlabel("pitch 角 θp / °")
    ax.set_ylabel("C1 对 pitch 的力臂 r / mm")
    ax.set_title("(b) C1 / pitch：短段力臂只剩零位的约 1/6", loc="left")
    ax.legend(loc="upper right", fontsize=8.5, framealpha=0.9)
    ax.grid(alpha=0.25, ls="--")

    fig.tight_layout()
    fig.savefig(FIG / "fig_why_dynamic.png", bbox_inches="tight")
    plt.close(fig)


def fig_flow():
    fig, ax = plt.subplots(figsize=(10.0, 2.7))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    boxes = [
        (0.01, "CAD\n24 点 + 轴线", "#EAF1FB", "#2F5597"),
        (0.205, "30 个常数\n6 段 × 5", "#EAF1FB", "#2F5597"),
        (0.40, "每周期\n6 × (s, r)", "#E8F5E9", "#2E7D32"),
        (0.595, "R\n2 × 3", "#E8F5E9", "#2E7D32"),
        (0.79, "τ = R f\n张力分配", "#FFF3E0", "#C55A11"),
    ]
    w, h, y = 0.16, 0.38, 0.36
    centers = []
    for x, text, fc, ec in boxes:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.010,rounding_size=0.012",
                                    fc=fc, ec=ec, lw=1.6))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=11.2, color="#16202e")
        centers.append((x, x + w))

    for i in range(len(boxes) - 1):
        ax.annotate("", xy=(centers[i + 1][0] - 0.008, y + h / 2),
                    xytext=(centers[i][1] + 0.008, y + h / 2),
                    arrowprops=dict(arrowstyle="->", lw=1.8, color="#555555"))

    ax.text(0.10, 0.90, "离线一次", ha="center", fontsize=10.5, color="#2F5597")
    ax.text(0.54, 0.90, "在线每周期（1 kHz）", ha="center", fontsize=10.5, color="#2E7D32")
    ax.plot([0.012, 0.37], [0.85, 0.85], color="#2F5597", lw=1.2)
    ax.plot([0.39, 0.96], [0.85, 0.85], color="#2E7D32", lw=1.2)

    ax.text(0.5, 0.10, "30 个 float　|　2 次 sin + 2 次 cos　|　6 次 sqrt　|　无查表、无迭代",
            ha="center", fontsize=10.0, color="#555555",
            bbox=dict(boxstyle="round,pad=0.40", fc="#F7F8FA", ec="#D0D7DE", lw=0.8))

    fig.tight_layout()
    fig.savefig(FIG / "fig_flow.png", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_why()
    fig_flow()
    print("wrote", FIG / "fig_why_dynamic.png", FIG / "fig_flow.png")





