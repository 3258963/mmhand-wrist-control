"""为什么会有"容量"——用三根绳的条形图讲清楚。

一句话：要拧出 τ 的力矩，三根绳的张力就被唯一确定了；如果算出来某根绳
**需要 0.5 N 以下（甚至负数）**，那就是"绳要推"——物理上做不到。

条形图里：绿=绳能拉到（≥ f_min）、红=算出来低于 f_min（不可能）。
**"容量" = 刚好让某根绳掉到 0.5 N 的那个 τ。**

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.gen_why_capacity
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import matplotlib.gridspec as gridspec  # noqa: E402
import numpy as np  # noqa: E402

from tools._figbase import GRID, INK, MUTED, plt  # noqa: E402
from wrist_model import ROLL, PITCH, positive_null_direction, wrist_eval  # noqa: E402
from wrist_tda import tda_solve  # noqa: E402

OK_C, BAD_C, FMIN_C = "#10b981", "#ef4444", "#f59e0b"
FMIN, FMAX = 0.5, 25.0


def main(argv=None) -> int:
    out = Path(argv[0]) if argv else (_REPO_ROOT / "../../figs")
    out = out if out.is_absolute() else (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    o = wrist_eval(0.0, 0.0)
    n = np.array(positive_null_direction(0.0, 0.0))
    R = o.r_m
    P = np.array([R[ROLL], R[PITCH], list(n)])
    Pinv = np.linalg.inv(P)

    def f_of(tp, preload):
        return Pinv @ np.array([0.0, tp, float(preload)])

    def cap(preload, axis):
        lo, hi = 0.0, 1.5
        for _ in range(45):
            mid = 0.5 * (lo + hi)
            tau = (mid, 0.0) if axis == 0 else (0.0, mid)
            f, fl, a = tda_solve(R, n, tau[0], tau[1], preload, FMIN, FMAX)
            if f is not None and a >= 1 - 1e-12:
                lo = mid
            else:
                hi = mid
        return lo

    cases = [
        (5.0, 0.000, "预紧 5 N，不拧（τ=0）"),
        (5.0, 0.030, "预紧 5 N，拧 0.030 N·m"),
        (5.0, 0.100, "预紧 5 N，拧 0.100 N·m"),
        (15.0, 0.000, "预紧 15 N，不拧（τ=0）"),
        (15.0, 0.100, "预紧 15 N，拧 0.100 N·m"),
        (15.0, 0.220, "预紧 15 N，拧 0.220 N·m"),
    ]

    fig = plt.figure(figsize=(14.6, 8.2), dpi=165)
    gs = gridspec.GridSpec(3, 3, height_ratios=[1, 1, 1.25], hspace=0.62, wspace=0.26)
    labels = ["绳1 (C1)", "绳2 (C2)", "绳3 (C3)"]

    for k, (pl, tp, title) in enumerate(cases):
        ax = fig.add_subplot(gs[k // 3, k % 3])
        f = f_of(tp, pl)
        colors = [OK_C if v >= FMIN else BAD_C for v in f]
        bars = ax.bar(labels, f, color=colors, width=0.62, zorder=3)
        ax.axhline(FMIN, color=FMIN_C, lw=1.6, ls="--", zorder=4)
        ax.axhline(0.0, color=INK, lw=0.9, zorder=4)
        ax.axhline(FMAX, color=MUTED, lw=0.8, ls=":", zorder=2)
        ymax = max(FMAX, float(np.max(f)) * 1.15)
        ax.set_ylim(min(-1.2, float(np.min(f)) - 0.6), ymax if k // 3 == 0 else 16)
        ax.set_ylabel("张力 (N)", fontsize=8, color=INK)
        for b, v in zip(bars, f):
            ax.text(b.get_x() + b.get_width() / 2,
                    v + (0.25 if v >= 0 else -0.55),
                    f"{v:+.2f}", ha="center",
                    va="bottom" if v >= 0 else "top",
                    fontsize=8.2, color=INK, fontweight="bold")
        bad = [i for i in range(3) if f[i] < FMIN]
        note = ("可以：三根绳都拉得住" if not bad
                else f"不行：绳{'/'.join(str(i + 1) for i in bad)} 要 "
                     + f"{min(f):+.2f} N（绳不能推）")
        ax.set_title(f"{title}\n{note}", fontsize=8.8,
                     color=INK if not bad else BAD_C)
        ax.tick_params(labelsize=7.5)
        ax.grid(axis="y", color=GRID, lw=0.5, zorder=0)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        if k == 0:
            ax.text(0.02, 0.97, "黄虚线 = 绳的最小张力 0.5 N\n（再低就等于松了）",
                    transform=ax.transAxes, fontsize=7, color=FMIN_C, va="top")

    # ---------- 底部：容量 = "刚好让最松那根掉到 0.5 的 τ" ----------
    ax = fig.add_subplot(gs[2, :])
    ps = np.arange(1.0, 25.01, 0.5)
    cr = np.array([cap(p, 0) for p in ps])
    cp = np.array([cap(p, 1) for p in ps])
    ax.plot(ps, cr, color="#3b82f6", lw=2.2, label="roll 方向能拧多大力矩")
    ax.plot(ps, cp, color="#8b5cf6", lw=2.2, label="pitch 方向能拧多大力矩")
    for p, c in ((5.0, INK), (15.0, INK)):
        ax.axvline(p, color=c, lw=0.9, ls=":", alpha=0.6)
        ax.text(p, 0.02, f"预紧 {p:g} N", fontsize=7.6, rotation=90,
                va="bottom", ha="right", color=MUTED)
    ax.annotate("预紧太小\n绳没余量 → 拧不动", xy=(2.5, 0.02), xytext=(3.0, 0.24),
                fontsize=8.2, color=BAD_C,
                arrowprops=dict(arrowstyle="->", color=BAD_C, lw=0.9))
    ax.annotate("预紧太大\n绳子贴着 25 N 上限\n→ 又拧不动了", xy=(24.0, 0.30),
                xytext=(18.6, 0.10), fontsize=8.2, color=BAD_C,
                arrowprops=dict(arrowstyle="->", color=BAD_C, lw=0.9))
    ax.annotate("最胖的位置\n预紧 ≈ 18~20 N", xy=(19.5, 0.40),
                xytext=(11.5, 0.40), fontsize=8.2, color=OK_C,
                arrowprops=dict(arrowstyle="->", color=OK_C, lw=0.9))
    ax.set_xlabel("预紧 preload (N) —— 绳子整体绷多紧", fontsize=9, color=INK)
    ax.set_ylabel("能拧出的最大力矩 (N·m)", fontsize=9, color=INK)
    ax.set_title("这条曲线就是「容量」：三根绳刚好全都不低于 0.5 N 的那个力矩",
                 fontsize=10, color=INK)
    ax.grid(color=GRID, lw=0.6)
    ax.legend(fontsize=8.5, loc="upper left")
    ax.set_xlim(0, 25.5)
    ax.set_ylim(0, 0.47)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)

    path = out / "why_capacity.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {path}  {path.stat().st_size/1024:.0f} KB")
    print(f"  容量: preload=5 → roll {cap(5,0):.3f} / pitch {cap(5,1):.3f} N·m")
    print(f"        preload=15 → roll {cap(15,0):.3f} / pitch {cap(15,1):.3f} N·m")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
