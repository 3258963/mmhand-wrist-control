"""P2 图解：张力空间 3D + 外环饱和曲线。

P2 的文字（"线性区 < 容量"）很难理解，几何上它其实是两件事：

  ① 张力空间里有个**盒子** `f_i ∈ [f_min, f_max]`；
  ② `R·f = τ`（两张平面）的交线是一条**直线**，方向恒为 n̂；
     `n̂·f = preload` 在线上挑一点 → 这个点必须落在盒子里，否则 TDA 打折（α<1）。
     这就是"容量"：τ 越大，直线平移越远，交点先跑出盒子；
  ③ 外环 `u = clamp(Kp·err, ±lim)` 的**饱和膝盖**在 `lim/Kp`。
     膝盖 < 容量 → 外环先饱和（增益失效）；膝盖 > 容量 → TDA 先打折。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.gen_torque_space_figure
    .venv\\Scripts\\python.exe -m tools.gen_torque_space_figure --preload 15 --kp-tau 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d import Axes3D  # noqa: E402,F401

from tools._figbase import GRID, INK, MUTED, plt  # noqa: E402
from wrist_model import ROLL, PITCH, positive_null_direction, wrist_eval  # noqa: E402
from wrist_tda import tda_solve  # noqa: E402

BLUE, GREEN, RED, AMBER, PURPLE = "#3b82f6", "#10b981", "#ef4444", "#f59e0b", "#8b5cf6"


def _box_edges(ax, fmin, fmax, color=MUTED, lw=0.9, alpha=0.75):
    r = [fmin, fmax]
    for i in range(8):
        for j in range(3):
            if not (i >> j) & 1:
                a = [r[(i >> k) & 1] for k in range(3)]
                b = list(a)
                b[j] = r[1 - ((i >> j) & 1)]
                ax.plot(*zip(a, b), color=color, lw=lw, alpha=alpha, zorder=1)


def _seg_in_box(base, n, fmin, fmax, s_lo=-20.0, s_hi=40.0, npts=400):
    ss = np.linspace(s_lo, s_hi, npts)
    pts = base[:, None] + n[:, None] * ss
    ok = np.all((pts >= fmin) & (pts <= fmax), axis=0)
    return pts, ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preload", type=float, default=5.0)
    ap.add_argument("--kp-tau", type=float, default=20.0)
    ap.add_argument("--fmin", type=float, default=0.5)
    ap.add_argument("--fmax", type=float, default=25.0)
    ap.add_argument("--out", default="../../figs")
    ap.add_argument("--tag", default="", help="输出文件名后缀（如 tuned）")
    args = ap.parse_args(argv)

    fmin, fmax = args.fmin, args.fmax
    out = Path(args.out)
    if not out.is_absolute():
        out = (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    o = wrist_eval(0.0, 0.0)
    n = np.array(positive_null_direction(0.0, 0.0))
    R = o.r_m
    P = np.array([R[ROLL], R[PITCH], list(n)])
    Pinv = np.linalg.inv(P)

    def f_tau(tr, tp):
        return Pinv @ np.array([tr, tp, 0.0])

    def alpha_of(tr, tp):
        f, fl, a = tda_solve(R, n, tr, tp, args.preload, fmin, fmax)
        return a if f is not None else float("nan")

    fig = plt.figure(figsize=(17.6, 6.0), dpi=160)

    # ================= (a) 零空间射线 + preload =================
    ax = fig.add_subplot(1, 3, 1, projection="3d")
    _box_edges(ax, fmin, fmax)
    s_max = fmax / n.max()
    s = np.linspace(0, s_max, 80)
    ax.plot(*(n[:, None] * s), color=BLUE, lw=2.4, zorder=5)
    for i, (p, c, ms) in enumerate(((2.0, MUTED, 30), (5.0, INK, 46), (10.0, INK, 46),
                                    (15.0, AMBER, 46), (20.0, INK, 46))):
        q = p * n
        ax.scatter(*q, color=c, s=ms, depthshade=False, zorder=8)
        dx = 0.8 if i % 2 == 0 else -2.6
        ax.text(q[0] + dx, q[1] + 0.5, q[2] + 0.9, f"p={p:g}", fontsize=8, color=c)
    ax.set_xlim(0, fmax); ax.set_ylim(0, fmax); ax.set_zlim(0, fmax)
    ax.view_init(elev=20, azim=34)
    ax.set_xlabel("$f_1$ (N)", color=INK, fontsize=8, labelpad=-4)
    ax.set_ylabel("$f_2$ (N)", color=INK, fontsize=8, labelpad=-4)
    ax.set_zlabel("$f_3$ (N)", color=INK, fontsize=8, labelpad=-4)
    ax.set_title("(a) $f=p\\,\\hat n$：preload = 沿零空间射线走多远\n"
                 "这条线上 τ 恒为 0（不产生力矩）", color=INK, fontsize=10.2)
    ax.tick_params(labelsize=6.5)

    # ================= (b) τ 越大 → 交点跑出盒子 =================
    ax = fig.add_subplot(1, 3, 2, projection="3d")
    _box_edges(ax, fmin, fmax)
    # preload 平面（裁到盒子内）
    e1 = np.cross(n, [1.0, 0.0, 0.0]); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    g = np.linspace(-14, 14, 90)
    G1, G2 = np.meshgrid(g, g)
    pts = (args.preload * n[None, None, :]
           + G1[..., None] * e1[None, None, :]
           + G2[..., None] * e2[None, None, :])
    mask = np.any((pts < fmin) | (pts > fmax), axis=2)
    Xp = np.ma.masked_where(mask, pts[..., 0])
    Yp = np.ma.masked_where(mask, pts[..., 1])
    Zp = np.ma.masked_where(mask, pts[..., 2])
    ax.plot_surface(Xp, Yp, Zp, color=BLUE, alpha=0.10, linewidth=0, zorder=2)
    ax.plot_wireframe(Xp[::6, ::6], Yp[::6, ::6], Zp[::6, ::6], color=BLUE,
                      alpha=0.25, linewidth=0.4, zorder=2)

    taus = ((0.0, GREEN), (0.05, AMBER), (0.10, RED), (0.20, PURPLE))
    for tp, col in taus:
        base = f_tau(0.0, tp)
        sp, ok = _seg_in_box(base, n, fmin, fmax)
        ax.plot(*sp[:, ok], color=col, lw=2.0, zorder=6)
        q = base + args.preload * n
        inside = np.all(q >= fmin) and np.all(q <= fmax)
        ax.scatter(*q, color=col, s=60, marker="o" if inside else "x",
                   linewidths=2.0, depthshade=False, zorder=9)
        # 出界时标一下越界的缆
        if not inside:
            bad = [i for i in range(3) if not (fmin <= q[i] <= fmax)]
            ax.text(q[0], q[1], q[2] + 0.45,
                    "C" + "/".join(str(i + 1) for i in bad) + " 出界",
                    fontsize=7.4, color=col, zorder=10)
    # 放大到 preload 附近（否则四条平行线糊成一条）
    zmax = 9.0
    ax.set_xlim(-1.5, zmax); ax.set_ylim(-1.5, zmax); ax.set_zlim(-1.5, zmax)
    ax.view_init(elev=20, azim=34)
    ax.set_xlabel("$f_1$ (N)", color=INK, fontsize=8, labelpad=-4)
    ax.set_ylabel("$f_2$ (N)", color=INK, fontsize=8, labelpad=-4)
    ax.set_zlabel("$f_3$ (N)", color=INK, fontsize=8, labelpad=-4)
    ax.set_title(f"(b) preload={args.preload:g} 平面 ∩ 盒子\n"
                 "τ 越大，直线平移越远，交点先出盒子（α<1）",
                 color=INK, fontsize=10.2)
    ax.tick_params(labelsize=6.5)
    handles = []
    for tp, col in taus:
        a = alpha_of(0.0, tp)
        handles.append(plt.Line2D([], [], color=col, lw=2,
                                  label=f"$\\tau_p$={tp:g} → α={a:.2f}"))
    ax.legend(handles=handles, fontsize=7.2, loc="upper left", framealpha=0.85)

    # ================= (c) 外环饱和 vs 容量 =================
    ax = fig.add_subplot(1, 3, 3)
    lim_r = (fmax - fmin) * sum(abs(v) for v in R[ROLL])
    lim_p = (fmax - fmin) * sum(abs(v) for v in R[PITCH])
    e = np.linspace(0, 0.32, 500)

    def cap(i):
        lo, hi = 0.0, 1.2
        for _ in range(50):
            mid = (lo + hi) / 2
            tau = (mid, 0.0) if i == 0 else (0.0, mid)
            if alpha_of(tau[0], tau[1]) >= 1 - 1e-12:
                lo = mid
            else:
                hi = mid
        return lo

    cr, cp = cap(0), cap(1)
    knee_r, knee_p = lim_r / args.kp_tau, lim_p / args.kp_tau

    for lim, knee, c_cap, name in ((lim_r, knee_r, cr, "roll"),
                                   (lim_p, knee_p, cp, "pitch")):
        ax.plot(e, np.minimum(args.kp_tau * e, lim), lw=2.2,
                color=BLUE if name == "roll" else PURPLE,
                label=f"{name}: $u=\\min(K_p e,\\ {lim:.2f})$")
        ax.axvline(knee, color=MUTED, ls="-.", lw=1.1)
        ax.axvline(c_cap, color=BLUE if name == "roll" else PURPLE,
                   ls="--", lw=1.4)
    # 交互区标注：膝盖 vs 容量（文本按实际大小关系生成，别写死）
    def _verdict(knee, cap):
        return ("外环先饱和（增益失效）" if knee < cap else "TDA 先打折（α<1）")

    x_r = lim_r / args.kp_tau
    ax.set_xlim(0, max(0.32, 1.15 * max(knee_r, knee_p, cr, cp, 0.1)))
    ax.text(0.02, 0.92, f"roll\n膝盖 {knee_r:.3f} {'<' if knee_r < cr else '>'} 容量 {cr:.3f}\n"
                        f"→ {_verdict(knee_r, cr)}",
            transform=ax.transAxes, fontsize=7.8, color=BLUE, va="top")
    ax.text(0.52, 0.92, f"pitch\n膝盖 {knee_p:.3f} {'<' if knee_p < cp else '>'} 容量 {cp:.3f}\n"
                        f"→ {_verdict(knee_p, cp)}",
            transform=ax.transAxes, fontsize=7.8, color=PURPLE, va="top")
    ax.set_xlabel("τ 误差 $|err|$ (N·m)", color=INK)
    ax.set_ylabel("外环输出 $u$ (N·m)", color=INK)
    ax.set_title(f"(c) 饱和膝盖（$K_p\\tau$={args.kp_tau:g}） vs TDA 容量\n"
                 "点划线=膝盖；虚线=容量；谁在左谁先到极限", color=INK, fontsize=10.2)
    ax.grid(color=GRID, lw=0.6)
    ax.set_ylim(0, lim_p * 1.18)
    ax.legend(fontsize=8, loc="lower right")
    for sp in ax.spines.values():
        sp.set_color(GRID)

    fig.tight_layout()
    path = out / (f"torque_space_{args.tag}.png" if args.tag else "torque_space.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"  {path}  {path.stat().st_size/1024:.0f} KB")
    print(f"  preload={args.preload:g}  Kp_τ={args.kp_tau:g}")
    print(f"  容量  roll {cr:.3f} / pitch {cp:.3f}  N·m")
    print(f"  膝盖  roll {knee_r:.3f} / pitch {knee_p:.3f}  N·m")
    print(f"  roll : {'外环先饱和' if knee_r < cr else 'TDA 先打折'}")
    print(f"  pitch: {'外环先饱和' if knee_p < cp else 'TDA 先打折'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
