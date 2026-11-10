# -*- coding: utf-8 -*-
"""图：sinΔ = −(â×v⊥)·u⊥/(ab) 的几何解释。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["mathtext.fontset"] = "dejavusans"
plt.rcParams["axes.unicode_minus"] = False

a = 27.459
b = 37.152
D = np.deg2rad(18.49)

u = np.array([a, 0.0])                       # u⊥ 沿 +x
v = b * np.array([np.cos(D), np.sin(D)])     # v⊥
c = b * np.array([np.cos(D + np.pi / 2), np.sin(D + np.pi / 2)])  # â×v⊥

fig, ax = plt.subplots(figsize=(10.2, 7.4), dpi=190)
ax.set_aspect("equal")
ax.set_xlim(-24, 44)
ax.set_ylim(-8, 52)
ax.axis("off")

# 坐标轴
ax.plot([-22, 42], [0, 0], color="0.88", lw=1, zorder=0)

# 投影虚线：从 c 的尖端垂直落到 x 轴
ax.plot([c[0], c[0]], [c[1], 0], color="0.55", lw=1.1, ls=(0, (4, 3)))
ax.plot([0, c[0]], [0, 0], color="#dc2626", lw=4.0, solid_capstyle="butt", alpha=0.85, zorder=2)
ax.plot([c[0]], [0], "o", ms=7, color="#dc2626", zorder=5)

# 三个向量
ax.annotate("", xy=u, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#7c3aed", lw=3.4))
ax.annotate("", xy=v, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#a78bfa", lw=3.4))
ax.annotate("", xy=c, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#0891b2", lw=3.0,
                                                       linestyle="--"))

# 直角标记（v⊥ 与 â×v⊥）
s = 4.2
e1 = v / b
e2 = c / b
ax.plot([e1[0] * s, (e1 * s + e2 * s)[0], e2[0] * s],
        [e1[1] * s, (e1 * s + e2 * s)[1], e2[1] * s], color="#475569", lw=1.2)

# 角 Δ 与 Δ+90°
ax.add_patch(Arc((0, 0), 20, 20, theta1=0, theta2=np.rad2deg(D), color="#7c3aed", lw=1.6))
ax.text(11.4, 2.4, "Δ", color="#6d28d9", fontsize=13)
ax.add_patch(Arc((0, 0), 34, 34, theta1=0, theta2=np.rad2deg(D) + 90, color="#f59e0b", lw=1.6))
ax.text(15.2, 15.6, "Δ+90°", color="#b45309", fontsize=12)

# 标注
ax.text(u[0] + 1.2, -3.6, r"$\vec{u}_\perp$（长度 a）", color="#6d28d9", fontsize=11.5)
ax.text(v[0] + 1.4, v[1] + 1.2, r"$\vec{v}_\perp$（长度 b）", color="#7c3aed", fontsize=11.5)
ax.text(c[0] + 0.6, c[1] - 9.0, r"$\hat{a}\times\vec{v}_\perp$（长度 b，方向再转 90°）", color="#0e7490", fontsize=11)

ax.annotate("", xy=(-11.78, 0), xytext=(-11.78, -4.5),
            arrowprops=dict(arrowstyle="-", color="#dc2626", lw=1))
ax.text(-12.6, -6.2, "投影 = b·cos(Δ+90°) = −b·sinΔ = −11.78 mm",
        color="#b91c1c", fontsize=11.5, ha="left")

ax.text(-22, 50,
        r"$\hat{a}\times\vec{v}_\perp$ 与 $\vec{u}_\perp$ 的夹角是 $\Delta+90^\circ$，所以点乘 $=ab\cos(\Delta+90^\circ)=-ab\sin\Delta$",
        fontsize=11.5, color="#1e293b")
ax.text(-22, 45.4,
        r"两边除以 $ab$ 并取负号：$\sin\Delta=-(\hat{a}\times\vec{v}_\perp)\cdot\vec{u}_\perp/(ab)=0.3171\ \rightarrow\ \Delta=18.49^\circ$",
        fontsize=11.5, color="#1e293b")

fig.savefig("讲解图_sinDelta.png", bbox_inches="tight", facecolor="white")
print("ok", c, np.dot(c, u), -np.dot(c, u) / (a * b))
