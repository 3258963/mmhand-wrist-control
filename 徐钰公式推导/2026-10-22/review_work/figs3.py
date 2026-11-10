"""v3 upgrade figures: cover art, methodology routes, error taxonomy, zero matrix, C2 geometry."""
import json, math, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, Circle, FancyBboxPatch, Arc

DATA = json.load(open("review_work/viz_data.json", encoding="utf-8"))
OUT = "review_work/figs2"
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "font.size": 8.2,
    "figure.facecolor": "white",
    "svg.fonttype": "path",
})

ACCENT = "#1F3A5F"
C1C, C2C, C3C = "#0072B2", "#E69F00", "#009E73"
RED = "#D55E00"
GRAY = "#9aa1ab"
INK = "#2a313b"

def save(fig, name):
    fig.savefig("%s/%s.svg" % (OUT, name), bbox_inches="tight", pad_inches=0.04,
                transparent=False)
    plt.close(fig)
    print("saved", name)

# ---------- cover art: minimal mechanism line drawing ----------
def fig_cover():
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    proj = lambda p: (p["x"] - 0.55 * p["z"], -0.62 * p["y"] + 0.30 * p["x"] + 0.45 * p["z"])
    extra = [{"x": 0, "y": -50, "z": 0}, {"x": 0, "y": 118, "z": 0},
             {"x": -70, "y": 0, "z": 24}, {"x": 80, "y": 0, "z": 24}]
    pts = DATA["pts24"] + extra
    P = [proj(p) for p in pts]
    xs = [q[0] for q in P]; ys = [q[1] for q in P]
    sx = lambda v: (v - min(xs)) / (max(xs) - min(xs)) * 100
    sy = lambda v: (v - min(ys)) / (max(ys) - min(ys)) * 34
    Q = lambda p: (sx(proj(p)[0]), sy(proj(p)[1]))
    def seg(a, b, color, lw=1.0, ls="-", z=2):
        pa, pb = Q(a), Q(b)
        ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=color, lw=lw, ls=ls, zorder=z,
                solid_capstyle="round")
    seg({"x": 0, "y": -50, "z": 0}, {"x": 0, "y": 118, "z": 0}, ACCENT, 1.3)
    seg({"x": -70, "y": 0, "z": 24}, {"x": 80, "y": 0, "z": 24}, ACCENT, 1.3)
    seg({"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 24}, RED, 1.2, (0, (4, 3)))
    for ci in (1, 2, 3):
        chain = sorted([p for p in DATA["pts24"] if p["cable"] == ci],
                       key=lambda p: int(p["id"].split("P")[1]))
        poly = [Q(p) for p in chain]
        ax.plot([q[0] for q in poly], [q[1] for q in poly], color=[C1C, C2C, C3C][ci - 1],
                lw=1.6 if ci == 2 else 0.9, zorder=3, alpha=0.95, solid_capstyle="round")
        ax.plot([q[0] for q in poly], [q[1] for q in poly], "o",
                color=[C1C, C2C, C3C][ci - 1], ms=3 if ci == 2 else 1.8, zorder=4)
    q = Q({"x": 0, "y": 118, "z": 0})
    ax.annotate("roll", q, xytext=(2, 0), textcoords="offset points", fontsize=7,
                color=ACCENT, style="italic")
    q = Q({"x": 80, "y": 0, "z": 24})
    ax.annotate("pitch", q, xytext=(-16, -3), textcoords="offset points", fontsize=7,
                color=ACCENT, style="italic")
    q = Q({"x": 0, "y": 0, "z": 24})
    ax.annotate("24 mm", q, xytext=(3, 2), textcoords="offset points", fontsize=6.5,
                color=RED)
    ax.set_xlim(-4, 104); ax.set_ylim(-4, 38)
    ax.axis("off")
    save(fig, "cover")

# ---------- methodology: four routes converge ----------
def fig_routes():
    fig, ax = plt.subplots(figsize=(7.0, 2.3))
    ax.set_xlim(0, 100); ax.set_ylim(0, 34); ax.axis("off")
    def box(x, y, w, h, text, fc, ec, tc, fs=7.6, lw=1.0):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.4",
                                    fc=fc, ec=ec, lw=lw, zorder=3))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
                color=tc, zorder=4, linespacing=1.5)
    def arrow(p1, p2, color=GRAY, lw=1.1):
        ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=11,
                                     color=color, lw=lw, zorder=2,
                                     connectionstyle="arc3,rad=0"))
    srcs = [("闭式 α/β/γ\nr=(βsinθ−γcosθ)/2√D", 4),
            ("嵌套中心差分\nh=$10^{-6}$ rad", 28.5),
            ("0.2° 模板重放\n三点 Lagrange", 53),
            ("静力学取矩\nτ=a·[(P−o)×(−fu)]", 77.5)]
    for t, x in srcs:
        box(x, 22, 18.5, 9, t, "white", "#B9C4D2", INK)
        arrow((x + 9.25, 22), (50, 15.5))
    box(30, 6, 40, 8, "3,621 姿态全网格交叉一致（残差见 §5）", "#EEF2F7", ACCENT, ACCENT, 8.2, 1.2)
    box(76, 6, 20, 8, "结论：\n理想模型内成立", "#EDF5F0", "#2E7D4F", "#2E7D4F", 7.8, 1.2)
    arrow((70, 10), (76, 10), "#2E7D4F")
    save(fig, "routes")

# ---------- error taxonomy ----------
def fig_errtax():
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    ax.set_xlim(0, 100); ax.set_ylim(0, 40); ax.axis("off")
    rows = [
        ("数值差分误差", "0.2° 模板截断：中心 h²/6、单侧 h²/3", "实测口径 0.032668 mm @ (4°,−25°)", "已解释·非模型误差", "#EEF2F7", ACCENT),
        ("标定参数误差", "δ 相位耦合；P06 梯度 15.7 mm/mm @ −25°", "0.05 mm 点位误差 → ≈1.52 mm 力臂误差", "待实测", "#FFF8EC", "#B8860B"),
        ("模型–实物误差", "瓷环滑动接触、摩擦、弹性、回差", "未建模，实机精度上限由其决定", "未建模·不承诺", "#FBF0EE", RED),
    ]
    y = 28
    for name, cause, scale, status, fc, ec in rows:
        ax.add_patch(FancyBboxPatch((2, y - 4), 96, 9.6, boxstyle="round,pad=0.5,rounding_size=1.2",
                                    fc=fc, ec=ec, lw=1.0, zorder=2))
        ax.text(4, y + 0.8, name, fontsize=8.4, color=ec, fontweight="bold", va="center", zorder=3)
        ax.text(22, y + 0.8, cause, fontsize=7.4, color=INK, va="center", zorder=3)
        ax.text(58, y + 0.8, scale, fontsize=7.2, color=INK, va="center", zorder=3)
        ax.text(91, y + 0.8, status, fontsize=7.2, color=ec, va="center", ha="center",
                fontweight="bold", zorder=3)
        y -= 12.4
    ax.annotate("", xy=(0.8, 30), xytext=(0.8, 4),
                arrowprops=dict(arrowstyle="-|>", color=GRAY, lw=1.2))
    ax.text(-0.5, 17, "由内到外：误差来源分层", rotation=90, fontsize=7, color=GRAY,
            ha="center", va="center")
    save(fig, "errtax")

# ---------- zero-pose matrix heatmap ----------
def fig_zmatrix():
    import matplotlib.colors as mcolors
    ana = np.array([[-0.25943726, -22.04970101, 17.37198247],
                    [-58.10461556, 11.80488412, 10.99035112]])
    cad = np.array([[-0.25943594, -22.04935585, 17.37166016],
                    [-58.10454990, 11.80482013, 10.99029230]])
    fig, ax = plt.subplots(figsize=(5.6, 2.5))
    norm = mcolors.TwoSlopeNorm(vmin=-60, vcenter=0, vmax=60)
    cmap = mcolors.LinearSegmentedColormap.from_list("cc", ["#C44E52", "#FFFFFF", "#DD8452"])
    ax.imshow(ana, cmap=cmap, norm=norm, aspect="auto")
    for i in range(2):
        for j in range(3):
            ax.text(j, i - 0.13, "%.5f" % ana[i, j], ha="center", va="center",
                    fontsize=7.6, color=INK)
            ax.text(j, i + 0.22, "CAD %.5f" % cad[i, j], ha="center", va="center",
                    fontsize=6.0, color="#6b7480")
    ax.set_xticks(range(3), ["C1", "C2", "C3"], fontsize=8)
    ax.set_yticks(range(2), ["roll 行", "pitch 行"], fontsize=8)
    ax.set_xticks(np.arange(-0.5, 3, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 2, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    save(fig, "zmatrix")

# ---------- C2 roll segment geometry ----------
def fig_c2geom():
    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    O = np.array([0.0, 0.0])
    A = np.array([-27.0, 5.0])
    B = np.array([-32.5, 18.0])
    ax.add_patch(Circle(O, np.linalg.norm(B), fill=False, ls=(0, (4, 3)),
                        lw=0.9, color=GRAY, zorder=1))
    ax.plot(*O, "o", ms=5, color=ACCENT, zorder=5)
    ax.plot([0], [0], "x", ms=0.1)  # placeholder
    ax.annotate("", xy=(0.55, 0), xytext=(-0.55, 0),
                arrowprops=dict(arrowstyle="-", color="none"))
    ax.plot([0, 3.2], [0, 3.2], lw=0.1, color="none")
    for xy, lab, dx, dy in ((O, "o（轴上点，轴 a⊥纸面）", 2, -4.5),
                            (A, "A = P04（固定端）", -4, -8),
                            (B, "$B_0$ = P05（零位）", 3, 2)):
        ax.plot(*xy, "o", ms=4.5, color=INK, zorder=5)
        ax.annotate(lab, xy, xytext=(dx, dy), textcoords="offset points",
                    fontsize=7.2, color=INK)
    for p, q, color, lab, off in ((O, A, C1C, "u = A − o", (-16, 2)),
                                  (O, B, C3C, "v = $B_0$ − o", (4, 12)),
                                  (A, B, RED, "s(θ) = ‖B(θ) − A‖", (-30, 14))):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=10,
                                     color=color, lw=1.4, zorder=4))
        ax.annotate(lab, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), xytext=off,
                    textcoords="offset points", fontsize=7.2, color=color)
    th = np.linspace(np.arctan2(B[1], B[0]) , np.arctan2(B[1], B[0]) + 0.6, 30)
    ax.plot(np.linalg.norm(B) * np.cos(th), np.linalg.norm(B) * np.sin(th),
            color=C2C, lw=1.8, zorder=3)
    ax.annotate("θ", (np.linalg.norm(B) * np.cos(th[-1]), np.linalg.norm(B) * np.sin(th[-1])),
                xytext=(6, 2), textcoords="offset points", fontsize=8, color=C2C,
                fontweight="bold")
    Bt = np.array([np.linalg.norm(B) * np.cos(th[-1]), np.linalg.norm(B) * np.sin(th[-1])])
    ax.plot(*Bt, "o", ms=3.5, color=C2C, zorder=5)
    ax.annotate("B(θ)", Bt, xytext=(6, -3), textcoords="offset points",
                fontsize=7.2, color=C2C)
    ax.set_xlim(-42, 14); ax.set_ylim(-9, 42)
    ax.set_aspect("equal")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#B9C4D2")
    ax.set_xticks([]); ax.set_yticks([])
    save(fig, "c2geom")

if __name__ == "__main__":
    fig_cover(); fig_routes(); fig_errtax(); fig_zmatrix(); fig_c2geom()
    print("figs3 done")
