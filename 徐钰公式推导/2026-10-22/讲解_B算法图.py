# -*- coding: utf-8 -*-
"""B 的求法示例：俯视图 + 数值步骤。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

th = 30 * np.pi / 180
A = np.array([-27.0, 5.0])
B0 = np.array([-32.5, 18.0])
r = np.hypot(*B0)

def rot2(p, a):
    return np.array([p[0] * np.cos(a) + p[1] * np.sin(a),
                     p[1] * np.cos(a) - p[0] * np.sin(a)])

B = rot2(B0, th)

fig = plt.figure(figsize=(13.6, 6.4), dpi=190)
gs = fig.add_gridspec(1, 2, width_ratios=[1.5, 1], wspace=0.05)
ax = fig.add_subplot(gs[0, 0])
ax2 = fig.add_subplot(gs[0, 1])

# ---------------- 左：俯视 ----------------
ax.set_aspect("equal")
ax.set_xlim(-50, 32)
ax.set_ylim(-10, 46)
ax.axis("off")

ax.add_patch(Circle((0, 0), r, fill=False, color="0.75", lw=1.1, ls=(0, (4, 4))))
ax.plot([-46, 24], [0, 0], color="0.92", lw=1)
ax.plot([0, 0], [-6, 44], color="0.92", lw=1)

ax.annotate("", xy=B0, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#7c3aed", lw=2.4))
ax.annotate("", xy=B, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color="#a78bfa", lw=2.4))
ax.plot([A[0], B[0]], [A[1], B[1]], color="#d97706", lw=4.2, solid_capstyle="round", zorder=3)

arc = np.array([rot2(B0, th * i / 30.0) for i in range(31)]) * 0.55
ax.plot(arc[:, 0], arc[:, 1], color="#0f766e", lw=1.6)

ax.plot([A[0]], [A[1]], "o", ms=8, color="#2563eb", zorder=5)
ax.plot([B0[0]], [B0[1]], "o", ms=7, color="#7c3aed", zorder=5)
ax.plot([B[0]], [B[1]], "o", ms=8, color="#a78bfa", zorder=5)
ax.plot([0], [0], "o", ms=8, color="k", zorder=6)

ax.text(-1.6, -4.6, "轴心 o", fontsize=11, ha="right", va="top")
ax.text(-31.0, 1.0, "A = P4（固定端）", fontsize=11, color="#2563eb", ha="right")
ax.text(-42.0, 9.0, "B0 = P5（零位）", fontsize=11, color="#7c3aed")
ax.text(B[0] + 1.8, B[1] - 1.2, "B（转过 30°）", fontsize=11, color="#a78bfa")

ax.text(-25.0, 7.0, "v⊥", color="#7c3aed", fontsize=13)
ax.text(-12.0, 24.5, "v′⊥", color="#a78bfa", fontsize=13)
ax.text(-36.0, 25.0, "θ = 30°", color="#0f766e", fontsize=11)
ax.text(-17.0, -4.0, "s = 28.249 mm", color="#b45309", fontsize=12)
ax.text(1.5, r + 1.2, "半径 b = 37.15（不变）", color="0.45", fontsize=10.5)

ax.set_title("沿着 roll 轴看下去（x–z 平面）", fontsize=13.5, pad=8)

# ---------------- 右：步骤 ----------------
ax2.axis("off")
ax2.set_xlim(0, 1)
ax2.set_ylim(0, 1)
ax2.set_title("六步代入（C2 / roll，θ = 30°）", fontsize=13.5, pad=8)

lines = [
    ("① v = B0 − o", "(-32.5, -12, 18)"),
    ("② h = v·â", "−12"),
    ("③ v⊥ = v − h·â", "( -32.5, 0, 18 )"),
    ("④ v′⊥ = v⊥cosθ + (â×v⊥)sinθ", "( -19.15, 0, 31.84 )"),
    ("⑤ B = o + h·â + v′⊥", "( -19.15, -12, 31.84 )"),
    ("⑥ s = ‖B − A‖", "28.249 mm"),
]
y = 0.84
for f, v in lines:
    ax2.text(0.02, y, f, fontsize=10.4, color="#111827", va="top")
    ax2.text(0.97, y, v, fontsize=10.4, color="#b45309", va="top", ha="right", family="Consolas")
    y -= 0.105

ax2.text(0.02, 0.14,
         "俯视图看不到 h：h 沿轴方向，垂直于纸面。\n"
         "所以 B 的真实坐标 = 俯视图里的 (x, z) + 轴向的 y。",
         fontsize=10.4, color="0.35", va="top")

fig.savefig("讲解图_B的算法.png", bbox_inches="tight", facecolor="white")
print("ok", B, r)
