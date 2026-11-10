# -*- coding: utf-8 -*-
"""示意图：l_i = c_i + s_ri(θr) + s_pi(θp)"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Arc
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

W, H = 13.6, 6.8
fig = plt.figure(figsize=(W, H), dpi=200)
ax = fig.add_axes([0.015, 0.06, 0.60, 0.86])
ax2 = fig.add_axes([0.635, 0.06, 0.35, 0.86])
for a in (ax, ax2):
    a.set_xlim(0, 10)
    a.set_ylim(0, 6.4)
    a.axis("off")

# ---------------- 左：三个刚体 + 一条绳 ----------------
boxes = [
    (0.35, 1.15, 2.60, 3.35, "固定板 base", "#edf3fb", "#7fa8d4"),
    (3.25, 1.15, 2.30, 3.35, "roll 件", "#fdf1e7", "#dfa76b"),
    (5.75, 1.15, 3.55, 3.35, "手掌 palm", "#ebf7ef", "#7fbf95"),
]
for x, y, w, h, nm, fc, ec in boxes:
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.10",
                                fc=fc, ec=ec, lw=1.5))
    ax.text(x + w / 2, y + h - 0.30, nm, ha="center", va="center", fontsize=12, color="#333")

# 铰链虚线
for hx in (3.10, 5.60):
    ax.plot([hx, hx], [1.35, 4.30], color="#aaa", lw=1.0, ls=(0, (4, 3)), zorder=1)

# 绳路点
P = {1: (0.85, 3.60), 2: (0.85, 3.00), 3: (1.85, 2.05), 4: (2.65, 2.35),
     5: (3.50, 2.10), 6: (5.30, 2.35), 7: (6.10, 3.35), 8: (7.85, 3.15)}
fixed = [(1, 2), (2, 3), (3, 4), (5, 6), (7, 8)]

for a_, b_ in fixed:
    ax.plot([P[a_][0], P[b_][0]], [P[a_][1], P[b_][1]], color="#8a6d3b", lw=2.0, zorder=3)

# 跨段（画在盒子之上）
ax.plot([P[4][0], P[5][0]], [P[4][1], P[5][1]], color="#1f6fd0", lw=5.2,
        solid_capstyle="round", zorder=4)
ax.plot([P[6][0], P[7][0]], [P[6][1], P[7][1]], color="#e07b1a", lw=5.2,
        solid_capstyle="round", zorder=4)

for k, (x, y) in P.items():
    ax.plot(x, y, "o", ms=7, mfc="white", mec="#555", mew=1.5, zorder=5)
    off = {1: (-0.10, 0.30), 2: (-0.10, -0.30), 3: (0.0, -0.34), 4: (0.0, 0.30),
           5: (0.12, -0.34), 6: (0.0, 0.30), 7: (-0.02, 0.32), 8: (0.22, 0.02)}[k]
    ha = "right" if k in (1, 2) else ("left" if k == 8 else "center")
    ax.text(x + off[0], y + off[1], f"P{k}", ha=ha, va="center", fontsize=11, color="#333")

# 转角
ax.add_patch(Arc((3.10, 2.85), 0.80, 0.80, theta1=250, theta2=105, color="#1f6fd0", lw=1.5))
ax.text(3.10, 3.36, "θr", color="#1f6fd0", fontsize=12, ha="center")
ax.add_patch(Arc((5.60, 2.85), 0.80, 0.80, theta1=250, theta2=105, color="#e07b1a", lw=1.5))
ax.text(5.60, 3.36, "θp", color="#e07b1a", fontsize=12, ha="center")

# 跨段就近标注
ax.text(3.07, 1.62, "s_ri(θr)", color="#1f6fd0", fontsize=11.5, ha="center")
ax.text(5.70, 1.62, "s_pi(θp)", color="#e07b1a", fontsize=11.5, ha="center")

# 提示框（放盒子上方，避免压字）
ax.text(7.55, 5.10, "P6–P7 会被 roll 带着整体转：\n方向在变，长度不变", fontsize=10.5,
        color="#555", ha="center", va="center",
        bbox=dict(boxstyle="round,pad=0.40", fc="#f8f8f8", ec="#d5d5d5"))

# 图例
leg = [("#8a6d3b", 2.0, "细线：5 段同刚体距离，合计 c_i（不变）"),
       ("#1f6fd0", 5.2, "蓝粗线：跨 roll 的 s_ri(θr)"),
       ("#e07b1a", 5.2, "橙粗线：跨 pitch 的 s_pi(θp)")]
for i, (c, lw, t) in enumerate(leg):
    y = 0.70 - i * 0.001  # 三行用不同 x 排开更省高度，这里改用单行说明
ax.text(0.15, 0.62, "细线 = 5 段固定长度（合计 c_i）   ",
        fontsize=10.5, color="#8a6d3b", ha="left", va="center")
ax.text(4.05, 0.62, "蓝 = s_ri(θr)   ", fontsize=10.5, color="#1f6fd0", ha="left", va="center")
ax.text(6.35, 0.62, "橙 = s_pi(θp)", fontsize=10.5, color="#e07b1a", ha="left", va="center")
ax.text(0.15, 5.10, "示意，不按比例", fontsize=9.5, color="#999", ha="left", va="center")

# ---------------- 右：正交矩阵不改长度 ----------------

ax2.text(5.1, 5.55, "为什么能“消掉”一个角", ha="center", fontsize=13.5, color="#222")
ax2.text(5.1, 4.95, "‖Q_r·w‖ = ‖w‖", ha="center", fontsize=15, color="#222")
ax2.text(5.1, 4.40, "旋转只改方向、不改长度，\n所以 P6–P7 这段的长度\n与 roll 角完全无关。",
         ha="center", va="top", fontsize=11, color="#555", linespacing=1.7)

o = np.array([2.45, 1.45])
w = np.array([1.85, 0.95])           # pitch 段向量（灰色虚线）
th = np.radians(56)
Q = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
qw = o + Q @ w                        # 被 roll 转过之后（橙色）

ax2.annotate("", xy=o + w, xytext=o,
             arrowprops=dict(arrowstyle="-|>", color="#999", lw=1.9, ls=(0, (5, 3)),
                             mutation_scale=16))
ax2.annotate("", xy=qw, xytext=o,
             arrowprops=dict(arrowstyle="-|>", color="#e07b1a", lw=2.8, mutation_scale=18))
ax2.text(4.55, 2.35, "w（θp 段向量）", color="#777", fontsize=11, ha="left", va="center")
ax2.text(o[0] - 0.18, 2.75, "Q_r·w\n（转过 θr）", color="#e07b1a", fontsize=11,
         ha="right", va="center", linespacing=1.4)
ax2.plot(*o, "o", ms=6, color="#333", zorder=5)
ax2.text(o[0] - 0.14, o[1] - 0.14, "o", fontsize=11, color="#333", ha="right", va="top")
ax2.add_patch(Arc(tuple(o), 1.55, 1.55, theta1=27, theta2=82, color="#1f6fd0", lw=1.4))
ax2.text(o[0] + 0.72, o[1] + 0.88, "θr", color="#1f6fd0", fontsize=11, ha="left")

ax2.text(5.1, 0.62, "总长 = 常数 + 只含 θr + 只含 θp", ha="center", fontsize=13,
         color="#1f5fa8",
         bbox=dict(boxstyle="round,pad=0.45", fc="#f2f7ff", ec="#9cbfe8"))

fig.savefig("讲解图_解耦公式.png", facecolor="white", bbox_inches="tight", pad_inches=0.15)
print("saved")
