# -*- coding: utf-8 -*-
"""三维旋转矩阵动画：绕 Z / X / Y 轴各转一圈（θ = 0 → 360°）的循环 GIF。

输出：动画_三轴旋转.gif
三张子图的旋转轴都摆成竖直，机位固定 —— 与 图2_三轴总览.png 同一套画法。
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

BLUE = "#1f6fd0"
ORANGE = "#e07b1a"
PURPLE = "#7d3c98"
DARK = "#333333"

DEG = np.pi / 180.0


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def Rz(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


SPECS = [
    ("Z", ("x", "y"), "① 绕 Z 轴：xy 平面里转，z 不动", 0.015),
    ("X", ("y", "z"), "② 绕 X 轴：yz 平面里转，x 不动", 0.345),
    ("Y", ("z", "x"), "③ 绕 Y 轴：zx 平面里转，y 不动", 0.675),
]

V0 = unit([0.60, 0.34, 0.72])
E_Z = np.array([0.0, 0.0, 1.0])


def setup_ax(ax):
    ax.set_proj_type("ortho")
    ax.set_box_aspect((1, 1, 1), zoom=1.58)
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-1.15, 1.15)
    ax.set_zlim(-0.55, 1.70)
    ax.view_init(elev=18, azim=-62)
    ax.set_axis_off()


def draw_panel(ax, pair, axis_name, th_deg):
    setup_ax(ax)
    th = th_deg * DEG

    # 坐标轴
    for d, nm in (((1, 0, 0), pair[0]), ((0, 1, 0), pair[1])):
        d = np.array(d, float)
        ax.quiver(0, 0, 0, *(d * 1.02), color="#b8b8b8", lw=1.0,
                  arrow_length_ratio=0.10, zorder=1)
        ax.text(*(d * 1.14), nm, color=DARK, fontsize=11.5, ha="center",
                va="center", zorder=8)

    # 旋转轴 + 沿轴分量
    par = np.dot(V0, E_Z) * E_Z
    ax.plot([0, 0], [0, 0], [0, 1.16], color=PURPLE, lw=1.5, alpha=0.8, zorder=2)
    ax.plot(*np.array([[0, 0, 0], par]).T, color=PURPLE, lw=6.5, alpha=0.33,
            solid_capstyle="round", zorder=3)
    ax.quiver(0, 0, 1.06, 0, 0, 0.10, color=PURPLE, lw=1.5,
              arrow_length_ratio=0.85, zorder=3)

    # 顶点轨迹圆
    r = np.linalg.norm(V0 - par)
    e1 = (V0 - par) / r
    e2 = np.cross(E_Z, e1)
    tt = np.linspace(0, 2 * np.pi, 180)
    circ = par + r * (np.cos(tt)[:, None] * e1 + np.sin(tt)[:, None] * e2)
    ax.plot(circ[:, 0], circ[:, 1], circ[:, 2], color="#d2d2d2", lw=0.9,
            ls=(0, (3, 4)), zorder=1)

    # 扫过的扇形 + 弧
    if th_deg > 0.5:
        ts = np.linspace(0, th, 60)
        sector = [par] + [par + r * (np.cos(t) * e1 + np.sin(t) * e2) for t in ts]
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        ax.add_collection3d(Poly3DCollection(
            [np.array(sector)], facecolor=ORANGE, alpha=0.10, edgecolor="none",
            zorder=0))
        arc = np.array([par + r * (np.cos(t) * e1 + np.sin(t) * e2) for t in ts])
        ax.plot(arc[:, 0], arc[:, 1], arc[:, 2], color=ORANGE, lw=2.4, zorder=4)
        d = arc[-1] - arc[-4]
        ax.quiver(*arc[-4], *d, color=ORANGE, lw=2.4,
                  arrow_length_ratio=0.075 / (np.linalg.norm(d) + 1e-9), zorder=4)

    # 两个向量
    v = Rz(th) @ V0
    for p, col, nm in ((V0, BLUE, "v"), (v, ORANGE, "v′")):
        ax.quiver(0, 0, 0, *p, color=col, lw=3.2, arrow_length_ratio=0.085,
                  zorder=6)
        rad = (p - par) / np.linalg.norm(p - par)
        ax.text(*(p + 0.15 * rad + (0.03 if col == BLUE else 0.04) * E_Z), nm,
                color=col, fontsize=13, zorder=9, ha="center", va="center")
        ax.plot(*np.array([par, p]).T, color="#b5b5b5", lw=0.9, ls=(0, (2, 3)),
                zorder=2)

    # θ 标在扇形里
    if th_deg > 8:
        mid = par + ((V0 - par) + (v - par)) / np.linalg.norm(
            (V0 - par) + (v - par)) * r * 0.52
        ax.text(*mid, "θ", color=ORANGE, fontsize=12, zorder=9, ha="center",
                va="center")

    ax.text2D(0.5, 0.99, SPECS[[s[0] for s in SPECS].index(axis_name)][2],
              transform=ax.transAxes, fontsize=12, color=DARK, ha="center",
              va="top")


def main(step=4.0, fps=22):
    fig = plt.figure(figsize=(12.2, 4.4), dpi=100)
    axes = []
    for _, _, _, x0 in SPECS:
        axes.append(fig.add_axes([x0, 0.07, 0.32, 0.84], projection="3d"))

    readout = fig.text(0.5, 0.022, "", fontsize=12.5, color=DARK, ha="center",
                       va="center")

    n_frames = int(round(360.0 / step))

    def update(frame):
        th_deg = frame * step
        for ax, (axis_name, pair, _, _) in zip(axes, SPECS):
            ax.cla()
            draw_panel(ax, pair, axis_name, th_deg)
        v = Rz(th_deg * DEG) @ V0
        readout.set_text(
            f"θ = {th_deg:5.0f}°    │    v′ = ( {v[0]:+.3f}, {v[1]:+.3f}, {v[2]:+.3f} )")
        return axes

    anim = FuncAnimation(fig, update, frames=n_frames, interval=1000 / fps,
                         blit=False)
    anim.save("动画_三轴旋转.gif", writer=PillowWriter(fps=fps), dpi=100)
    plt.close(fig)
    print(f"已生成 动画_三轴旋转.gif（{n_frames} 帧，{fps} fps，约 {n_frames/fps:.1f} 秒一轮）")


if __name__ == "__main__":
    main()
