# -*- coding: utf-8 -*-
"""图解 α、β、γ 三个系数到底各管什么。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

fig = plt.figure(figsize=(13.6, 5.8), dpi=200)
axA = fig.add_axes([0.01, 0.04, 0.42, 0.88])
axB = fig.add_axes([0.52, 0.15, 0.45, 0.72])

# ================= 左：余弦定理 =================
axA.set_xlim(-5.0, 5.0)
axA.set_ylim(-4.0, 4.6)
axA.set_aspect("equal")
axA.axis("off")
axA.text(0.0, 4.30, "① 沿轴看下去：这就是余弦定理", fontsize=12.5, color="#222", ha="center")

a, b = 3.4, 2.6
psi = np.radians(122.0)
A = np.array([a, 0.0])
B = b * np.array([np.cos(psi), np.sin(psi)])
O = np.array([0.0, 0.0])

t = np.linspace(0, 2 * np.pi, 400)
axA.plot(b * np.cos(t), b * np.sin(t), color="#cfcfcf", lw=1.1, ls=(0, (4, 3)))
axA.plot([O[0], A[0]], [O[1], A[1]], color="#1f6fd0", lw=2.6, zorder=3)
axA.plot([O[0], B[0]], [O[1], B[1]], color="#e07b1a", lw=2.6, zorder=3)
axA.plot([A[0], B[0]], [A[1], B[1]], color="#2e8b57", lw=3.4, zorder=4)
axA.plot(*O, "o", ms=7, color="#333", zorder=5)
axA.plot(*A, "o", ms=7, mfc="white", mec="#1f6fd0", mew=2, zorder=5)
axA.plot(*B, "o", ms=7, mfc="white", mec="#e07b1a", mew=2, zorder=5)

axA.text(-0.18, -0.42, "o（轴心）", fontsize=10.5, ha="right", va="top", color="#444")
axA.text(A[0] + 0.16, A[1] - 0.10, "A\n（固定端）", fontsize=10.5, color="#1f6fd0", va="top")
axA.text(B[0] - 0.05, B[1] + 0.28, "B(θ)\n（运动端）", fontsize=10.5, color="#e07b1a",
         ha="center", va="bottom")

axA.text(1.75, -0.38, "a = ‖u⊥‖", fontsize=11, color="#1f6fd0", ha="center", va="top")
axA.text(-1.62, 1.22, "b = ‖v⊥‖", fontsize=11, color="#e07b1a", ha="center")

mid = (A + B) / 2
d = B - A
ang = np.degrees(np.arctan2(d[1], d[0]))
axA.text(mid[0] + 0.55, mid[1] + 1.02, "s = √D", fontsize=12, color="#2e8b57",
         ha="center", rotation=ang - 180)

axA.add_patch(Arc((0, 0), 1.75, 1.75, theta1=0, theta2=122, color="#777", lw=1.2))
axA.text(1.02, 0.44, "θ + ψ0", fontsize=10.5, color="#555")

axA.text(0.0, -1.75, "s² = a² + b² − 2ab·cos(θ + ψ0)", fontsize=13, color="#222", ha="center")
axA.text(0.0, -2.55, "把 cos(θ+ψ0) 展开，就归并成三项：\n"
                     "常数 → α　　　cos 项 → β　　　sin 项 → γ", fontsize=11, color="#555",
         ha="center", va="top", linespacing=1.9)

# ================= 右：D(θ) 解剖 =================
al, be, ga = 2150.25, -1935.0, 647.0
rho = float(np.hypot(be, ga))
phi = float(np.degrees(np.arctan2(ga, be)))
th = np.linspace(-180, 180, 720)
D = al + be * np.cos(np.radians(th)) + ga * np.sin(np.radians(th))

axB.plot(th, D, color="#1f6fd0", lw=2.5, zorder=3)
axB.axhline(al, color="#8c8c8c", lw=1.2, ls=(0, (5, 3)), zorder=2)
axB.set_xlim(-180, 180)
axB.set_ylim(-300, 5000)
axB.set_xlabel("关节角 θ / °", fontsize=11)
axB.set_ylabel("D = s² / mm²", fontsize=11)
axB.grid(alpha=0.25, ls=":")
axB.set_title("② D(θ) = α + ρ·cos(θ − φ0)　（C2 的 roll 段）", fontsize=12, pad=12)

axB.annotate("α：整圈的平均值（基线）\nα = 2150.25 mm²", xy=(-125, al), xytext=(-176, 3200),
             fontsize=10.5, color="#555",
             arrowprops=dict(arrowstyle="->", color="#888", lw=1.1))

axB.annotate("", xy=(phi, al + rho), xytext=(phi, al),
             arrowprops=dict(arrowstyle="<->", color="#e07b1a", lw=1.8))
axB.text(phi - 7, al + rho * 0.52, "ρ = 2ab\n= 2040.3", fontsize=10.5, color="#e07b1a",
         ha="right", va="center")

axB.plot(phi, al + rho, "o", ms=7, color="#2e8b57", zorder=5)
axB.annotate("最长 θ=φ0，√(α+ρ)=64.73 mm", xy=(phi, al + rho), xytext=(-10, 4700),
             fontsize=10, color="#2e8b57",
             arrowprops=dict(arrowstyle="->", color="#2e8b57", lw=1.0))

tmin = phi - 180
axB.plot(tmin, al - rho, "o", ms=7, color="#c0392b", zorder=5)
axB.annotate("最短 √(α−ρ)=10.49 mm", xy=(tmin, al - rho), xytext=(-178, 620),
             fontsize=10, color="#c0392b",
             arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.0))

axB.plot(0, al + be, "s", ms=8, color="#7b3fa0", zorder=5)
axB.annotate("零位 θ=0 时 D=215.25，\n力臂 r(0)=−γ/(2√D)=−22.05", xy=(0, al + be), xytext=(62, 480),
             fontsize=10, color="#7b3fa0",
             arrowprops=dict(arrowstyle="->", color="#7b3fa0", lw=1.0))

fig.savefig("讲解图_αβγ含义.png", facecolor="white", bbox_inches="tight", pad_inches=0.15)
print("saved", phi)
