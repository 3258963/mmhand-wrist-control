# -*- coding: utf-8 -*-
"""叉乘直观图（平面版）：â 指向纸外，â×v 就是 v 在平面内转 90°。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

v = np.array([-32.5, 18.0])
c = np.array([18.0, 32.5])
r = np.linalg.norm(v)

fig, ax = plt.subplots(figsize=(9.6, 6.6), dpi=190)
ax.set_aspect("equal")
ax.set_xlim(-54, 34)
ax.set_ylim(-32, 44)
ax.axis("off")

ax.add_patch(Circle((0, 0), r, fill=False, color="0.82", lw=1.1, ls=(0, (4, 4))))

ax.fill([0, v[0], v[0] + c[0], c[0]], [0, v[1], v[1] + c[1], c[1]],
        color="#a5f3fc", alpha=0.16, zorder=0)

ax.annotate("", xy=v, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#7c3aed", lw=3))
ax.annotate("", xy=c, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#0891b2", lw=3))

s = 4.5
e1 = v / r
e2 = c / r
p1 = e1 * s
p2 = e1 * s + e2 * s
p3 = e2 * s
ax.plot([p1[0], p2[0], p3[0]], [p1[1], p2[1], p3[1]], color="#475569", lw=1.2)

ax.add_patch(Arc((0, 0), 18, 18, theta1=61.0, theta2=151.0, color="#f59e0b", lw=1.6))
ax.text(-10.6, 11.8, "90°", color="#b45309", fontsize=11)

ax.add_patch(Circle((0, 0), 1.9, fill=False, color="k", lw=1.4))
ax.plot([0], [0], "o", ms=3.2, color="k")
ax.text(2.5, -7.0, "â 指向纸外（就是转轴）", fontsize=10.5, color="0.2")

ax.text(v[0] - 2.5, v[1] + 2.0, "v", fontsize=15, color="#6d28d9", ha="right")
ax.text(c[0] + 2.0, c[1] - 0.5, "â × v", fontsize=15, color="#0e7490")
ax.text(-31.0, -15.0, "‖v‖ = 37.15", fontsize=11, color="#6d28d9")
ax.text(-4.0, 37.0, "‖â×v‖ = 37.15", fontsize=11, color="#0e7490")

ax.text(-52, -24,
        "â×v 就是：把 v 在这个平面里转 90°，长度不变。\n"
        "两者张成的平行四边形，面积 = ‖â‖·‖v‖·sin90° = 37.15。",
        fontsize=11, color="0.28", va="top")

ax.set_title("叉乘：â 与 v → 一个同时垂直于两者的新向量", fontsize=14)
fig.savefig("讲解图_叉乘.png", bbox_inches="tight", facecolor="white")
print("ok", r, np.linalg.norm(c))
