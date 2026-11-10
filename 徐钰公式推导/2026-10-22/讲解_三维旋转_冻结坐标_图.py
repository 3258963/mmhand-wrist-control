# -*- coding: utf-8 -*-
"""图8：把三维旋转"按下去" —— 每次只画两个坐标，就是你已经会的二维旋转。

v = (2, 1, 2)
  绕 Z 转 90°：看 (x, y) 平面   (2,1) → (−1,2)，z 一直是 2
  绕 X 转 90°：看 (y, z) 平面   (1,2) → (−2,1)，x 一直是 2
  绕 Y 转 90°：看 (z, x) 平面   (2,2) → (−2,2)，y 一直是 1
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

BLUE, ORANGE, PURPLE = "#1f6fd0", "#e07b1a", "#7d3c98"
DARK = "#333333"
DEG = np.pi / 180

PANELS = [
    dict(h="x", v="y", before=(2.0, 1.0), after=(-1.0, 2.0), frozen=("z", 2),
         title="① 绕 Z 轴 → 只画 (x, y)", x0=0.045),
    dict(h="y", v="z", before=(1.0, 2.0), after=(-2.0, 1.0), frozen=("x", 2),
         title="② 绕 X 轴 → 只画 (y, z)", x0=0.365),
    dict(h="z", v="x", before=(2.0, 2.0), after=(-2.0, 2.0), frozen=("y", 1),
         title="③ 绕 Y 轴 → 只画 (z, x)", x0=0.685),
]


def fmt(p):
    return f"({p[0]:.0f}, {p[1]:.0f})"


fig = plt.figure(figsize=(13.2, 5.0), dpi=200)

for P in PANELS:
    ax = fig.add_axes([P["x0"], 0.15, 0.27, 0.70])
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-2.75, 2.85)
    ax.set_ylim(-2.35, 2.95)

    ax.annotate("", xy=(2.75, 0), xytext=(-2.65, 0),
                arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.2,
                                shrinkA=0, shrinkB=0))
    ax.annotate("", xy=(0, 2.85), xytext=(0, -2.25),
                arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.2,
                                shrinkA=0, shrinkB=0))
    ax.text(2.80, -0.22, P["h"], fontsize=13, color=DARK, ha="left")
    ax.text(-0.16, 2.88, P["v"], fontsize=13, color=DARK, ha="right")

    a0 = np.degrees(np.arctan2(P["before"][1], P["before"][0]))
    ax.add_patch(Arc((0, 0), 5.0, 5.0, theta1=a0, theta2=a0 + 90,
                     color=ORANGE, lw=1.6, ls=(0, (4, 3))))
    am = (a0 + 45) * DEG
    lx = 2.95 * np.cos(am)
    ly = 2.80 * np.sin(am)
    if abs(lx) < 0.80:
        lx = 1.05 * (1 if lx >= 0 else -1)
    ax.text(lx, ly, "转 90°", fontsize=10.5,
            color=ORANGE, ha="center", va="center",
            bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.2))

    for pt, col, lab, off in (
            (P["before"], BLUE, "v", (0.30, -0.42)),
            (P["after"], ORANGE, "v′", (-0.28, 0.42))):
        ax.annotate("", xy=pt, xytext=(0, 0),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=2.8,
                                    shrinkA=0, shrinkB=0, mutation_scale=16))
        ax.plot(*pt, "o", ms=5, color=col, zorder=5)
        ax.text(pt[0] + off[0], pt[1] + off[1], f"{lab} = {fmt(pt)}",
                fontsize=11, color=col, ha="center", va="center",
                bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.5))

    fig.text(P["x0"] + 0.135, 0.960, P["title"], fontsize=12.6, color=DARK,
             ha="center")
    fig.text(P["x0"] + 0.135, 0.075,
             f"{P['frozen'][0]} = {P['frozen'][1]} 从头到尾没变（它不在这张图上）",
             fontsize=10.2, color=PURPLE, ha="center")

fig.text(0.5, 0.015,
         "三格的画法完全一样（都是逆时针 90°），变的只是「哪两个坐标」和「数字」。"
         "第三个坐标根本没参与，所以原样保留 —— 这就是矩阵里那个 1 和一堆 0 的意思。",
         fontsize=10.2, color="#555", ha="center", va="bottom")

fig.savefig("图8_三维按成二维.png", dpi=200, facecolor="white")
plt.close(fig)
print("ok")
