"""P2 的 3D 版本：容量鼓包 vs 外环膝盖（z 轴 = preload）。

读法：
  · z 轴 = 预紧 preload（N）；每个高度上，横截面是 (τ_roll, τ_pitch) 平面。
  · **彩色曲面 = 容量**：在该 preload 下，TDA 还能给到 α=1 的最大力矩边界。
    preload 小 → 截面小（贴着盒子边）；preload 中 → 鼓出来；preload 太大 → 又缩回去
    （因为三缆已经贴近 f_max，没有往上加的空间）。
  · **灰色虚线棱柱 = 外环膝盖**：|τ| ≤ lim/Kp_τ 的盒子。它是"控制器还留有多少
    比例作用"的边界，与 preload 无关，所以是一个竖直的盒子。
  · **谁在外面谁说了算**：
      膝盖盒子在曲面**里面** → 控制器先饱和（增益失效，P2 的 roll 侧）
      膝盖盒子**戳出**曲面   → 物理先到（α<1，力矩打折，P2 的 pitch 侧）

用法：
    .venv\\Scripts\\python.exe -m tools.gen_torque_capacity_3d
    .venv\\Scripts\\python.exe -m tools.gen_torque_capacity_3d --out ../../figs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import matplotlib

import numpy as np  # noqa: E402
from matplotlib import cm  # noqa: E402
from mpl_toolkits.mplot3d import Axes3D  # noqa: E402,F401

from tools._figbase import plt  # noqa: E402
from wrist_model import ROLL, PITCH, positive_null_direction, wrist_eval  # noqa: E402
from wrist_tda import tda_solve  # noqa: E402

INK, MUTED, BLUE, PURPLE, RED = "#24303f", "#6b7785", "#3b82f6", "#8b5cf6", "#ef4444"
FMIN, FMAX = 0.5, 25.0


def capacity_radius(R, n, preload, theta, fmin, fmax, tol=1e-10, iters=42):
    """沿单位方向 (cosθ, sinθ) 二分找 α=1 的最大 |τ|。"""
    lo, hi = 0.0, 2.5
    def ok(r):
        tr, tp = r * np.cos(theta), r * np.sin(theta)
        f, fl, a = tda_solve(R, n, tr, tp, preload, fmin, fmax)
        return f is not None and a >= 1.0 - 1e-12
    if not ok(1e-6):
        return 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if ok(mid):
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return lo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../../figs")
    ap.add_argument("--fmin", type=float, default=FMIN)
    ap.add_argument("--fmax", type=float, default=FMAX)
    args = ap.parse_args(argv)

    out = Path(args.out)
    if not out.is_absolute():
        out = (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    o = wrist_eval(0.0, 0.0)
    n = np.array(positive_null_direction(0.0, 0.0))
    R = o.r_m
    lim_r = (args.fmax - args.fmin) * sum(abs(v) for v in R[ROLL])
    lim_p = (args.fmax - args.fmin) * sum(abs(v) for v in R[PITCH])

    preloads = np.linspace(2.0, 25.0, 17)
    thetas = np.linspace(0, 2 * np.pi, 49)

    # 容量曲面
    Rr = np.zeros((len(preloads), len(thetas)))
    for i, p in enumerate(preloads):
        for j, th in enumerate(thetas):
            Rr[i, j] = capacity_radius(R, n, p, th, args.fmin, args.fmax)
    Z = np.repeat(preloads[:, None], len(thetas), axis=1)
    X = Rr * np.cos(thetas)[None, :]      # τ_roll
    Y = Rr * np.sin(thetas)[None, :]      # τ_pitch

    fig = plt.figure(figsize=(13.2, 6.4), dpi=165)

    # ---- 两个面板：Kp=20（现在） vs Kp=3（建议） ----
    for k, (kp, title) in enumerate(((20.0, "现在 Kp_τ=20"),
                                     (3.0, "建议 Kp_τ=3"))):
        ax = fig.add_subplot(1, 2, k + 1, projection="3d")
        surf = ax.plot_surface(X, Y, Z, cmap="viridis", alpha=0.5,
                               linewidth=0, antialiased=True, rstride=1, cstride=1)
        ax.plot_wireframe(X[::2, ::4], Y[::2, ::4], Z[::2, ::4],
                          color="#132a3a", alpha=0.18, linewidth=0.3)
        # 膝盖棱柱（|τ| ≤ lim/Kp），竖直，与 preload 无关 —— 亮橙实线
        kr, kp_ = lim_r / kp, lim_p / kp
        z0, z1 = preloads[0], preloads[-1]
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            ax.plot([sx * kr, sx * kr], [sy * kp_, sy * kp_], [z0, z1],
                    color="#f97316", lw=1.6, zorder=12)
        for zz in (z0, z1):
            ax.plot([-kr, kr, kr, -kr, -kr], [-kp_, -kp_, kp_, kp_, -kp_],
                    [zz] * 5, color="#f97316", lw=1.6, zorder=12)
        # preload=5 的容量截面（红）与膝盖截面（橙虚线）—— 直接比大小
        i5 = int(np.argmin(np.abs(preloads - 5.0)))
        ax.plot(X[i5], Y[i5], Z[i5], color=RED, lw=2.4, zorder=13)
        ax.plot([-kr, kr, kr, -kr, -kr], [-kp_, -kp_, kp_, kp_, -kp_],
                [preloads[i5]] * 5, color="#f97316", lw=2.0, ls=":", zorder=13)
        cap_r5 = capacity_radius(R, n, 5.0, 0.0, args.fmin, args.fmax)
        cap_p5 = capacity_radius(R, n, 5.0, np.pi / 2, args.fmin, args.fmax)
        ax.text2D(0.02, 0.97,
                  f"preload=5 截面（红线）\n"
                  f"roll 容量 {cap_r5:.3f} vs 膝盖 {kr:.3f} → "
                  f"{'控制器先顶' if kr < cap_r5 else '物理先顶'}\n"
                  f"pitch 容量 {cap_p5:.3f} vs 膝盖 {kp_:.3f} → "
                  f"{'控制器先顶' if kp_ < cap_p5 else '物理先顶'}",
                  transform=ax.transAxes, fontsize=7.2, color=INK, va="top",
                  bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#dfe4ea",
                            alpha=0.9))
        ax.set_xlabel("$\\tau_{roll}$ (N·m)", color=INK, fontsize=8, labelpad=-2)
        ax.set_ylabel("$\\tau_{pitch}$ (N·m)", color=INK, fontsize=8, labelpad=-2)
        ax.set_zlabel("preload (N)", color=INK, fontsize=8, labelpad=-2)
        ax.set_title(f"{title}：彩色曲面=容量  橙盒=膝盖\n"
                     f"盒子在曲面内=控制器先顶；盒子戳出去=物理先顶",
                     color=INK, fontsize=9.6)
        ax.tick_params(labelsize=6.5)
        ax.view_init(elev=16, azim=-62)
        ax.set_xlim(-0.46, 0.46); ax.set_ylim(-0.46, 0.46)
        ax.set_zlim(2, 25)

    fig.tight_layout()
    path = out / "torque_capacity_3d.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # 打印几个高度上的对比（文字版）
    print(f"  {path}  {path.stat().st_size/1024:.0f} KB")
    for p in (5.0, 15.0):
        i = int(np.argmin(np.abs(preloads - p)))
        cr = capacity_radius(R, n, p, 0.0, args.fmin, args.fmax)           # roll
        cp = capacity_radius(R, n, p, np.pi / 2, args.fmin, args.fmax)     # pitch
        print(f"  preload={p:5.1f}  容量 roll={cr:.3f} pitch={cp:.3f}")
    for kp in (20.0, 3.0):
        print(f"  Kp_τ={kp:5.1f}  膝盖 roll={lim_r/kp:.3f} pitch={lim_p/kp:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
