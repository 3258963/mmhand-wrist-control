# -*- coding: utf-8 -*-
"""图解 α、β、γ 的定义：三维怎么分解，沿轴看是什么，三个数怎么来。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Arc
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

fig = plt.figure(figsize=(13.8, 7.2), dpi=200)
ax1 = fig.add_axes([0.02, 0.36, 0.46, 0.58])
ax2 = fig.add_axes([0.52, 0.36, 0.46, 0.58])
ax3 = fig.add_axes([0.02, 0.02, 0.96, 0.26])
for a in (ax1, ax2):
    a.set_aspect("equal")
    a.axis("off")

# ================= 左：三维分解 =================
ax1.set_xlim(-1.6, 7.6)
ax1.set_ylim(-2.8, 3.4)
ax1.set_title("① 三维：把两个点拆成「沿轴」和「垂直轴」两部分", fontsize=11.5, pad=6)

ax1.annotate("", xy=(7.2, 0), xytext=(-1.4, 0),
             arrowprops=dict(arrowstyle="-|>", color="#333", lw=2.0, mutation_scale=16))
ax1.text(7.2, -0.30, "关节轴 a（单位向量）", fontsize=10.5, color="#333", ha="right")

O = np.array([0.0, 0.0])
A = np.array([2.4, 2.4])
B = np.array([4.6, -1.4])

# 垂直分量：从轴上的垂足连到点
ax1.annotate("", xy=A, xytext=(A[0], 0),
             arrowprops=dict(arrowstyle="<|-|>", color="#1f6fd0", lw=1.5, mutation_scale=12))
ax1.annotate("", xy=B, xytext=(B[0], 0),
             arrowprops=dict(arrowstyle="<|-|>", color="#e07b1a", lw=1.5, mutation_scale=12))
ax1.text(A[0] - 0.22, A[1] / 2, "u⊥", fontsize=11, color="#1f6fd0", ha="right", va="center")
ax1.text(B[0] + 0.22, B[1] / 2, "v⊥", fontsize=11, color="#e07b1a", ha="left", va="center")

# u、v
ax1.annotate("", xy=A, xytext=O,
             arrowprops=dict(arrowstyle="-|>", color="#1f6fd0", lw=2.6, mutation_scale=16))
ax1.annotate("", xy=B, xytext=O,
             arrowprops=dict(arrowstyle="-|>", color="#e07b1a", lw=2.6, mutation_scale=16))
ax1.text(A[0] + 0.16, A[1] + 0.30, "A（固定端）", fontsize=10.5, color="#1f6fd0")
ax1.text(B[0] + 0.16, B[1] - 0.34, "B0（运动端零位）", fontsize=10.5, color="#e07b1a")
ax1.text(1.02, 1.35, "u", fontsize=12, color="#1f6fd0")
ax1.text(1.92, -0.98, "v", fontsize=12, color="#e07b1a")

# 轴向错位
ax1.plot([A[0], B[0]], [0.0, 0.0], color="#2e8b57", lw=6.0, solid_capstyle="butt", zorder=2)
ax1.text((A[0] + B[0]) / 2, -0.52, "u∥ − v∥（沿轴错位）", fontsize=10, color="#2e8b57",
         ha="center")
ax1.plot([A[0], A[0]], [-0.12, 0.12], color="#2e8b57", lw=1.4)
ax1.plot([B[0], B[0]], [-0.12, 0.12], color="#2e8b57", lw=1.4)

ax1.plot(*O, "o", ms=7, color="#333", zorder=5)
ax1.text(-0.30, -0.62, "o（轴上一点）", fontsize=10, color="#333", ha="left")
ax1.text(-1.4, 2.95, "沿轴分量 u∥ = (a·u)·a ；垂直分量 u⊥ = u − u∥", fontsize=9.5, color="#777")

# ================= 右：沿轴看 =================
ax2.set_xlim(-3.6, 3.9)
ax2.set_ylim(-3.1, 3.1)
ax2.set_title("② 沿轴看下去：三角形里就是余弦定理", fontsize=11.5, pad=6)

a_len, b_len = 2.5, 1.9
psi = np.radians(112)
A2 = np.array([a_len, 0.0])
B2 = b_len * np.array([np.cos(psi), np.sin(psi)])

t = np.linspace(0, 2 * np.pi, 300)
ax2.plot(b_len * np.cos(t), b_len * np.sin(t), color="#d2d2d2", lw=1.0, ls=(0, (4, 3)))
ax2.text(0.30, 2.42, "B 转一圈的轨迹", fontsize=9.5, color="#999", ha="left")

ax2.plot([0, A2[0]], [0, A2[1]], color="#1f6fd0", lw=2.6)
ax2.plot([0, B2[0]], [0, B2[1]], color="#e07b1a", lw=2.6)
ax2.plot([A2[0], B2[0]], [A2[1], B2[1]], color="#2e8b57", lw=3.6)
ax2.plot(0, 0, "o", ms=6.5, color="#333", zorder=5)
ax2.plot(*A2, "o", ms=6.5, mfc="white", mec="#1f6fd0", mew=2, zorder=5)
ax2.plot(*B2, "o", ms=6.5, mfc="white", mec="#e07b1a", mew=2, zorder=5)

ax2.text(A2[0] + 0.14, A2[1] - 0.30, "A′", fontsize=11, color="#1f6fd0", va="top")
ax2.text(B2[0] - 0.05, B2[1] + 0.24, "B′", fontsize=11, color="#e07b1a", ha="center")
ax2.text(1.30, -0.34, "a = ‖u⊥‖", fontsize=11, color="#1f6fd0", ha="center", va="top")
ax2.text(-1.62, 1.30, "b = ‖v⊥‖", fontsize=11, color="#e07b1a", ha="center")
mid = (A2 + B2) / 2
ax2.text(mid[0] + 0.55, mid[1] + 0.62, "s", fontsize=12.5, color="#2e8b57")
ax2.add_patch(Arc((0, 0), 1.30, 1.30, theta1=0, theta2=112, color="#666", lw=1.0))
ax2.text(0.80, 0.44, "ψ0", fontsize=11.5, color="#555")
ax2.text(-3.5, -2.55, "s² = a² + b² − 2ab·cosψ0", fontsize=11.5, color="#333", ha="left")
ax2.text(-3.5, -2.95, "（这就是余弦定理）", fontsize=9.5, color="#777", ha="left")

# ================= 下：三张定义卡 =================
ax3.axis("off")
ax3.set_xlim(0, 100)
ax3.set_ylim(0, 26)

cards = [
    ("α", "α = ‖u⊥‖² + ‖v⊥‖² + (u∥ − v∥)²",
     "两个垂距的平方，加上轴向错位的平方\n= 与转角无关的“平均值”", "#eef3fb", "#4a7fb5"),
    ("β", "β = −2 u⊥·v⊥ = −2ab·cosψ0",
     "零位时两个垂距“面对面”有多正\n= cos 项", "#fdf3e7", "#c07f36"),
    ("γ", "γ = 2 a·(u⊥×v⊥) = 2ab·sinψ0",
     "零位时两个垂距“错开”有多斜\n= sin 项", "#fdecea", "#b5564f"),
]
w, gap, x0 = 30.4, 2.4, 1.6
for i, (sym, formula, meaning, fc, ec) in enumerate(cards):
    x = x0 + i * (w + gap)
    ax3.add_patch(FancyBboxPatch((x, 1.0), w, 23.0, boxstyle="round,pad=0.35,rounding_size=1.0",
                                 fc=fc, ec=ec, lw=1.5))
    ax3.text(x + 3.0, 19.6, sym, fontsize=18, color=ec, fontweight="bold", va="center", ha="center")
    ax3.text(x + w / 2 + 1.2, 19.6, formula, fontsize=10.8, color="#222", va="center", ha="center")
    ax3.text(x + w / 2, 8.6, meaning, fontsize=10.2, color="#555", ha="center", va="center",
             linespacing=1.8)

fig.savefig("讲解图_αβγ定义.png", facecolor="white", bbox_inches="tight", pad_inches=0.18)
print("saved")
