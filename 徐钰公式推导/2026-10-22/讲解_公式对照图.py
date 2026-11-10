# -*- coding: utf-8 -*-
"""把第 3.6~4 节的公式渲染成一张对照图。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams["mathtext.fontset"] = "dejavusans"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

rows = [
    (r"$s^2=\alpha+\beta\cos\theta+\gamma\sin\theta$",
     "绳长的平方 = 三个常数 + cos 项 + sin 项"),
    (r"$\alpha=a^2+b^2+h^2$",
     "α 只由两条半径和轴向错开量决定"),
    (r"$\beta=-2\,(v_\perp\cdot u_\perp)$",
     "β 与两个半径的“对齐程度”有关"),
    (r"$\gamma=-2\,((\hat a\times v_\perp)\cdot u_\perp)$",
     "γ 与两个半径的“错开方向”有关"),
    (r"$\dfrac{ds}{d\theta}=\dfrac{\gamma\cos\theta-\beta\sin\theta}{2s}$",
     "角度变一点，绳长变多少"),
    (r"$r(\theta)=\dfrac{\beta\sin\theta-\gamma\cos\theta}{2s},\quad r(0)=-\dfrac{\gamma}{2\sqrt{\alpha+\beta}}$",
     "力臂：上面那个导数的相反数"),
    (r"$R=-\left(\dfrac{\partial l}{\partial q}\right)^{\mathrm{T}}$",
     "R 是“力臂矩阵”，2 行 3 列"),
    (r"$\tau=Rf,\quad f=R^{+}\tau+tw$",
     "张力 f 与关节力矩 τ 的换算"),
]

fig = plt.figure(figsize=(13.2, 8.6), dpi=200)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")

ax.text(0.04, 0.95, "这几行公式各是什么", fontsize=18, weight="bold", color="#0f172a")

y = 0.855
for i, (f, txt) in enumerate(rows):
    if i % 2 == 0:
        ax.add_patch(FancyBboxPatch((0.035, y - 0.043), 0.93, 0.086,
                                    boxstyle="round,pad=0.004,rounding_size=0.01",
                                    fc="#f4f7fc", ec="none", zorder=0))
    ax.text(0.06, y, f, fontsize=17, va="center", color="#111827")
    ax.text(0.60, y, txt, fontsize=11.5, va="center", color="#334155")
    y -= 0.104

ax.text(0.04, 0.045,
        r"说明：这些就是 Markdown 里的 LaTeX 源码排版后的样子；\$\$ 只是“公式开始/结束”的标记，不会出现在成品里。",
        fontsize=10.5, color="#64748b")

fig.savefig("讲解图_公式对照.png", bbox_inches="tight", facecolor="white")
print("ok")
