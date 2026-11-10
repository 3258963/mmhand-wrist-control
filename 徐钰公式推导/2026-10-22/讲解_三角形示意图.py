# -*- coding: utf-8 -*-
"""讲解图：一根绳、一个关节，力臂就是"轴到绳线的垂距"。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DEG = np.pi / 180.0
a, b = 30.0, 20.0          # 两个半径 mm
delta = 60.0 * DEG         # 零位夹角
O = np.array([0.0, 0.0])
A = np.array([a, 0.0])
B = np.array([b * np.cos(delta), b * np.sin(delta)])
th = 15.0 * DEG
B2 = np.array([b * np.cos(delta + th), b * np.sin(delta + th)])

alpha = a * a + b * b
beta = -2 * a * b * np.cos(delta)
gamma = 2 * a * b * np.sin(delta)
s0 = np.sqrt(alpha + beta)
r0 = -gamma / (2 * s0)

# 垂足
t = -np.dot(A, B - A) / np.dot(B - A, B - A)
F = A + t * (B - A)

fig, (ax, ax2) = plt.subplots(1, 2, figsize=(12.4, 5.2), dpi=190)

# ---------- 左：几何 ----------
ax.set_aspect("equal")
ax.axhline(0, color="0.85", lw=0.8, zorder=0)
ax.axvline(0, color="0.85", lw=0.8, zorder=0)

ax.plot([O[0], A[0]], [O[1], A[1]], color="#2563eb", lw=2.2, zorder=3)
ax.plot([O[0], B[0]], [O[1], B[1]], color="#7c3aed", lw=2.2, zorder=3)
ax.plot([A[0], B[0]], [A[1], B[1]], color="#d97706", lw=4.0, zorder=4)

ax.plot([O[0], B2[0]], [O[1], B2[1]], color="#7c3aed", lw=1.2, ls=":", zorder=2)
ax.plot([A[0], B2[0]], [A[1], B2[1]], color="#d97706", lw=1.2, ls=":", zorder=2)

ax.plot([O[0], F[0]], [O[1], F[1]], color="#dc2626", lw=1.6, ls="--", zorder=5)
ax.plot([F[0]], [F[1]], marker="o", ms=4, color="#dc2626", zorder=6)
ax.plot([O[0]], [O[1]], marker="o", ms=7, color="k", zorder=6)
ax.plot([A[0]], [A[1]], marker="o", ms=6, color="#2563eb", zorder=6)
ax.plot([B[0]], [B[1]], marker="o", ms=6, color="#7c3aed", zorder=6)
ax.plot([B2[0]], [B2[1]], marker="o", ms=5, color="#7c3aed", alpha=0.5, zorder=6)

ax.text(-1.2, -3.4, "O（轴心）", fontsize=11, ha="right")
ax.text(A[0] + 1.0, -3.4, "A（绳固定端）", fontsize=11, color="#2563eb")
ax.text(B[0] - 1.0, B[1] + 1.6, "B（绳动端）", fontsize=11, color="#7c3aed")
ax.text(13.0, 1.6, "a = 30 mm", fontsize=10.5, color="#2563eb")
ax.text(2.2, 7.2, "b = 20 mm", fontsize=10.5, color="#7c3aed", rotation=60)
ax.text(20.6, 8.6, "s = |AB|", fontsize=10.5, color="#b45309", rotation=-41)
ax.text(15.4, 16.4, "r = 19.64 mm（垂距）", fontsize=10.5, color="#dc2626")

ax.add_patch(Arc(O, 14, 14, theta1=0, theta2=60, color="#7c3aed", lw=1.1))
ax.text(7.6, 3.4, "Δ = 60°", fontsize=10, color="#7c3aed")
ax.add_patch(Arc(O, 26, 26, theta1=60, theta2=75, color="#0f766e", lw=1.1))
ax.text(14.6, 23.4, "θ", fontsize=10, color="#0f766e")
ax.text(25.6, 22.4, "θ 转过一点后，\n绳长 s 只变一点点", fontsize=9.5, color="0.35")

ax.set_xlim(-11, 41)
ax.set_ylim(-9, 28)
ax.set_xlabel("x / mm")
ax.set_ylabel("y / mm")
ax.set_title("俯视图（沿关节轴看下去）：一个关节、一根绳", fontsize=12.5, pad=10)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)

# ---------- 右：曲线 ----------
tt = np.linspace(-70, 130, 600) * DEG
D = alpha + beta * np.cos(tt) + gamma * np.sin(tt)
s = np.sqrt(D)
r = (beta * np.sin(tt) - gamma * np.cos(tt)) / (2 * s)

ax2.plot(tt / DEG, s, color="#d97706", lw=2.4, label="绳长 s(θ) / mm")
ax2.set_xlabel("关节转角 θ / °")
ax2.set_ylabel("绳长 s / mm", color="#b45309")
ax2.tick_params(axis="y", labelcolor="#b45309")

ax3 = ax2.twinx()
ax3.plot(tt / DEG, r, color="#dc2626", lw=2.0, label="力臂 r(θ) / mm")
ax3.set_ylabel("力臂 r / mm", color="#dc2626")
ax3.tick_params(axis="y", labelcolor="#dc2626")
ax3.axhline(0, color="0.7", lw=0.9)

ax2.plot([0], [s0], marker="o", ms=6, color="#111827")
ax3.plot([0], [r0], marker="o", ms=6, color="#111827")
ax2.annotate("s(0) = 26.46", xy=(0, s0), xytext=(8, s0 - 4.5), fontsize=10,
             arrowprops=dict(arrowstyle="-", color="0.5"))
ax3.annotate("r(0) = −19.64", xy=(0, r0), xytext=(12, r0 + 5.0), fontsize=10, color="#dc2626",
             arrowprops=dict(arrowstyle="-", color="0.5"))
ax3.annotate("死点：绳线过轴心，r = 0", xy=(120, 0), xytext=(58, 6.5), fontsize=10,
             color="#0f766e", arrowprops=dict(arrowstyle="->", color="#0f766e"))
ax2.set_title("同一根绳：长度在动，力臂是它的变化率", fontsize=12.5, pad=10)

fig.tight_layout()
fig.savefig("讲解图_绳长与力臂.png", bbox_inches="tight", facecolor="white")
print("saved", s0, r0, np.linalg.norm(F))


