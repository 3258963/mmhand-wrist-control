# -*- coding: utf-8 -*-
"""三维旋转矩阵（绕 Z / X / Y 轴）配图脚本 —— v2

图1_二维推导.png      2D 热身：V* 的两个分量 = cos(φ+θ)、sin(φ+θ)
图2_三轴总览.png      3D 三连图：绕 Z / X / Y 各转 60°，沿轴分量不动
图3_沿轴俯视.png      沿轴看下去：三张 2D 视图，正转都是逆时针
图4_顺序不可交换.png  Rz·Rx 与 Rx·Rz 的结果姿态不同
"""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

BLUE = "#1f6fd0"
ORANGE = "#e07b1a"
PURPLE = "#7d3c98"
GRAY = "#9a9a9a"
DARK = "#333333"
GREEN = "#1e8449"
RED = "#c0392b"
NAVY = "#2471a3"

DEG = np.pi / 180.0


# ============================ 数学 ============================
def R_axis(axis, deg):
    t = deg * DEG
    c, s = np.cos(t), np.sin(t)
    if axis == "z":
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    if axis == "x":
        return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    if axis == "y":
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    raise ValueError(axis)


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


# ============================ 3D 工具 ============================
def ax3d(fig, rect, elev=20, azim=-58, lim=1.06, zoom=1.30):
    ax = fig.add_axes(rect, projection="3d")
    ax.set_proj_type("ortho")
    ax.set_box_aspect((1, 1, 1), zoom=zoom)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_zlim(-lim, lim)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    return ax


def axes3(ax, L=1.12, lw=1.1, color=GRAY, fs=11.5, names=("x", "y", "z"), labels=True):
    for i in range(3):
        d = np.eye(3)[i]
        ax.quiver(0, 0, 0, *(d * L), color=color, lw=lw,
                  arrow_length_ratio=0.10, zorder=1)
        if labels:
            p = d * (L + 0.10)
            ax.text(*p, names[i], color=DARK, fontsize=fs, ha="center",
                    va="center", zorder=8)


def vec3(ax, v, color, lw=3.2, head=0.09, z=6):
    ax.quiver(0, 0, 0, *v, color=color, lw=lw, arrow_length_ratio=head, zorder=z)


def arc_pts(axis, v, d0, d1, n=120):
    a = unit(axis)
    par = np.dot(v, a) * a
    pp = v - par
    r = np.linalg.norm(pp)
    e1 = pp / r
    e2 = np.cross(a, e1)
    t = np.linspace(d0 * DEG, d1 * DEG, n)
    return par + r * (np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2)


def arc3(ax, axis, v, d0, d1, color=ORANGE, lw=2.2, dashed=False, head=0.075, z=4):
    p = arc_pts(axis, v, d0, d1)
    kw = dict(color=color, lw=lw, zorder=z)
    if dashed:
        kw["ls"] = (0, (3, 4))
    ax.plot(p[:, 0], p[:, 1], p[:, 2], **kw)
    if not dashed:
        d = p[-1] - p[-5]
        ax.quiver(*p[-5], *d, color=color, lw=lw,
                  arrow_length_ratio=head / np.linalg.norm(d), zorder=z)


def sector3(ax, axis, v, d0, d1, color=ORANGE, alpha=0.10):
    a = unit(axis)
    par = np.dot(v, a) * a
    pp = v - par
    r = np.linalg.norm(pp)
    e1 = pp / r
    e2 = np.cross(a, e1)
    t = np.linspace(d0, d1, 40) * DEG
    pts = [par] + [par + r * (np.cos(x) * e1 + np.sin(x) * e2) for x in t]
    poly = Poly3DCollection([pts], facecolor=color, alpha=alpha,
                            edgecolor="none", zorder=0)
    ax.add_collection3d(poly)


# ============================ 图1：二维推导 ============================
def fig_2d():
    fig = plt.figure(figsize=(9.4, 5.4), dpi=200)
    ax = fig.add_axes([0.03, 0.10, 0.50, 0.86])
    ax.set_xlim(-0.35, 1.28)
    ax.set_ylim(-0.30, 1.22)
    ax.set_aspect("equal")
    ax.axis("off")

    phi, th = 18.0, 42.0
    V = np.array([np.cos(phi * DEG), np.sin(phi * DEG)])
    Vs = np.array([np.cos((phi + th) * DEG), np.sin((phi + th) * DEG)])

    t = np.linspace(-4, 72, 200) * DEG
    ax.plot(np.cos(t), np.sin(t), color="#dcdcdc", lw=1.2, ls=(0, (3, 4)), zorder=0)

    ax.annotate("", xy=(1.20, 0), xytext=(-0.10, 0),
                arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.3,
                                shrinkA=0, shrinkB=0))
    ax.annotate("", xy=(0, 1.16), xytext=(0, -0.10),
                arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.3,
                                shrinkA=0, shrinkB=0))
    ax.text(1.23, -0.06, "x", fontsize=13, color=DARK)
    ax.text(-0.09, 1.18, "y", fontsize=13, color=DARK)

    # V* 的两个分量
    ax.plot([Vs[0], Vs[0]], [0, Vs[1]], color=GREEN, lw=1.1, ls=(0, (2, 2)), zorder=2)
    ax.plot([0, Vs[0]], [Vs[1], Vs[1]], color=PURPLE, lw=1.1, ls=(0, (2, 2)), zorder=2)
    ax.plot([0, Vs[0]], [0, 0], color=GREEN, lw=4.0,
            solid_capstyle="butt", zorder=3)
    ax.plot([0, 0], [0, Vs[1]], color=PURPLE, lw=4.0,
            solid_capstyle="butt", zorder=3)

    # V, V*
    ax.annotate("", xy=tuple(V), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=BLUE, lw=2.5,
                                shrinkA=0, shrinkB=0, mutation_scale=15))
    ax.annotate("", xy=tuple(Vs), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=2.6,
                                shrinkA=0, shrinkB=0, mutation_scale=16))
    ax.text(V[0] + 0.03, V[1] - 0.10, "V", fontsize=13.5, color=BLUE,
            ha="left", va="top")
    ax.text(Vs[0] + 0.05, Vs[1] - 0.02, "V′", fontsize=13.5, color=ORANGE)

    # 角度弧
    ax.add_patch(Arc((0, 0), 0.60, 0.60, theta1=0, theta2=phi, color=DARK, lw=1.2))
    ax.add_patch(Arc((0, 0), 0.70, 0.70, theta1=phi, theta2=phi + th,
                     color=ORANGE, lw=1.6))
    ax.text(0.37 * np.cos(6 * DEG), 0.37 * np.sin(6 * DEG), "φ", fontsize=12.5,
            color=DARK, ha="left", va="bottom")
    ax.text(0.43 * np.cos(38 * DEG), 0.43 * np.sin(38 * DEG), "θ", fontsize=13,
            color=ORANGE, ha="left", va="center")

    # 分量标注
    ax.text(0.25, -0.075, "cos(φ+θ)", fontsize=11, color=GREEN, ha="center",
            va="top")
    ax.text(-0.10, Vs[1] * 0.72, "sin(φ+θ)", fontsize=11, color=PURPLE,
            ha="right", va="center", rotation=90)

    # 图例
    fig.text(0.035, 0.030,
             "绿色 = V′ 的 x 分量；紫色 = V′ 的 y 分量；虚线圆 = 长度不变（半径 1）。",
             fontsize=9.6, color="#555", ha="left", va="center")

    # 右栏
    tx = fig.add_axes([0.545, 0.02, 0.445, 0.96])
    tx.axis("off")
    tx.set_xlim(0, 1)
    tx.set_ylim(0, 1)
    tx.text(0.0, 0.985, "① 先看二维：矩阵的两行 = 两个读数", fontsize=12.5,
            color=DARK, va="top", fontweight="bold")
    tx.text(0.0, 0.925,
            "长度不变的箭头 V 转了 θ 变成 V′，它与 x 轴夹角从 φ 变成 φ+θ。\n"
            "V′ 的两个分量就是：",
            fontsize=10.0, color="#444", va="top", linespacing=1.75)
    tx.text(0.02, 0.805, "V′x = cos(φ+θ)", fontsize=10.8, color=GREEN,
            family="Consolas")
    tx.text(0.02, 0.752, "V′y = sin(φ+θ)", fontsize=10.8, color=PURPLE,
            family="Consolas")
    tx.text(0.0, 0.685, "只用了一步：两角和公式", fontsize=10.0, color="#444",
            va="top")
    tx.text(0.02, 0.635,
            "cos(φ+θ) = cosφ·cosθ − sinφ·sinθ\n"
            "sin(φ+θ) = sinφ·cosθ + cosφ·sinθ",
            fontsize=10.2, color=DARK, family="Consolas", va="top", linespacing=1.9)
    tx.text(0.0, 0.470, "而 cosφ = Vx、sinφ = Vy，代回去：", fontsize=10.0,
            color="#444", va="top")
    tx.text(0.02, 0.420,
            "V′x = Vx·cosθ − Vy·sinθ\n"
            "V′y = Vx·sinθ + Vy·cosθ",
            fontsize=10.4, color=DARK, family="Consolas", va="top", linespacing=1.9)
    tx.text(0.02, 0.255,
            "R(θ) =  [  cosθ   −sinθ ]\n"
            "        [  sinθ    cosθ ]",
            fontsize=10.6, color=NAVY, family="Consolas", va="top", linespacing=1.7)
    tx.text(0.0, 0.100,
            "记法：第 1 行 = 新的 x 分量；第 2 行 = 新的 y 分量。",
            fontsize=9.9, color="#444", va="top")

    fig.savefig("图1_二维推导.png", dpi=200, facecolor="white")
    plt.close(fig)


# ============================ 图2：三维三连图 ============================
def fig_3d_overview():
    """把三根轴分别"摆成竖直"，机位固定 —— 三张图看起来才是同一套画法。

    Q 把世界坐标搬到作图坐标：第 3 行 = 旋转轴（画成竖直的 z），
    第 1、2 行 = 旋转平面里的两根轴（画成"向右"和"向后"）。
    """
    fig = plt.figure(figsize=(13.8, 5.4), dpi=200)
    v_mpl = unit([0.60, 0.34, 0.72])
    th = 60.0
    e_z = np.array([0.0, 0.0, 1.0])
    specs = [
        ("z", np.eye(3), ("x", "y"), "① 绕 Z 轴转 60°", "xy 平面里转，z 分量不动", 0.015),
        ("x", np.array([[0., 1., 0.], [0., 0., 1.], [1., 0., 0.]]),
         ("y", "z"), "② 绕 X 轴转 60°", "yz 平面里转，x 分量不动", 0.345),
        ("y", np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]]),
         ("z", "x"), "③ 绕 Y 轴转 60°", "zx 平面里转，y 分量不动", 0.675),
    ]
    for axis, Q, pair, title, sub, x0 in specs:
        ax = ax3d(fig, [x0, 0.10, 0.315, 0.80], elev=18, azim=-62, lim=1.15,
                  zoom=1.58)
        ax.set_zlim(-0.55, 1.70)

        v = v_mpl.copy()
        v2 = R_axis("z", th) @ v          # 作图坐标里永远是"绕竖直轴转"
        par = np.dot(v, e_z) * e_z

        # 三根坐标轴（作图坐标的 x/y/z，标签用真实轴名）
        axes3(ax, L=1.02, lw=1.0, color="#b8b8b8", labels=False)
        for d, nm, fs, vertical in ((np.array([1., 0, 0]), pair[0], 11.5, False),
                                    (np.array([0, 1., 0]), pair[1], 11.5, False),
                                    (np.array([0, 0, 1.]), axis, 12.5, True)):
            if vertical:
                continue
            p = d * 1.12
            ax.text(*p, nm, color=DARK, fontsize=fs, ha="center", va="center",
                    zorder=8)

        # 旋转轴 + 沿轴分量
        ax.plot([0, 0], [0, 0], [0, 1.16], color=PURPLE, lw=1.5, alpha=0.8,
                zorder=2)
        ax.plot(*np.array([[0, 0, 0], par]).T, color=PURPLE, lw=6.5, alpha=0.33,
                solid_capstyle="round", zorder=3)
        ax.quiver(0, 0, 1.06, 0, 0, 0.10, color=PURPLE, lw=1.5,
                  arrow_length_ratio=0.85, zorder=3)

        # 轨迹圆、扇形、转角弧
        arc3(ax, e_z, v, 0, 360, color="#d2d2d2", lw=0.9, dashed=True, z=1)
        sector3(ax, e_z, v, 0, th, color=ORANGE, alpha=0.09)
        arc3(ax, e_z, v, 0, th, color=ORANGE, lw=2.2)

        for p in (v, v2):
            ax.plot(*np.array([par, p]).T, color="#b5b5b5", lw=0.9,
                    ls=(0, (2, 3)), zorder=2)

        vec3(ax, v, BLUE, lw=3.2, head=0.085)
        vec3(ax, v2, ORANGE, lw=3.2, head=0.085)
        rad1 = (v - par) / np.linalg.norm(v - par)
        rad2 = (v2 - par) / np.linalg.norm(v2 - par)
        ax.text(*(v + 0.15 * rad1 - 0.05 * e_z), "v", color=BLUE,
                fontsize=13.5, zorder=9, ha="center", va="center")
        ax.text(*(v2 + 0.15 * rad2 + 0.04 * e_z), "v′", color=ORANGE,
                fontsize=13.5, zorder=9, ha="center", va="center")

        # θ 标在扇形里
        r = np.linalg.norm(v - par)
        mid = par + (v - par + v2 - par) / np.linalg.norm(
            (v - par) + (v2 - par)) * r * 0.52
        ax.text(*mid, "θ", color=ORANGE, fontsize=12.5, zorder=9,
                ha="center", va="center")

        ax.text2D(0.5, 1.03, title, transform=ax.transAxes, fontsize=13,
                  color=DARK, ha="center", va="top")
        ax.text2D(0.5, 0.965, sub, transform=ax.transAxes, fontsize=10.2,
                  color="#666", ha="center", va="top")

    fig.text(0.5, 0.082,
             "三张图画的是同一件事：沿轴的那一段（紫色粗线）完全不动，只有垂直轴的那一小段在垂直平面里转了 60°。"
             "顶点走出的圆，圆面垂直于旋转轴。",
             fontsize=11.0, color="#444", ha="center", va="center")
    fig.text(0.5, 0.045,
             "为了便于对照，三张图都把旋转轴摆成竖直（等于把相机跟着转了一下），所以同一个 v 在三张图里朝向不同。",
             fontsize=10.6, color="#555", ha="center", va="center")
    fig.text(0.5, 0.010,
             "紫线长度 = v 在轴上的投影；两条灰虚线等长 = 垂直分量长度不变。",
             fontsize=10.2, color="#777", ha="center", va="center")

    fig.savefig("图2_三轴总览.png", dpi=200, facecolor="white")
    plt.close(fig)


# ============================ 图3：沿轴俯视 ============================
def fig_topview():
    fig = plt.figure(figsize=(12.8, 4.7), dpi=200)
    panels = [
        ("z", "① 从 +Z 往下看：平面 (x, y)", "横轴 = x，竖轴 = y", 0.02),
        ("x", "② 从 +X 看：平面 (y, z)", "横轴 = y，竖轴 = z", 0.345),
        ("y", "③ 从 +Y 看：平面 (z, x)", "横轴 = z，竖轴 = x（相当于把图转 90°）", 0.670),
    ]
    th = 60.0
    for axis, title, note, x0 in panels:
        ax = fig.add_axes([x0, 0.15, 0.30, 0.72])
        ax.set_xlim(-1.30, 1.30)
        ax.set_ylim(-1.20, 1.28)
        ax.set_aspect("equal")
        ax.axis("off")

        t = np.linspace(0, 2 * np.pi, 400)
        ax.plot(0.92 * np.cos(t), 0.92 * np.sin(t), color="#dcdcdc", lw=1.1,
                ls=(0, (3, 4)), zorder=0)

        ax.annotate("", xy=(1.22, 0), xytext=(-0.10, 0),
                    arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.3,
                                    shrinkA=0, shrinkB=0))
        ax.annotate("", xy=(0, 1.20), xytext=(0, -0.10),
                    arrowprops=dict(arrowstyle="-|>", color=DARK, lw=1.3,
                                    shrinkA=0, shrinkB=0))
        hname, vname = {"z": ("x", "y"), "x": ("y", "z"), "y": ("z", "x")}[axis]
        ax.text(1.26, -0.10, hname, fontsize=13, color=DARK, ha="center")
        ax.text(-0.10, 1.24, vname, fontsize=13, color=DARK, ha="right")

        V = 0.92 * np.array([np.cos(20 * DEG), np.sin(20 * DEG)])
        Vs = 0.92 * np.array([np.cos((20 + th) * DEG), np.sin((20 + th) * DEG)])
        for vt, col, nm, off in ((V, BLUE, "v", (0.03, -0.13)),
                                 (Vs, ORANGE, "v′", (0.03, 0.06))):
            ax.annotate("", xy=tuple(vt), xytext=(0, 0),
                        arrowprops=dict(arrowstyle="-|>", color=col, lw=2.4,
                                        shrinkA=0, shrinkB=0, mutation_scale=15))
            ax.text(vt[0] + off[0], vt[1] + off[1], nm, fontsize=12.5, color=col)

        ax.add_patch(Arc((0, 0), 1.24, 1.24, theta1=20, theta2=20 + th,
                         color=ORANGE, lw=1.6))
        ae = (20 + th) * DEG
        tip = 0.62 * np.array([np.cos(ae), np.sin(ae)])
        ax.annotate("", xy=tuple(1.03 * tip), xytext=tuple(0.94 * tip),
                    arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=1.5,
                                    mutation_scale=11))
        am = (20 + th * 0.42) * DEG
        ax.text(0.72 * np.cos(am), 0.72 * np.sin(am), "θ", fontsize=12.5,
                color=ORANGE, ha="center", va="center")

        fig.text(x0 + 0.15, 0.955, title, fontsize=12.6, color=DARK, ha="center")
        fig.text(x0 + 0.15, 0.085, note, fontsize=9.8, color="#555",
                 ha="center", va="center")

    fig.text(0.5, 0.020,
             "三张图里正转都是逆时针 —— 这就是右手定则；也说明 2×2 小方块该嵌在哪个平面里：嵌在哪个平面，就是绕哪根轴转。",
             fontsize=10.6, color="#444", ha="center", va="bottom")
    fig.savefig("图3_沿轴俯视.png", dpi=200, facecolor="white")
    plt.close(fig)


# ============================ 图4：顺序不可交换 ============================
def fig_order():
    fig = plt.figure(figsize=(11.2, 4.7), dpi=200)
    A = R_axis("x", 90) @ R_axis("z", 90)
    B = R_axis("z", 90) @ R_axis("x", 90)
    cases = [
        (A, "① 先绕 Z 90°，再绕 X 90°", "R = Rx(90°) · Rz(90°)",
         "X′→ +z    Y′→ −x    Z′→ −y", 0.01),
        (B, "② 先绕 X 90°，再绕 Z 90°", "R = Rz(90°) · Rx(90°)",
         "X′→ +y    Y′→ +z    Z′→ +x", 0.51),
    ]
    for M, title, formula, land, x0 in cases:
        ax = ax3d(fig, [x0, 0.14, 0.48, 0.60], elev=20, azim=-52, lim=1.20,
                  zoom=1.55)
        # 参考系：灰色虚线 + 字母
        for i in range(3):
            d = np.eye(3)[i]
            ax.plot(*np.array([[0, 0, 0], d * 1.16]).T, color="#c9c9c9", lw=1.0,
                    ls=(0, (4, 3)), zorder=1)
            ax.text(*(d * 1.27), "xyz"[i], color="#9a9a9a", fontsize=11,
                    ha="center", va="center", zorder=8)
        # 转完的物体坐标系
        for i, col in enumerate((RED, GREEN, NAVY)):
            d = M[:, i]
            ax.quiver(0, 0, 0, *(d * 0.95), color=col, lw=3.0,
                      arrow_length_ratio=0.13, zorder=6)
        fig.text(x0 + 0.24, 0.955, title, fontsize=13, color=DARK, ha="center")
        fig.text(x0 + 0.24, 0.900, formula, fontsize=12, color=PURPLE,
                 ha="center", family="Consolas")
        fig.text(x0 + 0.24, 0.850, "红 = X′   绿 = Y′   蓝 = Z′", fontsize=10.2,
                 color="#666", ha="center")
        fig.text(x0 + 0.24, 0.115, land, fontsize=10.5, color="#555",
                 ha="center", family="Consolas")

    fig.text(0.5, 0.075,
             "同一个物体、同样两个 90°，只换了先后次序，最后的姿态就完全不同 —— 旋转矩阵的乘法不可交换。",
             fontsize=11.0, color="#444", ha="center", va="center")
    fig.text(0.5, 0.028,
             "灰色虚线 = 没动的参考系 x、y、z。转 90° 后彩色轴正好落在坐标轴上，这正是 90° 特殊值的用处。",
             fontsize=10.0, color="#777", ha="center", va="center")

    fig.savefig("图4_顺序不可交换.png", dpi=200, facecolor="white")
    plt.close(fig)


# ============================ 数值校验 ============================
def checks():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    lines = []
    p = lines.append
    p("=" * 74)
    p("三维旋转矩阵数值校验")
    p("=" * 74)
    for ax in "zxy":
        for d in (30.0, 90.0):
            M = R_axis(ax, d)
            p("")
            p(f"R{ax}({d:g}°) =")
            for row in M:
                p("   [ " + "  ".join(f"{x:+.6f}" for x in row) + " ]")
            p(f"   det = {np.linalg.det(M):+.9f}    "
              f"max|R^T R - I| = {np.abs(M.T @ M - np.eye(3)).max():.2e}")
    p("")
    p("-" * 74)
    p("对单位基矢量的作用（θ = 90°）：")
    for ax in "zxy":
        M = R_axis(ax, 90)
        for i, nm in enumerate("xyz"):
            r = M @ np.eye(3)[i]
            p(f"   R{ax}(90°) · e_{nm} = ({r[0]:+.0f}, {r[1]:+.0f}, {r[2]:+.0f})")
    p("")
    p("-" * 74)
    p("顺序不可交换（θ = 90°）：")
    A = R_axis("x", 90) @ R_axis("z", 90)
    B = R_axis("z", 90) @ R_axis("x", 90)
    for nm, M in (("Rx(90)·Rz(90)", A), ("Rz(90)·Rx(90)", B)):
        p(f"   {nm}")
        for row in M:
            p("      [ " + "  ".join(f"{x:+.0f}" for x in row) + " ]")
    p(f"   两者之差的最大元素 = {np.abs(A - B).max():.0f}")
    p("")
    p("-" * 74)
    p("R = Rz(γ)·Ry(β)·Rx(α) 与逐步作用等价（α=20°, β=35°, γ=50°）：")
    a3, b3, g3 = 20.0, 35.0, 50.0
    Rc = R_axis("z", g3) @ R_axis("y", b3) @ R_axis("x", a3)
    v = np.array([1.0, 0.0, 0.0])
    step = R_axis("z", g3) @ (R_axis("y", b3) @ (R_axis("x", a3) @ v))
    p(f"   R·v      = {np.array2string(Rc @ v, precision=6)}")
    p(f"   逐步作用 = {np.array2string(step, precision=6)}")
    p(f"   差       = {np.abs(Rc @ v - step).max():.2e}")
    p(f"   det(R)   = {np.linalg.det(Rc):.9f}")
    p("")
    p("小角度近似 max|R − (I + θ·[a]×)|，θ = 1e-4 rad：")
    th = 1e-4
    for ax, a3v in (("z", np.array([0, 0, 1.0])), ("x", np.array([1.0, 0, 0])),
                    ("y", np.array([0, 1.0, 0]))):
        K = np.array([[0, -a3v[2], a3v[1]],
                      [a3v[2], 0, -a3v[0]],
                      [-a3v[1], a3v[0], 0]])
        err = np.abs(R_axis(ax, th / DEG) - (np.eye(3) + th * K)).max()
        p(f"   {ax}: {err:.3e}")

    with open("_旋转矩阵校验.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    fig_2d()
    fig_3d_overview()
    fig_topview()
    fig_order()
    checks()
    print("\n图片已生成。")
