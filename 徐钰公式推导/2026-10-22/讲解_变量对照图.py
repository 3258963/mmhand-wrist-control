# -*- coding: utf-8 -*-
"""变量说明图 v2：图上只写中文和数字，字母对照放到正文表格。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DEG = np.pi / 180.0
a, b = 30.0, 20.0
delta = 60.0 * DEG
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

t = -np.dot(A, B - A) / np.dot(B - A, B - A)
F = A + t * (B - A)

fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13.4, 5.9), dpi=190)
fig.subplots_adjust(bottom=0.20, wspace=0.30)

# ---------------- 左图 ----------------
ax.set_aspect("equal")
ax.axhline(0, color="0.9", lw=0.8, zorder=0)
ax.axvline(0, color="0.9", lw=0.8, zorder=0)

ax.plot([O[0], A[0]], [O[1], A[1]], color="#2563eb", lw=3.3, zorder=3, solid_capstyle="round")
ax.plot([O[0], B[0]], [O[1], B[1]], color="#7c3aed", lw=3.3, zorder=3, solid_capstyle="round")
ax.plot([A[0], B[0]], [A[1], B[1]], color="#d97706", lw=5.2, zorder=4, solid_capstyle="round")

ax.plot([O[0], B2[0]], [O[1], B2[1]], color="#7c3aed", lw=1.4, ls=":", zorder=2)
ax.plot([A[0], B2[0]], [A[1], B2[1]], color="#d97706", lw=1.4, ls=":", zorder=2)

ax.plot([O[0], F[0]], [O[1], F[1]], color="#dc2626", lw=2.2, ls=(0, (4, 3)), zorder=5)
ax.plot([F[0]], [F[1]], marker="o", ms=6, color="#dc2626", zorder=6)
ax.plot([O[0]], [O[1]], marker="o", ms=12, color="white", mec="k", mew=2, zorder=7)
ax.plot([O[0]], [O[1]], marker="o", ms=4.5, color="k", zorder=8)
ax.plot([A[0]], [A[1]], marker="o", ms=8, color="#2563eb", zorder=6)
ax.plot([B[0]], [B[1]], marker="o", ms=8, color="#7c3aed", zorder=6)
ax.plot([B2[0]], [B2[1]], marker="o", ms=6, color="#7c3aed", alpha=0.45, zorder=6)

ax.add_patch(Arc(O, 15, 15, theta1=0, theta2=60, color="#7c3aed", lw=1.4))
ax.text(8.4, 3.0, "零位夹角 60°", fontsize=11, color="#7c3aed")
ax.add_patch(Arc(O, 40, 40, theta1=60, theta2=75, color="#0f766e", lw=1.6))
ax.annotate("转了 15°", xy=(6.4, 19.6), xytext=(0.6, 22.6), fontsize=10.5, color="#0f766e",
            arrowprops=dict(arrowstyle="->", color="#0f766e", lw=0.9))

ax.annotate("力臂 = 19.64 mm", xy=(F[0] + 0.3, F[1] + 0.2), xytext=(18.6, 16.2),
            fontsize=11, color="#dc2626",
            arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.0))

ax.text(0, -6.6, "转轴中心", fontsize=12, ha="center")
ax.text(31.6, -2.6, "绳的固定端", fontsize=12, color="#2563eb")
ax.text(11.4, 18.4, "绳的另一端", fontsize=12, color="#7c3aed")
ax.text(13.8, 1.4, "30 mm", fontsize=12, color="#2563eb")
ax.text(2.0, 9.4, "20 mm", fontsize=12, color="#7c3aed", rotation=60)
ax.text(21.6, 3.4, "绳长 26.46 mm", fontsize=12, color="#b45309", rotation=-40)

ax.set_xlim(-9, 44)
ax.set_ylim(-10, 28)
ax.set_xlabel("横向位置 / mm")
ax.set_ylabel("纵向位置 / mm")
ax.set_xticks([0, 10, 20, 30, 40])
ax.set_yticks([0, 10, 20])
ax.set_title("① 沿关节轴看下去：三个点、四段长度", fontsize=13.5, pad=12)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)

# ---------------- 右图 ----------------
tt = np.linspace(-70, 130, 700) * DEG
D = alpha + beta * np.cos(tt) + gamma * np.sin(tt)
s = np.sqrt(D)
r = (beta * np.sin(tt) - gamma * np.cos(tt)) / (2 * s)

ax2.plot(tt / DEG, s, color="#d97706", lw=3.2)
ax2.set_xlabel("关节转过的角度（度）", fontsize=11.5)
ax2.set_ylabel("绳长（mm）", color="#b45309", fontsize=11.5)
ax2.tick_params(axis="y", labelcolor="#b45309", labelsize=10)
ax2.tick_params(axis="x", labelsize=10)

ax3 = ax2.twinx()
ax3.plot(tt / DEG, r, color="#dc2626", lw=2.6)
ax3.set_ylabel("力臂（mm）", color="#dc2626", fontsize=11.5)
ax3.tick_params(axis="y", labelcolor="#dc2626", labelsize=10)
ax3.axhline(0, color="0.75", lw=1.0)

ax2.plot([0], [s0], marker="o", ms=9, color="k", zorder=5)
ax3.plot([0], [r0], marker="o", ms=9, color="k", zorder=5)
ax2.annotate("零位：绳长 26.46", xy=(0, s0), xytext=(-64, 40), fontsize=11,
             arrowprops=dict(arrowstyle="->", color="0.35"))
ax3.annotate("零位：力臂 −19.64\n（负号只表示方向）", xy=(0, r0), xytext=(26, -20.5), fontsize=11,
             color="#b91c1c", arrowprops=dict(arrowstyle="->", color="0.6"))
ax3.annotate("这里力臂 = 0：\n绳线正好穿过转轴", xy=(120, 0), xytext=(38, 6.2), fontsize=10.5,
             color="#0f766e", arrowprops=dict(arrowstyle="->", color="#0f766e"))

ax2.set_title("② 同一个关节：角度一变，绳长和力臂都变", fontsize=13.5, pad=12)
for sp in ("top",):
    ax2.spines[sp].set_visible(False)
    ax3.spines[sp].set_visible(False)

fig.text(0.012, 0.035,
         "蓝线 = 固定端到转轴的距离 30 mm     紫线 = 另一端到转轴的距离 20 mm     "
         "橙线 = 绳长 26.46 mm     红虚线 = 力臂（轴到绳的垂直距离）19.64 mm",
         fontsize=10.8, color="0.3")

fig.savefig("讲解图_变量对照.png", bbox_inches="tight", facecolor="white")
print("ok", s0, r0)

