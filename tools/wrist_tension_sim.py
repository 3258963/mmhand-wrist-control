"""张力控制离线仿真 —— 不接实机、不连串口，用**真实的律**驱动一个假想被控对象。

用法（在 code/mmhand-main 下）：
    # 1) 预设矩阵 + 两张图（默认）
    .venv\\Scripts\\python.exe -m tools.wrist_tension_sim

    # 2) 只算一组参数，打印过程摘要
    .venv\\Scripts\\python.exe -m tools.wrist_tension_sim --case --s 0.05 --kp 10 --ki 10

    # 3) 换噪声/伺服跟随速度/每拍限幅
    .venv\\Scripts\\python.exe -m tools.wrist_tension_sim --case --s 0.2 --kp 8 --noise 0.03 --beta 0.6

模型（单缆，三缆相同且互不影响——张力模式本来就是对角结构）

    被控对象：  pos[n+1] = pos[n] + β·(target[n] − pos[n])      位置伺服一阶跟随
                Δf       = S · (pos[n+1] − pos[n])              S = N/count（等效绳刚度）
                f_true   = clamp(f_true + Δf, 0, ∞)             绳只能拉：f ≥ 0
    控制器：    wrist_tension_step(params, state, f_meas, age, dt)  ← 仓里真实的律
    执行器：    target = clamp(pos_meas + trim, base ± max_trim)   ← 与 _apply_force_step 同口径
    测量：      f_meas = f_true + N(0, σ) ，再量化到 1 raw = 0.0098 N

符号约定：S > 0 = trim 方向填对了（counts↑ ⇒ 该缆张力↑）；
          S < 0 = trim 方向填反了 —— 用来复现"错符号 = 飞车"。
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from wrist_force_law import (WristTensionParams, WristTensionState,  # noqa: E402
                             wrist_tension_step)

RAW_N = 0.00980665        # 1 raw = 1 g（与 TENSION_N_PER_RAW 同量级）
DT = 0.01                 # 100 Hz
F_MAX = 30.0


# ---------------------------------------------------------------------------
# 单次仿真
# ---------------------------------------------------------------------------
def simulate(s: float, kp: float, ki: float, u_max: float = 5.0,
             f0: float = 1.0, target: float = 2.0, noise: float = 0.02,
             beta: float = 1.0, quant: float = RAW_N, max_trim: float = 3000.0,
             ticks: int = 600, seed: int = 0) -> dict:
    """跑一次单缆闭环，返回轨迹与指标。"""
    rng = random.Random(seed)
    p = WristTensionParams(
        f_target=(target, target, target), kp=kp, ki=ki,
        max_step=u_max, trim_sign=(1.0, 1.0, 1.0), max_trim=max_trim,
        f_max=F_MAX, deadband=0.05)
    st = WristTensionState()

    f = f0                     # 真实张力
    pos = 0.0                  # 真实电机位置（counts，相对）
    base = 0.0                 # 进入时的位置（max_trim 的基准）
    tr = {"f": [], "meas": [], "trim": [], "target": []}

    for _ in range(ticks):
        # —— 测量 ——
        f_true = max(0.0, f)
        meas = f_true + rng.gauss(0.0, noise) if noise > 0 else f_true
        if quant > 0:
            meas = round(meas / quant) * quant
        trim, flags = wrist_tension_step(p, st, (meas, meas, meas), 0.0, DT)
        if trim is None:                       # 过期/过载 → 本拍不动作
            tr["f"].append(f_true); tr["meas"].append(meas)
            tr["trim"].append(0.0); tr["target"].append(target)
            continue
        cmd = trim[0]
        # —— 执行器：target = 实测位置 + trim，夹 base ± max_trim ——
        tgt = pos + cmd
        tgt = max(base - max_trim, min(base + max_trim, tgt))
        # —— 位置伺服：一阶跟随 ——
        pos_next = pos + beta * (tgt - pos)
        # —— 力学 ——
        f = max(0.0, f + s * (pos_next - pos))
        pos = pos_next

        tr["f"].append(f); tr["meas"].append(meas)
        tr["trim"].append(cmd); tr["target"].append(target)

    return {"trace": tr, "metrics": _metrics(tr["f"], target)}


def _metrics(f_list, target: float) -> dict:
    """收敛拍数 / 过冲 / 稳态误差 / 末段幅度（极限环）/ 过载 / 发散。"""
    n = len(f_list)
    peak = max(f_list) if f_list else 0.0
    over = peak >= F_MAX * 0.999
    diverged = (max(abs(v) for v in f_list) > abs(target) + 20.0) or any(
        math.isnan(v) for v in f_list)
    tail = f_list[int(n * 0.8):] or f_list
    ss_err = sum(tail) / len(tail) - target
    ripple = (max(tail) - min(tail)) if tail else 0.0
    # 尾段穿越目标线的次数：多 → 在抖；少 → 还在慢慢爬
    cross = sum(1 for i in range(1, len(tail))
                if (tail[i] - target) * (tail[i - 1] - target) < 0) if tail else 0

    # t90：第一次进入"距目标 10%"的时刻（比"连续 100 拍在带内"稳，不被噪声打断）
    band = 0.1 * abs(target - f_list[0]) if f_list else 0.1
    t90 = None
    for i, v in enumerate(f_list):
        if abs(v - target) <= max(band, 0.02):
            t90 = i
            break
    return {"diverged": diverged, "overload": over, "t90": t90,
            "ripple": ripple, "ss_err": ss_err, "peak": peak, "cross": cross}


def classify(m: dict, target: float) -> str:
    """四类结局：bad=发散/过载，cycle=抖动，slow=还在爬，ok=到位。"""
    if m["diverged"] or m["overload"]:
        return "bad"
    if m["t90"] is None:
        # 一直没进 10% 带：抖动会反复穿越目标线，慢爬不会
        return "cycle" if m["cross"] >= 5 else "slow"
    return "cycle" if m["ripple"] > 0.12 else "ok"


def verdict(m: dict, target: float) -> str:
    c = classify(m, target)
    if c == "bad":
        return f"过载（冲到 {m['peak']:.1f}N 后冻结）" if m["overload"] else "发散"
    if c == "slow":
        return f"600 拍还没到 90%（末段误差 {m['ss_err']:+.2f}N）"
    if c == "cycle":
        return f"到位但抖（末段幅度 {m['ripple']:.2f}N）"
    return f"90% 到位 {m['t90']} 拍（{m['t90']*DT:.2f}s）"


# ---------------------------------------------------------------------------
# 预设矩阵
# ---------------------------------------------------------------------------
CASES = [
    # (S, Kp, f0, 说明)  目标恒为 2.0 N
    (0.020, 10.0, 1.0, "软系统，默认 Kp=10（S·Kp=0.2）"),
    (0.050, 10.0, 1.0, "中等刚度，默认 Kp=10（S·Kp=0.5）"),
    (0.100, 10.0, 1.0, "偏硬（S·Kp=1，一拍到位）"),
    (0.200, 10.0, 1.0, "S·Kp=2 但从远处起步 → 被每拍限幅掩蔽"),
    (0.200, 10.0, 1.9, "S·Kp=2 且从目标附近起步 → 等幅抖动"),
    (0.050, 60.0, 1.0, "Kp 过大（S·Kp=3）"),
    (-0.050, 10.0, 2.5, "trim 方向反 + 该松却紧 → 冲过 fmax"),
    (-0.050, 10.0, 1.0, "trim 方向反 + 该紧却松 → 放到 0"),
]

SWEEP_S = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3]
SWEEP_KP = [2.0, 5.0, 10.0, 20.0, 40.0, 60.0, 100.0, 150.0]


def run_cases(ki: float, u_max: float, noise: float, beta: float) -> list:
    print("=" * 96)
    print(f"单缆闭环（目标 2.0N，Ki={ki:g}，每拍限幅={u_max:g}，噪声 σ={noise:g}N，β={beta:g}）")
    print("=" * 96)
    print(f"  {'f0':>5} {'S(N/c)':>8} {'Kp':>6} {'S·Kp':>7}  {'结果':<28} {'过冲N':>7}  说明")
    print("  " + "-" * 92)
    rows = []
    for s, kp, f0, note in CASES:
        r = simulate(s, kp, ki, u_max=u_max, noise=noise, beta=beta, f0=f0)
        m = r["metrics"]
        over = max(0.0, m["peak"] - 2.0)
        print(f"  {f0:5.1f} {s:+8.3f} {kp:6.1f} {s*kp:+7.2f}  {verdict(m, 2.0):<28} "
              f"{over:7.2f}  {note}")
        rows.append((s, kp, f0, m))
    print()

    # Ki 的影响（固定 S=0.05, Kp=10）：默认 Ki=10，看它把收敛拖慢多少
    print(f"  Ki 的影响（S=0.05, Kp=10, f0=1.0, Ki 默认 10）")
    print(f"  {'Ki':>6}  {'结果':<28} {'末段幅度':>8}")
    print("  " + "-" * 50)
    for ki_v in (0.0, 2.0, 5.0, 10.0, 20.0, 50.0):
        m = simulate(0.05, 10.0, ki_v, u_max=u_max, noise=noise, beta=beta,
                     ticks=600)["metrics"]
        print(f"  {ki_v:6.0f}  {verdict(m, 2.0):<28} {m['ripple']:8.3f}")
    print()
    return rows


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------
def make_figures(out_dir: Path, ki: float, u_max: float, noise: float, beta: float,
                 mark_s: float = 0.0) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    INK, MUTED, GRID = "#24303f", "#6b7785", "#dfe4ea"
    BLUE, RED, GREEN, AMBER, PURPLE = "#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#7c3aed"

    # ---------- 图 A：2×2（稳定性地图 + 三种典型响应） ----------
    fig, axs = plt.subplots(2, 2, figsize=(13.6, 9.6), dpi=170)
    t = np.arange(600) * DT

    def draw(a, cases, ylim, title):
        for (s, kp, f0), col, lab in cases:
            r = simulate(s, kp, ki, u_max=u_max, noise=noise, beta=beta, f0=f0)
            f = np.array(r["trace"]["f"])
            a.plot(t[:len(f)], f, color=col, lw=1.7, label=lab)
        a.axhline(2.0, color=MUTED, lw=1.0, ls=":")
        a.set_xlim(0, 3.0)
        a.set_ylim(*ylim)
        a.set_xlabel("时间 (s)", color=INK)
        a.set_ylabel("单缆张力 f (N)", color=INK)
        a.set_title(title, color=INK, fontsize=11.5)
        a.legend(fontsize=8.0, loc="center right", framealpha=0.92)
        a.grid(color=GRID, lw=0.7)

    # (a) 稳定性地图：散点分类（比色块更诚实：未收敛/极限环/发散分得开）
    ax = axs[0, 0]
    cats = {"ok": [], "cycle": [], "slow": [], "bad": []}
    for s in SWEEP_S:
        for kp in SWEEP_KP:
            m = simulate(s, kp, ki, u_max=u_max, noise=noise, beta=beta,
                         ticks=600)["metrics"]
            c = classify(m, 2.0)
            if c == "ok":
                cats["ok"].append((s, kp, m["t90"] + 1))
            else:
                cats[c].append((s, kp))

    ss = np.logspace(math.log10(SWEEP_S[0]), math.log10(SWEEP_S[-1]), 60)
    ax.fill_between(ss, 0.2 / ss, 0.5 / ss, color=GREEN, alpha=0.22,
                    label="$S\\cdot K_p=0.2\\sim0.5$（推荐带）")
    ax.plot(ss, 2.0 / ss, "--", color=RED, lw=1.4, label="$S\\cdot K_p=2$（理论边界）")
    if cats["ok"]:
        xs = [c[0] for c in cats["ok"]]
        ys = [c[1] for c in cats["ok"]]
        cs = [c[2] for c in cats["ok"]]
        sc = ax.scatter(xs, ys, c=cs, cmap="viridis", s=70, marker="o",
                        edgecolors="white", linewidths=0.6, zorder=4,
                        label="收敛（颜色=拍数）")
        cb = fig.colorbar(sc, ax=ax, pad=0.02)
        cb.set_label("收敛拍数", fontsize=8.5)
    if cats["slow"]:
        ax.scatter([c[0] for c in cats["slow"]], [c[1] for c in cats["slow"]],
                   s=46, marker="x", color=MUTED, zorder=4, label="600 拍还在爬（太慢）")
    if cats["cycle"]:
        ax.scatter([c[0] for c in cats["cycle"]], [c[1] for c in cats["cycle"]],
                   s=52, marker="s", facecolors="none", edgecolors=AMBER,
                   linewidths=1.6, zorder=4, label="抖动（1 count = S N 的粒度 / 增益过大）")
    if cats["bad"]:
        ax.scatter([c[0] for c in cats["bad"]], [c[1] for c in cats["bad"]],
                   s=70, marker="*", color=RED, zorder=5, label="发散/过载")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("等效绳刚度 S (N/count)", color=INK)
    ax.set_ylabel("$Kp_f$ (counts/N)", color=INK)
    ax.set_title("(a) 稳定性地图：仿真的四类结局 vs 理论边界", color=INK, fontsize=11.5)
    ax.legend(fontsize=7.6, loc="lower left", framealpha=0.92)
    ax.grid(color=GRID, lw=0.6, which="both", alpha=0.6)
    if mark_s > 0:
        ax.axvline(mark_s, color=PURPLE, lw=1.3, ls="-.")
        ax.plot([mark_s], [10.0], marker="D", ms=8, mfc=PURPLE, mec="white", mew=1.2,
                zorder=9, label="_")
        ax.annotate(f"实测 S={mark_s:.4f}\n(默认 Kp=10)", xy=(mark_s, 10.0),
                    xytext=(8, 26), textcoords="offset points", fontsize=8.2,
                    color=PURPLE, zorder=9,
                    arrowprops=dict(arrowstyle="->", color=PURPLE, lw=0.9))

    # (b) 正常三例（同一条曲线族：软 / 中 / 硬）
    draw(axs[0, 1],
         [((0.02, 10.0, 1.0), BLUE, "$S$=0.02（软，S·Kp=0.2）"),
          ((0.05, 10.0, 1.0), GREEN, "$S$=0.05（中，S·Kp=0.5）"),
          ((0.10, 10.0, 1.0), AMBER, "$S$=0.10（硬，S·Kp=1）")],
         (0.8, 2.6), "(b) 默认 Kp=10：S 越大越快")

    # (c) S·Kp=2 的两种起步：饱和把"大误差"救回来，近目标才暴露抖动
    draw(axs[1, 0],
         [((0.20, 10.0, 1.9), RED, "从 1.9N 起步（近）→ 等幅抖 ±0.5N"),
          ((0.20, 10.0, 1.0), BLUE, "从 1.0N 起步（远）→ 饱和掩蔽，平在 2.0N")],
         (1.0, 3.2), "(c) 同一个 S·Kp=2：远看没事，近目标才抖")

    # (d) trim 方向反：该松却紧 → 冲过 fmax 冻结
    draw(axs[1, 1],
         [((-0.05, 10.0, 2.5), PURPLE, "$S<0$：目标 2N、实测 2.5N → 越纠越紧")],
         (0, 33), "(d) trim 方向反的两种结局（这里：冲到 fmax 冻结）")
    axs[1, 1].axhline(F_MAX, color="#b91c1c", lw=1.0, ls="--")
    axs[1, 1].text(0.08, F_MAX - 2.4, f"fmax = {F_MAX:g} N（过载停环）",
                   color="#b91c1c", fontsize=8.5)

    for a in axs.ravel():
        for sp in a.spines.values():
            sp.set_color(GRID)
    fig.tight_layout()
    fig.savefig(out_dir / "tension_sim_map.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # ---------- 图 B：给定 S，Kp 的安全区 ----------
    fig, ax = plt.subplots(figsize=(7.6, 5.4), dpi=170)
    s_arr = np.logspace(-3, math.log10(0.35), 200)
    ax.fill_between(s_arr, 0.2 / s_arr, 0.5 / s_arr, color=GREEN, alpha=0.25,
                    label="推荐 $0.2/S \\leq Kp < 0.5/S$")
    ax.plot(s_arr, 2.0 / s_arr, "--", color=RED, lw=1.6, label="$Kp_{max}=2/S$（稳定上限）")
    ax.plot(s_arr, 10.0 + 0 * s_arr, "-", color=BLUE, lw=1.6,
            label="当前默认 $Kp_f=10$")
    # 把仿真的稳定点叠上来
    ok_s, ok_k = [], []
    for s in SWEEP_S:
        for kp in SWEEP_KP:
            m = simulate(s, kp, ki, u_max=u_max, noise=noise, beta=beta,
                         ticks=600)["metrics"]
            if (not m["diverged"]) and (not m["overload"]) and m["ripple"] <= 0.12 \
                    and m["t90"] is not None:
                ok_s.append(s)
                ok_k.append(kp)
    ax.plot(ok_s, ok_k, "o", ms=5, mfc="white", mec=INK, mew=1.1,
            label="仿真判为收敛的点", zorder=5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("等效绳刚度 S (N/count)  ← 上机测一次", color=INK)
    ax.set_ylabel("$Kp_f$ (counts/N)", color=INK)
    ax.set_title("给定 S 该选多大 Kp：默认 10 只在绿色带里才合适", color=INK, fontsize=12, pad=10)
    ax.grid(color=GRID, lw=0.7, which="both", alpha=0.6)
    ax.legend(fontsize=9, loc="upper right", framealpha=0.92)
    if mark_s > 0:
        lo, hi = 0.2 / mark_s, 0.5 / mark_s
        ax.axvline(mark_s, color=PURPLE, lw=1.3, ls="-.")
        ax.annotate(f"S={mark_s:.4f}\n→ Kp 取 {lo:.0f}~{hi:.0f}",
                    xy=(mark_s, 10.0), xytext=(-96, 40), textcoords="offset points",
                    fontsize=9, color=PURPLE,
                    arrowprops=dict(arrowstyle="->", color=PURPLE, lw=1.0))
    for sp in ax.spines.values():
        sp.set_color(GRID)
    fig.tight_layout()
    fig.savefig(out_dir / "tension_sim_kp.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="张力控制离线仿真（不接实机）")
    ap.add_argument("--case", action="store_true", help="只算一组参数并打印摘要")
    ap.add_argument("--s", type=float, default=0.05, help="等效绳刚度 N/count（负=方向反）")
    ap.add_argument("--kp", type=float, default=10.0)
    ap.add_argument("--ki", type=float, default=10.0)
    ap.add_argument("--u-max", type=float, default=5.0, help="每拍限幅 counts/拍")
    ap.add_argument("--noise", type=float, default=0.02, help="张力测量噪声 σ (N)")
    ap.add_argument("--beta", type=float, default=1.0, help="位置伺服每拍跟随比例（1=一拍到位）")
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--mark-s", type=float, default=0.0,
                    help="在图上标出实测 S（N/count），0=不标")
    ap.add_argument("--no-fig", action="store_true")
    ap.add_argument("--out", default="../../figs", help="出图目录")
    args = ap.parse_args(argv)

    if args.case:
        r = simulate(args.s, args.kp, args.ki, u_max=args.u_max,
                     noise=args.noise, beta=args.beta, ticks=args.ticks)
        m = r["metrics"]
        print(f"S={args.s:+.4f} N/count  Kp={args.kp:g}  Ki={args.ki:g}  "
              f"u_max={args.u_max:g}  β={args.beta:g}  噪声σ={args.noise:g}")
        print(f"  S·Kp = {args.s*args.kp:+.2f}   →  {verdict(m, 2.0)}")
        print(f"  过冲 = {max(0.0, m['peak']-2.0):.3f} N   稳态误差 = {m['ss_err']:+.3f} N   "
              f"末段幅度 = {m['ripple']:.3f} N")
        f = r["trace"]["f"]
        idx = [0, 1, 2, 5, 10, 20, 50, 100, 200, len(f) - 1]
        print("  抽样轨迹 f(t): " + "  ".join(f"{i}:{f[i]:.2f}" for i in idx if i < len(f)))
        return 0

    run_cases(args.ki, args.u_max, args.noise, args.beta)
    if args.no_fig:
        return 0
    out = Path(args.out)
    if not out.is_absolute():
        out = (_REPO_ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    make_figures(out, args.ki, args.u_max, args.noise, args.beta, args.mark_s)
    for n in ("tension_sim_map.png", "tension_sim_kp.png"):
        p = out / n
        print(f"  出图: {p}  {p.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
