# -*- coding: utf-8 -*-
"""为什么"绳长变化率"就是力臂：卷筒 + 投影两个证明。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DEG = np.pi / 180.0
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.0, 5.6), dpi=190)

# ---------------- (a) 卷筒 ----------------
R = 20.0
T = np.array([R, 0.0])
dth = 50 * DEG
T2 = np.array([R * np.cos(-dth), R * np.sin(-dth)])

ax1.add_patch(Circle((0, 0), R, fill=False, lw=2.6, color="#2563eb"))
ax1.plot([0], [0], marker="o", ms=9, color="k", zorder=5)
ax1.text(-1.5, -4.2, "转轴", ha="center", fontsize=11)

ax1.plot([0, R], [0, 0], color="#2563eb", lw=1.6)
ax1.text(R * 0.42, 1.0, "r", fontsize=13, color="#2563eb")

th = np.linspace(0, -dth, 60)
ax1.plot(R * np.cos(th), R * np.sin(th), color="#dc2626", lw=4.5, alpha=0.75)

ax1.plot([T[0], T[0]], [T[1], -32], color="#d97706", lw=4.5, solid_capstyle="round")
ax1.plot([T2[0], T2[0]], [T2[1], -32], color="#d97706", lw=1.2, ls=":", alpha=0.8)

ax1.add_patch(Arc((0, 0), 17, 17, theta1=-dth, theta2=0, color="k", lw=1.2))
ax1.text(9.4, -5.6, "Δθ", fontsize=12)

ax1.annotate("", xy=(T2[0] + 6.0, T2[1] - 2.5), xytext=(T2[0] + 6.0, T2[1] - 9.5),
             arrowprops=dict(arrowstyle="<->", color="#dc2626", lw=1.4))
ax1.text(T2[0] + 7.4, T2[1] - 6.6, "Δl", fontsize=13, color="#dc2626")

ax1.text(-35, -13.0, "转动 Δθ，绳子被收进：", fontsize=12.5, color="#b45309")
ax1.text(-35, -18.5, "Δl = r · Δθ", fontsize=13.5, color="#b45309")
ax1.text(-35, -26.0, "而张力对轴的力矩本来就是：", fontsize=12.5, color="#b45309")
ax1.text(-35, -31.5, "T = f · r", fontsize=13.5, color="#b45309")
ax1.text(-2, 26, "① 卷筒：转多少，收多少", fontsize=13.5)

ax1.set_xlim(-36, 36)
ax1.set_ylim(-34, 30)
ax1.set_aspect("equal")
ax1.axis("off")

# ---------------- (b) 投影 ----------------
rho, beta, dtheta = 30.0, 35 * DEG, 12 * DEG
r = rho * np.sin(beta)
P = np.array([rho * np.cos(beta), r])
P2 = P + rho * dtheta * np.array([-np.sin(beta), np.cos(beta)])
footx = P2[0]

ax2.plot([-4, 46], [r, r], color="#d97706", lw=4.2, solid_capstyle="round", zorder=2)
ax2.text(42.5, r + 1.6, "绳", fontsize=12, color="#b45309")

ax2.plot([0, P[0]], [0, P[1]], color="#2563eb", lw=1.8, zorder=3)
ax2.plot([0, 0], [0, r], color="#dc2626", lw=2.0, ls=(0, (4, 3)), zorder=3)
ax2.plot([0], [0], marker="o", ms=9, color="k", zorder=6)
ax2.plot([P[0]], [P[1]], marker="o", ms=7, color="#7c3aed", zorder=7)
ax2.plot([P2[0]], [P2[1]], marker="o", ms=6, color="#7c3aed", alpha=0.55, zorder=6)

ax2.annotate("", xy=P2, xytext=P, arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=2.2))
ax2.plot([P2[0], P2[0]], [P2[1], r], color="0.65", lw=1.0, ls=":")
ax2.plot([footx, P[0]], [r, r], color="#dc2626", lw=3.4, zorder=5)
ax2.plot([0, 0], [0, r], color="#dc2626", lw=2.4, ls=(0, (4, 3)), zorder=4)

ax2.add_patch(Arc(P, 9, 9, theta1=180, theta2=215, color="k", lw=1.1))
ax2.text(P[0] - 5.4, r - 2.6, "β", fontsize=11)
ax2.text(-2.4, r / 2 - 1.2, "r", fontsize=13, color="#dc2626")
ax2.text(P[0] + 3.0, P[1] - 4.2, "ρ", fontsize=13, color="#2563eb")

ax2.text(9.0, P2[1] + 2.2, "转 dθ：P 走 ρ·dθ", fontsize=12, color="#7c3aed")
ax2.text(footx - 1.0, r - 7.2, "沿绳的分量 = r·dθ", fontsize=12.5, color="#b91c1c")
ax2.text(-3, 30, "② 任意方向：只有沿绳的分量算数", fontsize=13.5)
ax2.text(-3, -7.5, "垂直于绳的那部分，只是把绳“抬起来”，不改变绳长。",
         fontsize=10.8, color="0.35")

ax2.set_xlim(-5, 46)
ax2.set_ylim(-10, 32)
ax2.set_aspect("equal")
ax2.axis("off")

fig.tight_layout()
fig.savefig("讲解图_为什么是力臂.png", bbox_inches="tight", facecolor="white")
print("ok", r)
