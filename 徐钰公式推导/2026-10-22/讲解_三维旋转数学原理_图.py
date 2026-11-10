# -*- coding: utf-8 -*-
"""三维旋转「数学原理」配图。

图5_为什么是正交矩阵.png   保长保角 + 列向量是标准正交基
图6_无穷小旋转.png         角速度、叉乘、反对称矩阵（生成元）
图7_旋转向量球.png         轴角表示 = 球；θ=π 处对径粘合
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

BLUE, ORANGE, PURPLE = "#1f6fd0", "#e07b1a", "#7d3c98"
GREEN, RED, NAVY = "#2e8b57", "#c0392b", "#2471a3"
DARK, GRAY = "#333333", "#9a9a9a"
DEG = np.pi / 180

BOX = dict(fc="white", ec="none", alpha=0.82, pad=1.6)


def Rz(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def Ry(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def Rx(t):
    c, s = np.cos(t), np.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def ax3d(fig, rect, elev=20, azim=-58, lim=1.3, zoom=1.25):
    ax = fig.add_axes(rect, projection="3d")
    ax.set_proj_type("ortho")
    ax.set_box_aspect((1, 1, 1), zoom=zoom)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_zlim(-lim, lim)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    return ax


# ==================== 图5：为什么是正交矩阵 ====================
def fig_orthogonal():
    fig = plt.figure(figsize=(13.2, 5.1), dpi=200)

    # ---- 左：同一个三角形，只是转了一下 ----
    ax = fig.add_axes([0.02, 0.04, 0.44, 0.82])
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(-2.45, 2.45)
    ax.set_ylim(-0.60, 1.55)

    tri = np.array([[0.0, 0.0], [1.32, 0.14], [0.60, 1.02]])
    A = tri + np.array([-1.82, 0.06])

    th = 40 * DEG
    R2 = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    c0 = tri.mean(axis=0)
    B = (tri - c0) @ R2.T + c0 + np.array([0.58, -0.10])

    def draw_tri(T, color, lw, ls, fill=None):
        if fill:
            ax.fill(T[:, 0], T[:, 1], color=fill, alpha=0.10, zorder=1)
        ax.plot(*np.vstack([T, T[:1]]).T, color=color, lw=lw, ls=ls, zorder=3)
        for p in T:
            ax.plot(*p, "o", ms=4.5, color=color, zorder=4)

    draw_tri(A, "#a8a8a8", 1.7, (0, (6, 4)))
    draw_tri(B, ORANGE, 2.4, "-", fill=ORANGE)

    # 每边一个"等长"小横杠（两份一模一样）
    def ticks(T, color, lw):
        for i in range(3):
            p, q = T[i], T[(i + 1) % 3]
            m = (p + q) / 2
            d = q - p
            n = np.array([-d[1], d[0]])
            n = n / np.linalg.norm(n) * 0.075
            ax.plot([m[0] - n[0], m[0] + n[0]], [m[1] - n[1], m[1] + n[1]],
                    color=color, lw=lw, zorder=5, solid_capstyle="round")
    ticks(A, "#a8a8a8", 1.4)
    ticks(B, ORANGE, 1.7)

    # 顶点的夹角弧（两份一样大）
    def angle_arc(T, idx, color, lw):
        v, p, q = T[idx], T[(idx + 1) % 3], T[(idx + 2) % 3]
        a1 = np.arctan2(p[1] - v[1], p[0] - v[0])
        a2 = np.arctan2(q[1] - v[1], q[0] - v[0])
        d = (a2 - a1) % (2 * np.pi)
        if d <= np.pi:
            t1, t2 = a1, a1 + d
        else:
            t1, t2 = a2, a2 + (2 * np.pi - d)
        ax.add_patch(Arc(v, 0.50, 0.50, theta1=np.degrees(t1),
                         theta2=np.degrees(t2), color=color, lw=lw, zorder=5))
    angle_arc(A, 2, "#8a8a8a", 1.2)
    angle_arc(B, 2, "#b45309", 1.5)

    # 中间"转了一下"的箭头
    ax.annotate("", xy=(0.34, 0.46), xytext=(-0.80, 0.56),
                arrowprops=dict(arrowstyle="-|>", color=PURPLE, lw=1.8,
                                connectionstyle="arc3,rad=0.40",
                                mutation_scale=14))
    ax.text(-0.22, 0.92, "转 40°", fontsize=10.5, color=PURPLE, ha="center")

    ax.text(-2.42, 1.52, "同一个三角形，只是转了一下：三条边一样长、三个角一样大",
            fontsize=11.3, color=DARK, ha="left", va="top")
    ax.text(-2.42, -0.48,
            "灰虚线 = 转之前    橙色 = 转之后    每边的小横杠 = 等长记号",
            fontsize=9.6, color="#777", ha="left", va="center")

    # ---- 右：三列是标准正交基 ----
    axB = ax3d(fig, [0.47, 0.02, 0.52, 0.90], elev=20, azim=-52, lim=1.18,
               zoom=1.18)
    M = Ry(22) @ Rx(34)
    cols = [M[:, i] for i in range(3)]
    names = ["r1", "r2", "r3"]
    colors = [RED, GREEN, NAVY]

    for i in range(3):
        e = np.eye(3)[i]
        axB.plot(*np.array([[0, 0, 0], e * 1.16]).T, color="#d0d0d0", lw=1.0,
                 ls=(0, (3, 3)), zorder=1)
        axB.text(*(e * 1.28), "e" + str(i + 1), color="#999", fontsize=11,
                 ha="center", va="center")
    for c, col, nm in zip(cols, colors, names):
        axB.quiver(0, 0, 0, *c, color=col, lw=3.2, arrow_length_ratio=0.12,
                   zorder=6)
        axB.text(*(c * 1.17), nm, color=col, fontsize=13, ha="center",
                 va="center", zorder=9)

    axB.text2D(0.5, 1.00, "R 的三列 = 三根轴转完之后的位置",
               transform=axB.transAxes, fontsize=11.5, color=DARK,
               ha="center", va="top")
    axB.text2D(0.5, 0.935, "两两垂直、长度都是 1；灰色虚线是原来的 e1、e2、e3",
               transform=axB.transAxes, fontsize=10.2, color="#666",
               ha="center", va="top")

    fig.text(0.5, 0.028,
             "R^T·R = I 翻译成人话：三列是标准正交基 → 变换前后长度、夹角都不变；"
             "det R = ±1，取 +1 才是旋转（−1 是镜像）。",
             fontsize=10.8, color="#444", ha="center", va="center")

    fig.savefig("图5_为什么是正交矩阵.png", dpi=200, facecolor="white")
    plt.close(fig)


# ==================== 图6：无穷小旋转 ====================
def fig_infinitesimal():
    fig = plt.figure(figsize=(13.2, 5.2), dpi=200)
    ax = ax3d(fig, [0.01, 0.03, 0.47, 0.86], elev=16, azim=-62, lim=1.42,
              zoom=1.18)

    w = np.array([0.0, 0.0, 1.0])
    r = np.array([0.95, 0.42, 0.55])
    v = np.cross(w, r)
    v = v / np.linalg.norm(v) * 0.85

    ax.plot([0, 0], [0, 0], [0, 1.25], color=PURPLE, lw=2.2, zorder=3)
    ax.quiver(0, 0, 1.12, 0, 0, 0.13, color=PURPLE, lw=2.2,
              arrow_length_ratio=0.9, zorder=3)
    ax.text(-0.10, 0, 1.10, "ω（角速度）", color=PURPLE, fontsize=12,
            ha="right", va="center", zorder=9, bbox=BOX)

    par = np.dot(r, w) * w
    rad = r - par
    e1 = rad / np.linalg.norm(rad)
    e2 = np.cross(w, e1)
    tt = np.linspace(0, 2 * np.pi, 160)
    circ = par + np.linalg.norm(rad) * (np.cos(tt)[:, None] * e1
                                        + np.sin(tt)[:, None] * e2)
    ax.plot(*circ.T, color="#d5d5d5", lw=1.0, ls=(0, (4, 4)), zorder=1)

    ax.quiver(0, 0, 0, *r, color=BLUE, lw=3.0, arrow_length_ratio=0.10, zorder=6)
    ax.text(*(r * 1.10), "r", color=BLUE, fontsize=13, zorder=9, ha="center")
    tip = r + v
    ax.quiver(*r, *v, color=ORANGE, lw=3.0, arrow_length_ratio=0.12, zorder=6)
    ax.text(*(tip + np.array([0.0, 0.0, 0.12])), "v = ω × r", color=ORANGE,
            fontsize=12, zorder=9, ha="center", bbox=BOX)
    ax.plot(*np.array([par, r]).T, color="#b5b5b5", lw=0.9, ls=(0, (2, 3)),
            zorder=2)
    ax.plot([0, 0], [0, 0], [0, par[2]], color="#b5b5b5", lw=0.9, ls=(0, (2, 3)),
            zorder=2)

    ax.text2D(0.5, 0.99, "① 角速度就是「转得多快 + 绕哪根轴」",
              transform=ax.transAxes, fontsize=11.8, color=DARK, ha="center",
              va="top")
    ax.text2D(0.5, 0.905, "v ⊥ r，v ⊥ ω；|v| = ω·|r|·sin∠(ω,r)",
              transform=ax.transAxes, fontsize=10.5, color="#666", ha="center",
              va="top")

    # ---- 右：推导 ----
    tx = fig.add_axes([0.50, 0.02, 0.49, 0.96])
    tx.axis("off")
    tx.set_xlim(0, 1); tx.set_ylim(0, 1)

    tx.text(0.0, 0.995, "② 为什么一定会冒出「反对称矩阵」", fontsize=12.5,
            color=DARK, va="top", fontweight="bold")
    tx.text(0.0, 0.925, "把 R^T·R = I 对时间求导（旋转是连续发生的）：",
            fontsize=10.2, color="#444", va="top")
    tx.text(0.03, 0.868, "(dR/dt)^T·R + R^T·(dR/dt) = 0", fontsize=11.2,
            color=NAVY, family="Consolas", va="top")
    tx.text(0.0, 0.800, "令 Ω = (dR/dt)·R^T，可得 Ω^T = −Ω —— 它必须反对称。",
            fontsize=10.2, color="#444", va="top")
    tx.text(0.0, 0.735, "反对称矩阵只有 3 个独立数，正好装一个三维向量 ω：",
            fontsize=10.2, color="#444", va="top")
    tx.text(0.03, 0.675,
            "Ω = [ω]× = [   0    −ωz   ωy ]\n"
            "           [  ωz      0   −ωx ]\n"
            "           [ −ωy    ωx     0  ]",
            fontsize=10.4, color=DARK, family="Consolas", va="top", linespacing=1.9)
    tx.text(0.0, 0.505, "于是旋转的「瞬时版本」就是一个叉乘：",
            fontsize=10.2, color="#444", va="top")
    tx.text(0.03, 0.448, "dR/dt = [ω]× R      v = ω × r", fontsize=11.2,
            color=ORANGE, family="Consolas", va="top")
    tx.text(0.0, 0.370, "三个「基本生成元」（ω 分别取 x、y、z 单位向量）：",
            fontsize=10.2, color="#444", va="top")
    tx.text(0.03, 0.312,
            "    [  0  0  0 ]        [  0  0  1 ]        [  0 −1  0 ]\n"
            "Kx= [  0  0 −1 ]   Ky=  [  0  0  0 ]   Kz=  [  1  0  0 ]\n"
            "    [  0  1  0 ]        [ −1  0  0 ]        [  0  0  0 ]",
            fontsize=9.6, color=DARK, family="Consolas", va="top", linespacing=1.7)
    tx.text(0.0, 0.130,
            "注：这里的 ω 是「世界系」角速度；若换成随体角速度，\n"
            "    公式变成 dR/dt = R·[ω_body]×，两者差一个共轭。",
            fontsize=9.6, color="#666", va="top", linespacing=1.8)

    fig.savefig("图6_无穷小旋转.png", dpi=200, facecolor="white")
    plt.close(fig)


# ==================== 图7：旋转向量球 ====================
def fig_ball():
    fig = plt.figure(figsize=(11.6, 5.4), dpi=200)
    ax = ax3d(fig, [0.02, 0.02, 0.64, 0.94], elev=18, azim=-52, lim=3.9,
              zoom=0.98)

    R = np.pi
    for a in np.linspace(0, 2 * np.pi, 9)[:-1]:
        t = np.linspace(-np.pi / 2, np.pi / 2, 60)
        ax.plot(R * np.cos(t) * np.cos(a), R * np.cos(t) * np.sin(a),
                R * np.sin(t), color="#d8d8d8", lw=0.55, alpha=0.7, zorder=1)
    for el in (-60, -30, 0, 30, 60):
        t = np.linspace(0, 2 * np.pi, 80)
        rr = R * np.cos(el * DEG)
        ax.plot(rr * np.cos(t), rr * np.sin(t),
                np.full_like(t, R * np.sin(el * DEG)), color="#d8d8d8", lw=0.55,
                alpha=0.7, zorder=1)

    for i, nm in enumerate("xyz"):
        d = np.eye(3)[i] * R * 1.30
        ax.plot(*np.array([[0, 0, 0], d]).T, color="#e8e8e8", lw=0.8,
                ls=(0, (3, 3)), zorder=1)
        ax.text(*(d * 1.06), nm, color="#b0b0b0", fontsize=11, ha="center")

    # 球心
    ax.plot(0, 0, 0, "o", ms=5, color=DARK, zorder=8)
    ax.text(0, -0.15, -1.55, "θ = 0（不转）", fontsize=10, color=DARK,
            ha="center", va="top", zorder=9, bbox=BOX)

    # 代表点：绕 z 转 90°
    pz = np.array([0, 0, 1.0]) * np.pi / 2
    ax.quiver(0, 0, 0, *pz, color=PURPLE, lw=2.2, arrow_length_ratio=0.09,
              zorder=6)
    ax.text(-0.30, 0, pz[2] * 1.05, "绕 z 转 90°", color=PURPLE, fontsize=10.5,
            ha="right", va="center", zorder=9, bbox=BOX)

    # 对径两点：±y 转 180°
    py = np.array([0, 1.0, 0]) * np.pi
    for s in (1, -1):
        ax.quiver(0, 0, 0, *(s * py), color=ORANGE, lw=2.2,
                  arrow_length_ratio=0.07, zorder=6)
    ax.plot(*np.array([-py, py]).T, color=ORANGE, lw=1.2, ls=(0, (4, 3)),
            zorder=5, alpha=0.7)
    for s in (1, -1):
        ax.plot(*(s * py), "o", ms=5, mfc="white", mec=ORANGE, mew=1.6,
                zorder=7)
    ax.text(0, 2.45, 1.55, "绕 ±y 转 180°：\n对径两点 = 同一个旋转",
            color=ORANGE, fontsize=10, ha="center", va="bottom", zorder=9,
            bbox=BOX)

    ax.text2D(0.5, 0.99,
              "每个点 = 一个旋转：方向 = 转轴，到球心的距离 = 转角",
              transform=ax.transAxes, fontsize=12, color=DARK, ha="center",
              va="top")
    ax.text2D(0.5, 0.925,
              "半径取 π（180°）就够描述所有旋转；球面是对径粘合的",
              transform=ax.transAxes, fontsize=10.2, color="#666", ha="center",
              va="top")

    # ---- 右栏 ----
    tx = fig.add_axes([0.655, 0.05, 0.34, 0.86])
    tx.axis("off")
    tx.set_xlim(0, 1); tx.set_ylim(0, 1)
    tx.text(0.0, 1.0, "这张「球」是什么", fontsize=12, color=DARK, va="top",
            fontweight="bold")
    tx.text(0.0, 0.925,
            "任给一个旋转，都能拆成「绕某根单位轴 â 转 θ」。\n"
            "把 θ·â 当成一个三维向量画出来，终点就是球里的一点。",
            fontsize=9.6, color="#444", va="top", linespacing=1.9)
    tx.text(0.0, 0.775,
            "· 球心 = 不转（R = I）\n"
            "· 沿同一根轴越远 = 转得越多\n"
            "· 半径 π 以外不用画：转 190° = 反着转 170°",
            fontsize=9.6, color="#444", va="top", linespacing=1.95)
    tx.text(0.0, 0.575,
            "为什么「转 180° 正反一样」：\n"
            "R(â, π) = R(−â, π)，球面上两个对径点代表同一个\n"
            "姿态。所以 SO(3) = 这个球把表面对径粘起来（RP³）。",
            fontsize=9.6, color="#444", va="top", linespacing=1.85)
    tx.text(0.0, 0.345,
            "这也解释了欧拉角为什么一定有奇异：SO(3) 是「紧」的\n"
            "（有界的球），三个角度只能在 R³ 的一小块里当坐标，\n"
            "不可能用一张坐标卡盖满整个球。",
            fontsize=9.6, color="#444", va="top", linespacing=1.85)
    tx.text(0.0, 0.135,
            "四元数则是 S³：S³ → SO(3) 是 2 对 1 的覆盖\n"
            "（q 与 −q 表示同一个旋转）。",
            fontsize=9.6, color="#666", va="top", linespacing=1.85)

    fig.savefig("图7_旋转向量球.png", dpi=200, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    fig_orthogonal()
    fig_infinitesimal()
    fig_ball()
    print("三张图已生成")
