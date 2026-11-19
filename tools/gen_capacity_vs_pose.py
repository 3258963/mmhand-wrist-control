"""力矩容量随【位姿】变化 —— 3D 曲面（附闭式解，可手算核对）。

核心：给定 (τ, preload)，三缆张力唯一确定
      f(τ) = c·τ + preload·n̂ ,   c = P⁻¹·[1,0,0]ᵀ 或 [0,1,0]ᵀ
套边界 fmin ≤ f_i ≤ fmax，逐缆解出 τ 的上下界，取最紧的那个 → 容量（闭式，O(3)）。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.gen_capacity_vs_pose
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d import Axes3D  # noqa: E402,F401

from tools._figbase import GRID, INK, MUTED, plt  # noqa: E402
from wrist_model import ROLL, PITCH, positive_null_direction, wrist_eval  # noqa: E402

BLUE, ORANGE, RED, GREEN = "#3b82f6", "#f97316", "#ef4444", "#10b981"
FMIN, FMAX = 0.5, 25.0


def capacity_closed(R, n, preload, axis, fmin=FMIN, fmax=FMAX):
    """沿 axis(0=roll,1=pitch) 方向的容量（闭式）。

    f(τ) = c·τ + preload·n̂；逐缆把 fmin ≤ f_i ≤ fmax 解成 τ 的区间，取交集。
    """
    P = np.array([R[ROLL], R[PITCH], list(n)])
    try:
        Pinv = np.linalg.inv(P)
    except np.linalg.LinAlgError:
        return 0.0
    e = np.zeros(3)
    e[axis] = 1.0
    c = Pinv @ e
    base = preload * np.asarray(n, dtype=float)
    lo, hi = 0.0, np.inf
    for i in range(3):
        ci, bi = c[i], base[i]
        if abs(ci) < 1e-12:
            if not (fmin - 1e-9 <= bi <= fmax + 1e-9):
                return 0.0
            continue
        a = (fmin - bi) / ci
        b = (fmax - bi) / ci
        if ci > 0:
            lo, hi = max(lo, a), min(hi, b)
        else:
            lo, hi = max(lo, b), min(hi, a)
    if not np.isfinite(hi) or hi < lo:
        return 0.0
    return max(0.0, float(hi))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../../figs")
    ap.add_argument("--step", type=float, default=1.0)
    args = ap.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    rolls = np.arange(-18.0, 15.01, args.step)
    pitches = np.arange(-25.0, 33.01, args.step)
    RR, PP = np.meshgrid(rolls, pitches)
    shape = RR.shape

    def grid(preload, axis):
        Z = np.full(shape, np.nan)
        for j in range(shape[0]):
            for i in range(shape[1]):
                o = wrist_eval(math.radians(RR[j, i]), math.radians(PP[j, i]))
                if not o.math_valid:
                    continue
                n = positive_null_direction(math.radians(RR[j, i]),
                                            math.radians(PP[j, i]))
                if n is None:
                    continue
                Z[j, i] = capacity_closed(o.r_m, n, preload, axis)
        return Z

    Z5r, Z5p = grid(5.0, 0), grid(5.0, 1)
    Z15r, Z15p = grid(15.0, 0), grid(15.0, 1)

    fig = plt.figure(figsize=(15.2, 6.4), dpi=160)
    for k, (Zl, Zh, name) in enumerate(((Z5r, Z15r, "roll"),
                                        (Z5p, Z15p, "pitch"))):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        for Z, col, lab in ((Zl, BLUE, "preload=5 N"),
                            (Zh, ORANGE, "preload=15 N")):
            ax.plot_surface(RR, PP, np.ma.masked_invalid(Z), color=col,
                            alpha=0.55, linewidth=0, rstride=2, cstride=2)
            ax.plot_wireframe(RR[::4, ::4], PP[::4, ::4],
                              np.ma.masked_invalid(Z[::4, ::4]),
                              color=col, linewidth=0.35, alpha=0.5)
        # 0.1 N·m 参考平面
        ax.plot_surface(RR, PP, np.full(shape, 0.1), color=GREEN, alpha=0.08,
                        linewidth=0)
        ax.set_xlabel("ROLL (°)", color=INK, fontsize=8, labelpad=-2)
        ax.set_ylabel("PITCH (°)", color=INK, fontsize=8, labelpad=-2)
        ax.set_zlabel(f"{name} 容量 (N·m)", color=INK, fontsize=8, labelpad=-2)
        ax.set_title(f"{name} 方向：能拧多大力矩 vs 位姿\n"
                     f"蓝=预紧 5 N，橙=预紧 15 N，绿平面=0.1 N·m 门槛",
                     color=INK, fontsize=10)
        ax.view_init(elev=26, azim=-58)
        ax.set_zlim(0, 0.50)
        ax.tick_params(labelsize=6.5)

    fig.tight_layout()
    path = out / "capacity_vs_pose.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # 打印关键点，顺便自检闭式解
    print(f"  {path}  {path.stat().st_size/1024:.0f} KB")
    print("  位姿        preload=5 roll/pitch    preload=15 roll/pitch")
    for rd, pd in ((0, 0), (10, 0), (-10, 0), (0, 20), (0, 30), (12, 5)):
        o = wrist_eval(math.radians(rd), math.radians(pd))
        n = positive_null_direction(math.radians(rd), math.radians(pd))
        if n is None:
            print(f"  ({rd:+3d},{pd:+3d})   n̂ 不存在")
            continue
        a = capacity_closed(o.r_m, n, 5.0, 0), capacity_closed(o.r_m, n, 5.0, 1)
        b = capacity_closed(o.r_m, n, 15.0, 0), capacity_closed(o.r_m, n, 15.0, 1)
        print(f"  ({rd:+3d},{pd:+3d})   {a[0]:.3f} / {a[1]:.3f}      "
              f"{b[0]:.3f} / {b[1]:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
