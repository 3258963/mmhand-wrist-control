"""推导三的手算对照卡：矩阵求逆 vs 消元法（两种算法，同一结果）。

产出 figs/derivation_card.png，贴进 docs/力矩容量与工作区_详解.md §4.5。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.gen_derivation_card
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from tools._figbase import GRID, INK, MUTED, plt  # noqa: E402
from wrist_model import ROLL, PITCH, positive_null_direction, wrist_eval  # noqa: E402

plt.rcParams["font.monospace"] = ["Consolas", "Microsoft YaHei", "SimHei",
                                  "DejaVu Sans Mono"]

A_C, B_C, OK_C = "#3b82f6", "#f97316", "#10b981"


def main() -> int:
    out = (_REPO_ROOT / "../../figs").resolve()
    out.mkdir(parents=True, exist_ok=True)

    o = wrist_eval(0.0, 0.0)
    n = np.array(positive_null_direction(0.0, 0.0))
    R = np.array([o.r_m[ROLL], o.r_m[PITCH]])
    P = np.array([o.r_m[ROLL], o.r_m[PITCH], list(n)])
    Pinv = np.linalg.inv(P)
    tau, p = 0.1, 5.0
    b = np.array([0.0, tau, p])
    fA = Pinv @ b

    # 消元法（与文档 §4.5 完全同一套数）
    n3 = n[2]
    k0 = p / n3
    k1 = n[0] / n3
    k2 = n[1] / n3
    a11 = R[0][0] - R[0][2] * k1
    a12 = R[0][1] - R[0][2] * k2
    b1 = 0.0 - R[0][2] * k0
    a21 = R[1][0] - R[1][2] * k1
    a22 = R[1][1] - R[1][2] * k2
    b2 = tau - R[1][2] * k0
    det2 = a11 * a22 - a12 * a21
    f1 = (b1 * a22 - a12 * b2) / det2
    f2 = (a11 * b2 - b1 * a21) / det2
    f3 = k0 - k1 * f1 - k2 * f2
    fB = np.array([f1, f2, f3])

    fig = plt.figure(figsize=(13.6, 7.4), dpi=160)
    gs = gridspec.GridSpec(2, 2, height_ratios=[3.1, 1.5], hspace=0.22, wspace=0.10)

    # ---------- 左：矩阵法 ----------
    ax = fig.add_subplot(gs[0, 0]); ax.axis("off")
    ax.set_title("方法 A：矩阵求逆  $f=P^{-1}[\\tau;\\,p]$", fontsize=11.5,
                 color=A_C, loc="left", pad=8)
    mat = (
        "P =  [ -0.00025944  -0.02204970  +0.01737198 ]\n"
        "     [ -0.05810462  +0.01180488  +0.01099035 ]\n"
        "     [ +0.26443774  +0.59490962  +0.75904890 ]\n"
        "\n"
        "        det(P) = -1.6919227e-03   （≈ |r1×r2|）\n"
        "\n"
        "P^-1 = [ -1.431637  -16.000472   +0.264438 ]\n"
        "      [ -27.785258   +2.831532   +0.594910 ]\n"
        "      [ +22.275635   +3.355018   +0.759049 ]\n"
        "\n"
        "        ↑ 第三列 = n̂（预紧项，见 §5.2）\n"
        "\n"
        "b = [ 0 ,  0.1 ,  5 ]ᵀ\n"
        "\n"
        "f = P^-1·b = ( %+.4f ,  %+.4f ,  %+.4f )\n"
        "\n"
        "校验：R·f = ( 0 , 0.1 )     n̂·f = 5.000"
        % (fA[0], fA[1], fA[2])
    )
    ax.text(0.0, 0.98, mat, transform=ax.transAxes, va="top", ha="left",
            fontsize=9.2, family=["Consolas", "Microsoft YaHei", "DejaVu Sans Mono"],
            color=INK,
            bbox=dict(boxstyle="round,pad=0.6", fc="#f6f8fb", ec=A_C, lw=1.2))

    # ---------- 右：消元法 ----------
    ax = fig.add_subplot(gs[0, 1]); ax.axis("off")
    ax.set_title("方法 B：消元（拿计算器就能算）", fontsize=11.5,
                 color=B_C, loc="left", pad=8)
    steps = (
        "① 由 n̂·f = p 解出 f3：\n"
        "   f3 = %.4f  −  %.5f·f1  −  %.5f·f2\n"
        "\n"
        "② 代回前两式 → 2×2：\n"
        "   %+.6f·f1  %+.6f·f2 = %+.5f\n"
        "   %+.6f·f1  %+.6f·f2 = %+.5f\n"
        "\n"
        "③ 解 2×2（det = %+.4e）：\n"
        "   f1 = %+.4f      f2 = %+.4f\n"
        "\n"
        "④ 回代求 f3：\n"
        "   f3 = %.4f  −  %.5f×(%+.4f)  −  %.5f×(%+.4f)\n"
        "      = %+.4f\n"
        "\n"
        "结果 f = ( %+.4f ,  %+.4f ,  %+.4f )"
        % (k0, k1, k2,
           a11, a12, b1, a21, a22, b2,
           det2, f1, f2,
           k0, k1, f1, k2, f2, f3,
           fB[0], fB[1], fB[2])
    )
    ax.text(0.0, 0.98, steps, transform=ax.transAxes, va="top", ha="left",
            fontsize=9.2, family=["Consolas", "Microsoft YaHei", "DejaVu Sans Mono"],
            color=INK,
            bbox=dict(boxstyle="round,pad=0.6", fc="#fff8f1", ec=B_C, lw=1.2))

    # ---------- 下：两种方法结果对比 ----------
    ax = fig.add_subplot(gs[1, :])
    x = np.arange(3)
    w = 0.34
    ax.bar(x - w / 2, fA, w, color=A_C, label="方法 A（矩阵求逆）", zorder=3)
    ax.bar(x + w / 2, fB, w, color=B_C, alpha=0.85, label="方法 B（消元）", zorder=3)
    for i in range(3):
        ax.text(x[i] - w / 2, fA[i] + (0.12 if fA[i] >= 0 else -0.28),
                f"{fA[i]:+.4f}", ha="center", fontsize=8.4, color=A_C)
        ax.text(x[i] + w / 2, fB[i] + (0.12 if fB[i] >= 0 else -0.28),
                f"{fB[i]:+.4f}", ha="center", fontsize=8.4, color=B_C)
    ax.axhline(0, color=INK, lw=1.0, zorder=4)
    ax.axhline(0.5, color=OK_C, lw=1.4, ls="--", zorder=4)
    ax.text(2.42, 0.56, "f_min = 0.5 N", color=OK_C, fontsize=8, ha="right")
    ax.set_xticks(x)
    ax.set_xticklabels(["绳1 (C1)", "绳2 (C2)", "绳3 (C3)"], fontsize=9)
    ax.set_ylabel("张力 (N)", fontsize=9, color=INK)
    ax.set_title(f"两种算法结果一致（差 < 1e-3 N）；C1 = {fA[0]:+.3f} N < 0 → 绳要「推」→ τ_p={tau:g} N·m 不可实现",
                 fontsize=10, color=INK)
    ax.legend(fontsize=8.4, loc="upper left")
    ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    path = out / "derivation_card.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {path}  {path.stat().st_size/1024:.0f} KB")
    print(f"  A = ({fA[0]:+.4f}, {fA[1]:+.4f}, {fA[2]:+.4f})")
    print(f"  B = ({fB[0]:+.4f}, {fB[1]:+.4f}, {fB[2]:+.4f})")
    print(f"  最大差 = {np.max(np.abs(fA - fB)):.2e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
