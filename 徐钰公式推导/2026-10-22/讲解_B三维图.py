# -*- coding: utf-8 -*-
"""B 点求解的三维示意（C2 / roll, θ=25°）——突出 v 与 v'。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

A = np.array([-27.0, -16.0, 5.0])
B0 = np.array([-32.5, -12.0, 18.0])
r = np.hypot(B0[0], B0[2])
th = np.radians(30)

def rotY(p, a):
    return np.array([p[0] * np.cos(a) + p[2] * np.sin(a), p[1],
                     p[2] * np.cos(a) - p[0] * np.sin(a)])

B = rotY(B0, th)
P0 = np.array([B0[0], 0.0, B0[2]])   # B0 在轴上的垂足

fig = plt.figure(figsize=(13.6, 7.4), dpi=185)
ax = fig.add_subplot(1, 2, 1, projection="3d")
ax.set_position([0.0, 0.02, 0.52, 0.92])
ax2 = fig.add_subplot(1, 2, 2)
ax2.axis("off")

# ---------- 轴 ----------
ax.plot([0, 0], [-6, 46], [0, 0], color="0.55", lw=1.2, ls=(0, (5, 5)), zorder=1)
ax.quiver(0, 44, 0, 0, 8, 0, color="0.45", arrow_length_ratio=0.25, lw=1.2)
ax.text(0, 53, 0, "+Y（roll 轴）", fontsize=10, color="0.35")

# ---------- 圆 ----------
t = np.linspace(0, 2 * np.pi, 200)
ax.plot(r * np.cos(t), np.full_like(t, -12.0), r * np.sin(t),
        color="0.72", lw=1.0, ls=(0, (4, 4)), zorder=1)
ax.text(0, -12, r + 4, "B 能到达的圆：半径 b = 37.15", fontsize=9.5, color="0.45", ha="center")

# ---------- 两个主向量 ----------
ax.quiver(0, 0, 0, B0[0], B0[1], B0[2], color="#7c3aed",
          arrow_length_ratio=0.13, linewidth=2.6, zorder=5)
ax.quiver(0, 0, 0, B[0], B[1], B[2], color="#0891b2",
          arrow_length_ratio=0.13, linewidth=2.8, zorder=5)

# ---------- h：B0 到轴上的垂足 ----------
ax.plot([B0[0], P0[0]], [B0[1], P0[1]], [B0[2], P0[2]],
        color="#f59e0b", lw=2.2, zorder=4)
ax.scatter(*P0, s=30, color="#f59e0b", zorder=5)

# ---------- 绳 ----------
ax.plot([A[0], B[0]], [A[1], B[1]], [A[2], B[2]], color="#d97706", lw=4.2, zorder=3)

# ---------- 点 ----------
ax.scatter(*A, s=75, color="#2563eb", zorder=6)
ax.scatter(*B0, s=65, color="#7c3aed", zorder=6)
ax.scatter(*B, s=75, color="#0891b2", zorder=6)
ax.scatter(0, 0, 0, s=65, color="k", zorder=6)

# ---------- 标注 ----------
ax.text(A[0] - 1, A[1] - 4, A[2] - 4, "A = P4（固定端）", fontsize=10, color="#2563eb")
ax.text(B0[0] - 2, B0[1] - 7, B0[2] - 5, "B0 = P5（零位）", fontsize=10, color="#7c3aed")
ax.text(B[0] + 2, B[1] - 1, B[2] + 2, "B（转过 30°）", fontsize=10, color="#0891b2")
ax.text(1.5, -3.5, 0, "o", fontsize=12, color="k")

ax.text(-16, -8, 9, "v", fontsize=13, color="#7c3aed")
ax.text(-7, -6, 22, "v′", fontsize=13, color="#0891b2")
ax.text(-24, -1, 27, "h = −12", fontsize=9.5, color="#b45309")
ax.text(-8, -19, 4, "s = 28.249", fontsize=10.5, color="#b45309")

ax.set_xlim(-42, 14)
ax.set_ylim(-22, 52)
ax.set_zlim(-8, 42)
ax.set_box_aspect((56, 74, 50), zoom=1.45)
ax.view_init(elev=20, azim=-58)
ax.set_axis_off()
ax.set_title("三维：v 绕轴转 θ 得到 v′（= 新的 B）", fontsize=13.5, pad=0)

# ---------- 右侧说明 ----------
ax2.set_xlim(0, 1)
ax2.set_ylim(0, 1)
ax2.set_title("同一个过程，六步数值", fontsize=13.5, pad=8)

rows = [
    ("v = B0 − o", "(−32.5, −12, 18)"),
    ("h = v·â", "−12"),
    ("v⊥ = v − h·â", "(−32.5, 0, 18)"),
    ("v′⊥ = v⊥cosθ + (â×v⊥)sinθ", "(−19.15, 0, 31.84)"),
    ("B = o + h·â + v′⊥", "(−19.15, −12, 31.84)"),
    ("s = ‖B − A‖", "28.249 mm"),
]
y = 0.86
for f, v in rows:
    ax2.text(0.02, y, f, fontsize=10.6, color="#111827", va="top")
    ax2.text(0.97, y, v, fontsize=10.6, color="#b45309", va="top", ha="right", family="Consolas")
    y -= 0.11

ax2.text(0.02, 0.17,
         "紫色箭头 v = 零位向量（不动）\n"
         "青色箭头 v′ = 转过 θ 之后的同一根向量\n"
         "橙色短线 h = 沿轴那段，转的时候不变\n"
         "末端的青点就是新的 B",
         fontsize=10.5, color="0.32", va="top", linespacing=1.9)

fig.savefig("讲解图_B三维.png", bbox_inches="tight", facecolor="white")
print("ok", B, r)
