# -*- coding: utf-8 -*-
"""左右手坐标系对照图：同样的"前/左/上"，换一下轴的名字，手性就变了。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

FWD = np.array([0.80, 0.52])    # 朝前（屏幕右上）
LEFT = np.array([-0.80, 0.52])  # 朝左（屏幕左上）
UP = np.array([0.0, 1.0])       # 朝上

CX, CY = -0.35, -0.62
OY = -0.35

fig, axes = plt.subplots(1, 2, figsize=(12.6, 6.0), dpi=200)
fig.subplots_adjust(left=0.03, right=0.97, top=0.84, bottom=0.10, wspace=0.12)

def draw_axes(ax, xv, yv, xname, yname, title, verdict, ok):
    ax.set_xlim(-1.45, 1.45)
    ax.set_ylim(-0.95, 1.45)
    ax.set_aspect("equal")
    ax.axis("off")

    o = np.array([0.0, OY])
    for v, col, lab, name in [
        (xv, "#e11d48", "X", xname),
        (yv, "#059669", "Y", yname),
    ]:
        end = o + v
        ax.add_patch(FancyArrowPatch(o, end, arrowstyle="-|>", mutation_scale=18,
                                     lw=3.2, color=col, shrinkA=0, shrinkB=0, zorder=4))
        ax.text(end[0] + (0.06 if end[0] > 0 else -0.06), end[1] + 0.10, lab, color=col, fontsize=22,
                fontweight="bold", ha="center", va="center")
        ax.text(end[0] + (0.06 if end[0] > 0 else -0.06), end[1] - 0.09, name, color=col, fontsize=12.5,
                ha="center", va="center")

    endz = o + UP * 1.18
    ax.add_patch(FancyArrowPatch(o, endz, arrowstyle="-|>", mutation_scale=18,
                                 lw=3.2, color="#2563eb", shrinkA=0, shrinkB=0, zorder=4))
    ax.text(endz[0] + 0.02, endz[1] + 0.06, "Z", color="#2563eb", fontsize=22,
            fontweight="bold", ha="center", va="bottom")
    ax.text(endz[0] + 0.26, endz[1] + 0.02, "上", color="#2563eb", fontsize=13,
            ha="center", va="center")

    ax.plot([o[0]], [o[1]], "o", ms=7, color="#111827", zorder=6)
    ax.text(o[0] - 0.06, o[1] - 0.10, "O", fontsize=15, ha="right", va="top")

    # 从 X 转向 Y 的弧，提示右手定则
    a1 = np.arctan2(xv[1], xv[0])
    a2 = np.arctan2(yv[1], yv[0])
    d = ((a2 - a1 + np.pi) % (2 * np.pi)) - np.pi
    ts = np.linspace(0, d, 40)
    arc = o + 0.34 * np.c_[np.cos(a1 + ts), np.sin(a1 + ts)]
    ax.plot(arc[:, 0], arc[:, 1], color="#9ca3af", lw=1.5, ls=(0, (4, 3)))
    ax.annotate("", xy=arc[0], xytext=arc[5],
                arrowprops=dict(arrowstyle="-|>", color="#9ca3af", lw=1.2))

    ax.set_title(title, fontsize=15, pad=6)
    ax.text(0, -0.86, verdict, ha="center", va="center", fontsize=14,
            color="#047857" if ok else "#b91c1c", fontweight="bold")

# 右手：前 X、左 Y、上 Z
draw_axes(axes[0], FWD, LEFT, "前", "左",
          "右手坐标系：前 = X，左 = Y，上 = Z",
          "X × Y = Z　√ 右手定则成立", True)

# 左手：左 X、前 Y、上 Z
draw_axes(axes[1], LEFT, FWD, "左", "前",
          "左手坐标系：左 = X，前 = Y，上 = Z",
          "X × Y = −Z　× 拇指朝下", False)

fig.text(0.5, 0.945, "同样的“前 / 左 / 上”，只把 X、Y 换个名字，手性就反了",
         ha="center", fontsize=17)
fig.text(0.5, 0.035,
         "右手定则：右手四指从 X 弯向 Y，拇指指向 Z。  机器人常用 ROS 约定：X 前、Y 左、Z 上。",
         ha="center", fontsize=11.5, color="0.35")

fig.savefig("左右手坐标系.png", bbox_inches="tight", facecolor="white")
print("ok")
