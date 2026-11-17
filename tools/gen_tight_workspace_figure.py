"""生成张紧模式「可用区 + 可行 t 区间」热力图（可直接进报告）。

用法（在 code/mmhand-main 下）：
    .venv\\Scripts\\python.exe -m tools.gen_tight_workspace_figure
    .venv\\Scripts\\python.exe -m tools.gen_tight_workspace_figure --fmin 0.2 --fmax 30

产出（默认写到仓库上一级 figs/）：
    tight_workspace.png
      (a) 颜色 = 可行 t 的宽度 = t_max_allow − t_min_req（越大越"松"）
      (b) 等值线 = t_min_req / t_max_allow；绿色 = 默认 t*=5 可行的区域

判据（与 mmhand_scope._tight_params 同口径）：
    n̂ 存在且三分量全正
    t_min_req  = fmin / min(n̂)      （否则最松那根达不到 fmin）
    t_max_allow = fmax / max(n̂)     （否则最紧那根超 fmax）
    可行 ⇔ t_min_req ≤ t* ≤ t_max_allow
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

from wrist_model import positive_null_direction  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

INK, MUTED, GRID = "#24303f", "#6b7785", "#dfe4ea"
RED, GREEN, AMBER, BLUE = "#ef4444", "#10b981", "#f59e0b", "#3b82f6"

# 采样位姿（与文档里的例子一致）
SAMPLES = [
    ((0, 0), "(0,0)"),
    ((10, 10), "(10,10)"),
    ((14, 0), "(14,0)"),
    ((0, 30), "(0,30)"),
    ((-18, 0), "(−18,0)"),
    ((13, 25), "(13,25)"),
]


def scan(fmin: float, fmax: float, step: float = 0.5):
    """返回 (R, P, N̂ 数组, t_min, t_max, 有效掩码)。"""
    r = np.arange(-25.0, 25.0 + 1e-9, step)
    p = np.arange(-25.0, 45.0 + 1e-9, step)
    R, P = np.meshgrid(r, p)
    n = np.full(R.shape + (3,), np.nan)
    tmin = np.full(R.shape, np.nan)
    tmax = np.full(R.shape, np.nan)
    for j in range(R.shape[0]):
        for i in range(R.shape[1]):
            nd = positive_null_direction(math.radians(R[j, i]),
                                         math.radians(P[j, i]))
            if nd is None:
                continue
            n[j, i] = nd
            tmin[j, i] = fmin / min(nd)
            tmax[j, i] = fmax / max(nd)
    return r, p, n, tmin, tmax


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="张紧可用区热力图")
    ap.add_argument("--fmin", type=float, default=0.5)
    ap.add_argument("--fmax", type=float, default=30.0)
    ap.add_argument("--t-target", type=float, default=5.0, help="默认张紧目标 t*")
    ap.add_argument("--out", default="../../figs")
    args = ap.parse_args(argv)

    r, p, n, tmin, tmax = scan(args.fmin, args.fmax)
    width = tmax - tmin
    valid = np.isfinite(width) & (width > 0)

    out = Path(args.out)
    if not out.is_absolute():
        out = (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    fig, axs = plt.subplots(1, 2, figsize=(13.6, 5.6), dpi=170)

    # ---------- (a) 可行 t 宽度 ----------
    ax = axs[0]
    Wm = np.ma.masked_where(~valid, width)
    pc = ax.pcolormesh(r, p, Wm, shading="auto", cmap="viridis",
                       vmin=0, vmax=45, zorder=2)
    cb = fig.colorbar(pc, ax=ax, pad=0.02)
    cb.set_label("可行 t 的宽度  $t_{max}-t_{min}$ (N)", fontsize=9)
    # 有效区边界 + UI 框
    ax.contour(r, p, valid.astype(float), levels=[0.5], colors=[RED], linewidths=1.6,
               zorder=4)
    ax.add_patch(Rectangle((-25, -25), 50, 70, fill=False, ec=MUTED, lw=1.2,
                           ls=(0, (6, 4)), zorder=3))
    ax.text(-24.0, 41.5, "UI / 模型行程（±25°, −25~45°）", color=MUTED, fontsize=8.5)
    for (x0, y0), lab in SAMPLES:
        ax.plot(x0, y0, "o", ms=6, mfc="white", mec=INK, mew=1.2, zorder=6)
    ax.set_xlabel("ROLL (°)", color=INK)
    ax.set_ylabel("PITCH (°)", color=INK)
    ax.set_title(f"(a) 张紧可行区：颜色=可行 t 宽度（fmin={args.fmin:g}, fmax={args.fmax:g}）",
                 color=INK, fontsize=11.5)
    ax.grid(color=GRID, lw=0.6, alpha=0.6, zorder=0)

    # ---------- (b) t_min / t_max 等值线 + t* 可行域 ----------
    ax = axs[1]
    ok5 = valid & (tmin <= args.t_target) & (args.t_target <= tmax)
    ax.contourf(r, p, valid.astype(float), levels=[0.5, 1.5], colors=["#eef2f7"], zorder=0)
    ax.contourf(r, p, ok5.astype(float), levels=[0.5, 1.5], colors=[GREEN],
                alpha=0.35, zorder=1)
    lv_min = [l for l in (2, 5, 10, 20, 30) if np.nanmin(tmin) <= l <= np.nanmax(tmin)]
    lv_max = [l for l in (5, 10, 20, 30, 39) if np.nanmin(tmax) <= l <= np.nanmax(tmax)]
    c1 = ax.contour(r, p, np.where(valid, tmin, np.nan), levels=lv_min,
                    colors=[BLUE], linewidths=1.3, zorder=5)
    c2 = ax.contour(r, p, np.where(valid, tmax, np.nan), levels=lv_max,
                    colors=[AMBER], linewidths=1.3, linestyles="--", zorder=5)
    ax.clabel(c1, fmt="$t_{min}$=%g", fontsize=7.5)
    ax.clabel(c2, fmt="$t_{max}$=%g", fontsize=7.5)
    ax.contour(r, p, valid.astype(float), levels=[0.5], colors=[RED], linewidths=1.6,
               zorder=6)
    for (x0, y0), lab in SAMPLES:
        ax.plot(x0, y0, "o", ms=6, mfc="white", mec=INK, mew=1.2, zorder=7)
        # 标注该点的 t 区间
        nd = positive_null_direction(math.radians(x0), math.radians(y0))
        if nd is not None:
            lo, hi = args.fmin / min(nd), args.fmax / max(nd)
            ax.annotate(f"{lab}\n[{lo:.1f},{hi:.1f}]", xy=(x0, y0), xytext=(5, 6),
                        textcoords="offset points", fontsize=7.0, color=INK, zorder=8)
    # 右侧"缺口"
    ax.annotate("缺口：roll>14.5° 后\npitch 下界从 −23.6° 猛升到 +29.7°",
                xy=(15.0, 22.0), xytext=(-2, -34), textcoords="offset points",
                fontsize=7.6, color=RED,
                arrowprops=dict(arrowstyle="->", color=RED, lw=1.0))
    ax.set_xlabel("ROLL (°)", color=INK)
    ax.set_ylabel("PITCH (°)", color=INK)
    ax.set_title(f"(b) 绿=默认 t*={args.t_target:g} N 可行；蓝实线 $t_{{min}}$ / 黄虚线 $t_{{max}}$",
                 color=INK, fontsize=11.5)
    ax.grid(color=GRID, lw=0.6, alpha=0.6, zorder=0)
    ax.set_xlim(-25, 25)
    ax.set_ylim(-25, 45)

    for a in axs:
        for sp in a.spines.values():
            sp.set_color(GRID)
    fig.tight_layout()
    path = out / "tight_workspace.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {path}  {path.stat().st_size/1024:.0f} KB")
    print(f"  有效面积占比 {100.0*valid.mean():.1f}% ; t*= {args.t_target:g} N 可行占比 "
          f"{100.0*ok5.mean():.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
