# -*- coding: utf-8 -*-
"""为什么 v' = v·cosθ + (â×v)·sinθ：圆上的分解。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

th = 35 * np.pi / 180
fig, ax = plt.subplots(figsize=(8.6, 6.2), dpi=200)
ax.set_aspect("equal")
ax.set_xlim(-0.35, 1.45)
ax.set_ylim(-0.35, 1.25)
ax.axis("off")

O = np.array([0, 0])
ax.add_patch(plt.Circle((0, 0), 1, fill=False, color="0.8", lw=1.0, ls=(0, (4, 4))))

V = np.array([1.0, 0.0])
P = np.array([np.cos(th), np.sin(th)])

ax.annotate("", xy=V, xytext=O, arrowprops=dict(arrowstyle="-|>", color="#7c3aed", lw=3))
ax.annotate("", xy=P, xytext=O, arrowprops=dict(arrowstyle="-|>", color="#a78bfa", lw=3))

ax.plot([P[0], P[0]], [0, P[1]], color="#0891b2", lw=2.2, ls=(0, (3, 3)))
ax.plot([0, P[0]], [0, 0], color="#059669", lw=3.2, alpha=0.85)

ax.add_patch(Arc(O, 0.5, 0.5, theta1=0, theta2=35, color="k", lw=1.3))
ax.text(0.30, 0.10, "θ", fontsize=15)

ax.text(0.30, -0.10, "v⊥·cos θ", color="#059669", fontsize=12, ha="center")
ax.text(P[0] + 0.06, P[1] / 2, "(â×v⊥)·sin θ", color="#0891b2", fontsize=12, va="center")

ax.text(0.62, 0.08, "v⊥", color="#7c3aed", fontsize=14)
ax.text(0.55, 0.62, "v′⊥", color="#a78bfa", fontsize=14)

ax.text(-0.02, -0.06, "O", fontsize=12, ha="right", va="top")
ax.text(0.0, 1.16, "在垂直于轴的平面里：v⊥ 转 θ 后落在圆上", fontsize=14)

ax.text(0.0, -0.30,
        "绿色 = 原方向留下的部分   青色 = 垂直方向甩出去的部分\n"
        "两个都是“长度 × cos/sin”，合起来就是转过的那个点",
        fontsize=11, color="0.3")

fig.savefig("讲解图_旋转分解.png", bbox_inches="tight", facecolor="white")
print("ok")
