"""Redesigned figures with matplotlib (Okabe-Ito palette, YaHei, SVG text-as-path).
Output: review_work/figs2/*.svg for Typst embedding."""
import json, math, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

DATA = json.load(open("review_work/viz_data.json", encoding="utf-8"))
OUT = "review_work/figs2"
os.makedirs(OUT, exist_ok=True)

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "font.size": 8.2,
    "axes.linewidth": 0.7,
    "axes.edgecolor": "#5b6470",
    "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "xtick.major.width": 0.7, "ytick.major.width": 0.7,
    "xtick.color": "#5b6470", "ytick.color": "#5b6470",
    "axes.labelcolor": "#333a44",
    "text.color": "#333a44",
    "figure.facecolor": "white",
    "svg.fonttype": "path",
})

ACCENT = "#1F3A5F"
C1C, C2C, C3C = "#0072B2", "#E69F00", "#009E73"
RED = "#D55E00"
GRAY = "#9aa1ab"
INK = "#2a313b"
CC = [C1C, C2C, C3C]

deg = lambda x: x * math.pi / 180
def abc_of(c, s):
    return next(a for a in DATA["abc"] if a["cable"] == c and a["seg"] == s)
def s_of(a, d):
    return math.sqrt(a["A"] + a["B"] * math.cos(deg(d)) + a["C"] * math.sin(deg(d)))
def r_of(a, d):
    t = deg(d)
    return (a["B"] * math.sin(t) - a["C"] * math.cos(t)) / (2 * s_of(a, d))

def style(ax, xlab="", ylab="", grid_axis="y"):
    ax.spines[["top", "right"]].set_visible(False)
    if grid_axis:
        ax.grid(axis=grid_axis, color="#e3e6ea", linewidth=0.6, zorder=0)
    ax.set_xlabel(xlab, fontsize=8.2, labelpad=3)
    ax.set_ylabel(ylab, fontsize=8.2, labelpad=3)
    ax.tick_params(labelsize=7.6)

D = FuncFormatter(lambda v, _: ("%g°" % round(v, 6)))

def save(fig, name):
    fig.savefig("%s/%s.svg" % (OUT, name), bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("saved", name)

# ---------- 1 schema ----------
def fig_schema():
    fig, ax = plt.subplots(figsize=(6.9, 4.0))
    proj = lambda p: (p["x"] - 0.55 * p["z"], -0.82 * p["y"] + 0.30 * p["x"] + 0.45 * p["z"])
    extra = [{"x": 0, "y": -50, "z": 0}, {"x": 0, "y": 116, "z": 0},
             {"x": -68, "y": 0, "z": 24}, {"x": 78, "y": 0, "z": 24}]
    pts = DATA["pts24"] + extra
    P = [proj(p) for p in pts]
    xs = [q[0] for q in P]; ys = [q[1] for q in P]
    sx = lambda v: 90 + (v - min(xs)) / (max(xs) - min(xs)) * 620
    sy = lambda v: 350 - (v - min(ys)) / (max(ys) - min(ys)) * 320
    Q = lambda p: (sx(proj(p)[0]), sy(proj(p)[1]))
    def seg(a, b, color, lw=1.1, ls="-", z=2):
        pa, pb = Q(a), Q(b)
        ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=color, lw=lw, ls=ls, zorder=z,
                solid_capstyle="round")
    seg({"x": 0, "y": -50, "z": 0}, {"x": 0, "y": 116, "z": 0}, INK, 1.2)
    seg({"x": -68, "y": 0, "z": 24}, {"x": 78, "y": 0, "z": 24}, INK, 1.2)
    seg({"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 24}, RED, 1.3, (0, (5, 3)))
    for ci in (1, 2, 3):
        chain = sorted([p for p in DATA["pts24"] if p["cable"] == ci],
                       key=lambda p: int(p["id"].split("P")[1]))
        poly = [Q(p) for p in chain]
        ax.plot([q[0] for q in poly], [q[1] for q in poly], color=CC[ci - 1],
                lw=1.7 if ci == 2 else 1.0, zorder=3, solid_capstyle="round")
        ax.plot([q[0] for q in poly], [q[1] for q in poly], "o", color=CC[ci - 1],
                ms=3.4 if ci == 2 else 2.2, zorder=4)
    for idx in (4, 5, 6, 7):
        p = next(q for q in DATA["pts24"] if q["id"] == "C2-P0%d" % idx)
        q = Q(p)
        ax.annotate("P%d" % idx, q, textcoords="offset points", xytext=(0, -9),
                    ha="center", fontsize=6.8, color=INK)
    q = Q(next(p for p in DATA["pts24"] if p["id"] == "C2-P05"))
    ax.annotate("P4–P5 跨 roll", q, textcoords="offset points", xytext=(7, 2),
                fontsize=7.4, color=C2C, fontweight="bold")
    q = Q(next(p for p in DATA["pts24"] if p["id"] == "C2-P07"))
    ax.annotate("P6–P7 跨 pitch", q, textcoords="offset points", xytext=(7, 2),
                fontsize=7.4, color=C2C, fontweight="bold")
    q = Q({"x": 0, "y": 116, "z": 0})
    ax.annotate("roll 轴 a=(0,1,0)", q, textcoords="offset points", xytext=(4, -2),
                fontsize=7.6, color=INK)
    q = Q({"x": 78, "y": 0, "z": 24})
    ax.annotate("pitch 轴 a=(1,0,0)，过 (0,0,24)", q, textcoords="offset points",
                xytext=(-4, -12), ha="right", fontsize=7.6, color=INK)
    q = Q({"x": 0, "y": 0, "z": 24})
    ax.annotate("24 mm 偏置", q, textcoords="offset points", xytext=(6, 2),
                fontsize=7.6, color=RED)
    for ci, lb in ((1, "绳 C1"), (2, "绳 C2"), (3, "绳 C3")):
        ax.plot([], [], color=CC[ci - 1], lw=2, label=lb)
    ax.plot([], [], color=INK, lw=1.4, label="关节轴")
    ax.plot([], [], color=RED, lw=1.4, ls=(0, (5, 3)), label="两轴公垂线")
    ax.legend(frameon=False, fontsize=7.2, loc="lower left", ncol=2,
              handlelength=1.6, columnspacing=1.0, borderaxespad=0.2)
    ax.set_xlim(60, 760); ax.set_ylim(0, 380)
    ax.axis("off")
    save(fig, "schema")

# ---------- 2 grid residual ----------
def fig_grid():
    cats = ["roll/C1", "roll/C2", "roll/C3", "pitch/C1", "pitch/C2", "pitch/C3"]
    fig, ax = plt.subplots(figsize=(6.7, 2.7))
    xpos = np.arange(len(cats))
    cols = [RED if c == "pitch/C1" else C1C for c in cats]
    ax.bar(xpos, DATA["myMax"], width=0.52, color=cols, alpha=0.88, zorder=3,
           label="独立复现最大差")
    ax.scatter(xpos, DATA["docMax"], marker="_", s=170, color=INK, linewidths=1.6,
               zorder=4, label="文档声称值")
    ax.set_yscale("log")
    for x, v in zip(xpos, DATA["myMax"]):
        ax.annotate("%.2e" % v, (x, v), textcoords="offset points", xytext=(0, 5),
                    ha="center", fontsize=6.6, color=INK)
    ax.set_xticks(xpos, cats, fontsize=7.4)
    style(ax, "", "最大差 |ΔR|（mm）")
    ax.set_ylim(5e-6, 2e-1)
    ax.legend(frameon=False, fontsize=7.2, loc="upper right", borderaxespad=0.2)
    save(fig, "grid")

# ---------- 3 stencil ----------
def fig_stencil():
    st = DATA["stencil"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.7, 4.4), sharex=True,
                                 height_ratios=[1.25, 1], constrained_layout=True)
    a1.plot(st["ang"], st["rana"], color=C1C, lw=1.7, label="解析导数 r(θ)")
    a1.plot(st["ang"], st["rst"], color=C3C, lw=1.3, ls=(0, (5, 3)),
            label="0.2° 三点差分（同一解析长度）")
    style(a1, "", "C1 pitch 段力臂（mm）")
    a1.legend(frameon=False, fontsize=7.2, loc="lower right", borderaxespad=0.2)
    a1.annotate("两条曲线几乎重合", xy=(30, -25), fontsize=7.4, color=INK)
    a2.plot(st["ang"], st["dif"], color=C3C, lw=1.5)
    a2.plot(-25, 0.032668, "o", color=RED, ms=4.5, zorder=5)
    a2.annotate("边界单侧模板：0.032668 mm @ −25°", xy=(-25, 0.032668),
                xytext=(-19, 0.030), fontsize=7.4, color=INK,
                arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.7))
    style(a2, "pitch 角（°）", "两者之差（mm）")
    a2.xaxis.set_major_formatter(D)
    save(fig, "stencil")

# ---------- 4 sign ----------
def fig_sign():
    abc = abc_of("C2", "roll")
    xs = np.arange(-25, 25.05, 0.5)
    right = [r_of(abc, x) for x in xs]
    wrong = [(-647 * math.cos(deg(x)) + 1935 * math.sin(deg(x))) / (2 * s_of(abc, x)) for x in xs]
    fig, ax = plt.subplots(figsize=(6.9, 3.6))
    ax.plot(xs, wrong, color=RED, lw=1.5, ls=(0, (5, 3)),
            label="文档 (27) 印刷式（sin 项符号错）")
    ax.plot(xs, right, color=C2C, lw=1.9,
            label="正确式：r=(βsinθ−γcosθ)/(2√D)，即 (23) 代入")
    cx = [p[0] for p in DATA["cadC2roll"]]; cy = [p[1] for p in DATA["cadC2roll"]]
    ax.plot(cx, cy, "o", color=INK, ms=2.8, label="CAD 网格点（pitch=0，51 点）")
    ax.plot(0, -22.05, "o", ms=8, mfc="none", mec=INK, mew=1.1)
    ax.annotate("θ=0：两式同为 −22.05\n（错误被掩盖）", xy=(0, -22.05),
                xytext=(3.5, -40), fontsize=7.3, color=INK,
                arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.7))
    ax.axvline(17, color="#d5d9de", lw=0.8, ls=(0, (3, 3)), zorder=1)
    ax.annotate("θ=17°：CAD −26.78 落在正确式上\n印刷式 ≈ −1.2（错误）", xy=(17, 8),
                fontsize=7.3, color=INK, ha="center",
                xytext=(17, 4.5))
    style(ax, "roll 角（°）", "C2 roll 力臂（mm）")
    ax.xaxis.set_major_formatter(D)
    ax.legend(frameon=False, fontsize=7.2, loc="lower left", borderaxespad=0.2)
    save(fig, "sign")

# ---------- 5 decouple ----------
def fig_decouple():
    fig, ax = plt.subplots(figsize=(6.7, 2.8))
    xpos = np.arange(3)
    cur = [1e-8] * 3
    cnt = DATA["decoupleCounter"]
    ax.bar(xpos - 0.19, cur, width=0.34, color=C1C, alpha=0.85, zorder=3,
           label="当前绳路（解析恒为 0，数值 ≤ 1e−8）")
    ax.bar(xpos + 0.19, cnt, width=0.34, color=C2C, alpha=0.92, zorder=3,
           label="反例：加 base→palm 直连段")
    ax.set_yscale("log")
    for x, v in zip(xpos + 0.19, cnt):
        ax.annotate("%.3g" % v, (x, v), textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=7.0, color=INK)
    ax.annotate("≈0", (-0.19, 1e-8), textcoords="offset points", xytext=(-2, 4),
                ha="center", fontsize=7.0, color=INK)
    ax.set_xticks(xpos, ["C1", "C2", "C3"], fontsize=7.6)
    style(ax, "", "混合偏导 |∂²l/∂θr∂θp|（mm/rad²）")
    ax.set_ylim(3e-9, 12)
    ax.legend(frameon=False, fontsize=7.2, loc="upper right", borderaxespad=0.2)
    save(fig, "decouple")

# ---------- 6 smin ----------
def fig_smin():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.9, 2.9), constrained_layout=True)
    for ax, seg, lo, hi in ((a1, "roll", -25, 25), (a2, "pitch", -25, 45)):
        xs = np.arange(lo, hi + 0.25, 0.25)
        for i, k in enumerate(("C1", "C2", "C3")):
            abc = abc_of(k, seg)
            ax.plot(xs, [s_of(abc, x) for x in xs], color=CC[i], lw=1.5,
                    label="%s/%s" % (k, seg))
            m = abc["minAng"]
            if lo <= m <= hi:
                c = RED if (k == "C1" and seg == "pitch") else CC[i]
                ax.plot(m, abc["minS"], "o", color=c, ms=4.2, zorder=5)
                ax.annotate("%.2f" % abc["minS"], (m, abc["minS"]),
                            textcoords="offset points", xytext=(0, 6), ha="center",
                            fontsize=6.8, color=INK)
        style(ax, seg + " 角（°）", "段长 s（mm）")
        ax.xaxis.set_major_formatter(D)
        ax.legend(frameon=False, fontsize=6.8, loc="lower right", borderaxespad=0.2,
                  handlelength=1.4)
    a2.annotate("C1/pitch 仅 3.90 mm @ −25°：短段高危区", xy=(-24, 30),
                fontsize=7.2, color=RED)
    save(fig, "smin")

# ---------- 7 grad ----------
def fig_grad():
    pts = ["P04", "P05", "P06", "P07"]
    fig, ax = plt.subplots(figsize=(6.7, 2.8))
    xpos = np.arange(4)
    w = 0.26
    for j, k in enumerate(("C1", "C2", "C3")):
        vals = [DATA["grad"][p][j] for p in pts]
        ax.bar(xpos + (j - 1) * w, vals, width=w, color=CC[j], alpha=0.9, zorder=3,
               label=k)
        for x, v in zip(xpos + (j - 1) * w, vals):
            if v > 0.6:
                ax.annotate("%.2f" % v, (x, v), textcoords="offset points",
                            xytext=(0, 3), ha="center", fontsize=6.6, color=INK)
    ax.set_xticks(xpos, pts, fontsize=7.6)
    style(ax, "跨关节段端点（零位）", "位置梯度范数（mm/mm）")
    ax.set_ylim(0, 2.6)
    ax.legend(frameon=False, fontsize=7.2, ncol=3, loc="upper right", borderaxespad=0.2)
    ax.annotate("−25° 时 C1/pitch 对 P06 梯度达 15.7 mm/mm", xy=(1.5, 2.38),
                fontsize=7.2, color=INK, ha="center")
    save(fig, "grad")

# ---------- 8 phase ----------
def fig_phase():
    abc = abc_of("C2", "roll")
    d = deg(3.7)
    Bp = abc["B"] * math.cos(d) + abc["C"] * math.sin(d)
    Cp = abc["C"] * math.cos(d) - abc["B"] * math.sin(d)
    xs = np.arange(-25, 25.05, 0.5)
    d0 = [abc["A"] + abc["B"] * math.cos(deg(q)) + abc["C"] * math.sin(deg(q)) for q in xs]
    d1 = [abc["A"] + abc["B"] * math.cos(deg(q) + d) + abc["C"] * math.sin(deg(q) + d) for q in xs]
    d2 = [abc["A"] + Bp * math.cos(deg(q)) + Cp * math.sin(deg(q)) for q in xs]
    fig, ax = plt.subplots(figsize=(6.7, 3.0))
    ax.plot(xs, d0, color=GRAY, lw=1.2, label="参考：未移相 D(q; β,γ)")
    ax.plot(xs, d1, color=C1C, lw=2.0, label="真实参数 D(q+δ; β,γ)，δ=3.7°")
    ax.plot(xs, d2, color=C3C, lw=1.3, ls=(0, (5, 3)),
            label="等效参数 D(q; β′,γ′)，δ=0")
    style(ax, "编码器读数 q（°）", "D = s²（mm²）")
    ax.xaxis.set_major_formatter(D)
    ax.legend(frameon=False, fontsize=7.2, loc="upper center", borderaxespad=0.2)
    ax.annotate("实线与虚线完全重合 → 长度数据无法区分 (β,γ,δ) 与 (β′,γ′,0)",
                xy=(0, ax.get_ylim()[0] * 0.96 + (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.06),
                fontsize=7.3, color=INK, ha="center")
    save(fig, "phase")

# ---------- 9 preload ----------
def fig_preload():
    from matplotlib.colors import ListedColormap
    M = np.array([[0 if ch == "1" else 1 for ch in row] for row in DATA["pmap"]])
    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    ax.imshow(M, cmap=ListedColormap(["#dfe3e9", "#D55E00"]), aspect="auto",
              interpolation="nearest", alpha=0.92,
              extent=[-25, 25, 45, -25])
    style(ax, "roll（°）", "pitch（°）", grid_axis=None)
    ax.set_xticks(range(-20, 26, 10))
    ax.set_yticks(range(-20, 50, 10))
    import matplotlib.patches as mpatches
    h = [mpatches.Patch(color="#dfe3e9", label="存在全正预紧方向"),
         mpatches.Patch(color="#D55E00", label="不存在（1,664 / 3,621 姿态）")]
    ax.legend(handles=h, frameon=False, fontsize=7.4, loc="upper center",
              bbox_to_anchor=(0.5, 1.14), ncol=2)
    save(fig, "preload")

if __name__ == "__main__":
    fig_schema(); fig_grid(); fig_stencil(); fig_sign(); fig_decouple()
    fig_smin(); fig_grad(); fig_phase(); fig_preload()
    print("figs2 done")
