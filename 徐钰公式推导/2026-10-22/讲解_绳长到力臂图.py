# -*- coding: utf-8 -*-
"""图解：绳长只是中间量，力臂才是控制要用的。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

AL, BE, GA = 1300.0, -600.0, 1039.2304845413264          # 30/20/60° 例子的三个数
s_of = lambda th: np.sqrt(AL + BE * np.cos(th) + GA * np.sin(th))
r_of = lambda th: (BE * np.sin(th) - GA * np.cos(th)) / (2 * s_of(th))

fig = plt.figure(figsize=(13.6, 7.6), dpi=200)

# ---------------- 顶部：流程 ----------------
axP = fig.add_axes([0.02, 0.78, 0.96, 0.20])
axP.set_xlim(0, 100)
axP.set_ylim(-4, 26)
axP.axis("off")

steps = [
    ("① 零位几何", "8 个点位 + 轴线\n（CAD 量出来）", "#eef3fb", "#7fa8d4"),
    ("② 绳长 s(θ)", "这根绳现在多长\ns = √D", "#fdf3e7", "#dfa76b"),
    ("③ 力臂 r(θ)", "每 1 N 张力\n给多大扭矩\nr = −ds/dθ", "#fdecea", "#d98080"),
    ("④ 矩阵 R", "2 行 × 3 列\n6 个数", "#eef7f0", "#7fbf95"),
    ("⑤ 力矩 τ", "τ = R · f\n真正拿去用", "#f3eefb", "#a58bc4"),
]
w, h, gap = 16.0, 18.0, 3.4
x0 = 2.0
for i, (title, body, fc, ec) in enumerate(steps):
    x = x0 + i * (w + gap)
    box = FancyBboxPatch((x, 3.0), w, h, boxstyle="round,pad=0.3,rounding_size=1.2",
                         fc=fc, ec=ec, lw=1.6)
    axP.add_patch(box)
    axP.text(x + w / 2, 17.6, title, ha="center", va="center", fontsize=12, color="#222")
    axP.text(x + w / 2, 10.2, body, ha="center", va="center", fontsize=9.6, color="#555",
             linespacing=1.6)
    if i < len(steps) - 1:
        axP.annotate("", xy=(x + w + gap - 0.4, 12.0), xytext=(x + w + 0.4, 12.0),
                     arrowprops=dict(arrowstyle="-|>", color="#999", lw=1.8,
                                     mutation_scale=16))
axP.text(50, -2.2, "绳长走到第 ② 步就够了吗？不够——控制要的是第 ③ 步的力臂",
         ha="center", fontsize=10.5, color="#b03a2e")

# ---------------- 中部：绳长 ----------------
axS = fig.add_axes([0.085, 0.455, 0.575, 0.245])
th = np.linspace(-100, 130, 800)
axS.plot(th, s_of(np.radians(th)), color="#d9822b", lw=2.4)
axS.set_ylabel("绳长 s / mm", fontsize=10.5, color="#d9822b")
axS.set_xlim(-100, 130)
axS.set_ylim(0, 58)
axS.grid(alpha=0.22, ls=":")
axS.tick_params(labelsize=9)
axS.set_title("绳长随角度变化：一条余弦波形状的曲线", fontsize=11, pad=6)

# 切线
t0 = 0.0
s0 = float(s_of(np.radians(t0)))
slope = float(-r_of(np.radians(t0)))          # ds/dθ = -r
tt = np.linspace(-45, 45, 2)
axS.plot(tt, s0 + slope * np.radians(tt - t0), color="#888", lw=1.4, ls=(0, (5, 3)))
axS.plot(t0, s0, "o", ms=8, color="#d9822b", zorder=5)
axS.annotate("θ=0：绳长 26.46 mm\n切线斜率 = +19.64 mm/rad",
             xy=(t0, s0), xytext=(-95, 46), fontsize=10, color="#7a4a12",
             arrowprops=dict(arrowstyle="->", color="#888", lw=1.0))

# ---------------- 下部：力臂 ----------------
axR = fig.add_axes([0.085, 0.105, 0.575, 0.265])
axR.plot(th, r_of(np.radians(th)), color="#c0392b", lw=2.4)
axR.axhline(0, color="#999", lw=0.9)
axR.set_ylabel("力臂 r / mm", fontsize=10.5, color="#c0392b")
axR.set_xlabel("关节角 θ / °", fontsize=10.5)
axR.set_xlim(-100, 130)
axR.set_ylim(-28, 24)
axR.grid(alpha=0.22, ls=":")
axR.tick_params(labelsize=9)
axR.set_title("力臂 = 绳长曲线的斜率取负：同一个姿态、不同的信息", fontsize=11, pad=6)

axR.plot(t0, float(r_of(np.radians(t0))), "o", ms=8, color="#c0392b", zorder=5)
axR.annotate("同一姿态：r = −19.64 mm\n（负号 = 张力阻碍正转）",
             xy=(t0, float(r_of(np.radians(t0)))), xytext=(24, -26),
             fontsize=10, color="#7a1f14",
             arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1.0))
# 死点
for ang, txt, xytext in ((-60, "此处 r = 0\n（绳线穿过轴）", (-96, 6)),
                         (120, "此处 r = 0", (95, 6))):
    axR.plot(ang, 0, "o", ms=7, mfc="white", mec="#c0392b", mew=1.8, zorder=5)
    axR.annotate(txt, xy=(ang, 0), xytext=xytext, fontsize=9.5, color="#7a1f14",
                 arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.9))

# 上下对齐虚线
for ax in (axS, axR):
    ax.axvline(0, color="#bbb", lw=1.0, ls=":")

# ---------------- 右侧：三个量各回答什么 ----------------
axT = fig.add_axes([0.70, 0.10, 0.29, 0.60])
axT.axis("off")
axT.text(0.0, 1.0, "三个量，各回答一个问题", fontsize=12, va="top", color="#222")
items = [
    ("绳长 s", "现在多长？→ 决定收放线量\n→ 会不会短到危险", "#d9822b"),
    ("力臂 r", "每 1 N 给多大扭矩？\n→ 控制真正用这个", "#c0392b"),
    ("力矩 τ", "关节实际受多大力？\nτ = R·f", "#7b3fa0"),
]
y = 0.86
for name, body, col in items:
    axT.text(0.02, y, name, fontsize=12, color=col, va="top", fontweight="bold")
    axT.text(0.02, y - 0.055, body, fontsize=10, color="#555", va="top", linespacing=1.65)
    y -= 0.245
fig.savefig("讲解图_绳长只是中间量.png", facecolor="white", bbox_inches="tight", pad_inches=0.18)
print("saved", s0, slope)
