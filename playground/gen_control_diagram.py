# -*- coding: utf-8 -*-
"""上位机控制框图生成脚本（2026-11-01）。

内容：双模式闭环全景——位置模式（FF+P）与张力·力控模式（PI→trim），
PC 内部两条循环 + 滤波桥 + 安全层 + 曲线通道汇合。
数据来源：mmhand_scope.py / wrist_control_law.py / wrist_model.py /
wrist_force_law.py / wrist_filter.py 当前实现（行号口径 2026-11-01）。
重画：.venv\\Scripts\\python playground/gen_control_diagram.py
输出：仓库根 控制框图.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# 深色主题（与上位机 app_theme.night 同族）
BG = "#0d1015"
CARD = "#161c25"
CARD_LINE = "#232d3c"
TEXT = "#e8ecf2"
MUTED = "#8b94a3"
ACCENT = "#3b82f6"    # 位置模式
ACCENT2 = "#22d3ee"   # 力控模式
GOOD = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"
BRIDGE = "#a78bfa"    # 共享/滤波桥

FILL = {"pos": "#12203a", "force": "#0f2733", "bridge": "#1d1830",
        "safe": "#2a1512", "io": "#151a22", "title": "#10141b"}
EDGE = {"pos": ACCENT, "force": ACCENT2, "bridge": BRIDGE,
        "safe": BAD, "io": CARD_LINE, "title": CARD_LINE}

fig, ax = plt.subplots(figsize=(18, 10.6), dpi=170)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 100)
ax.set_ylim(0, 64)
ax.axis("off")


def box(x0, y0, x1, y1, text, kind="io", fs=9.6, tc=None, lw=1.5, bold=False):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                                boxstyle="round,pad=0.25,rounding_size=0.8",
                                facecolor=FILL[kind], edgecolor=EDGE[kind],
                                linewidth=lw, zorder=2))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
            fontsize=fs, color=tc or TEXT, linespacing=1.55, zorder=3,
            fontweight="bold" if bold else "normal")


def arrow(x0, y0, x1, y1, color, lw=1.8, style="-|>", conn="arc3,rad=0.0", ls="-"):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style,
                                 mutation_scale=15, color=color, linewidth=lw,
                                 connectionstyle=conn, linestyle=ls, zorder=1))


# ============ 标题 ============
ax.text(50, 62.6, "MMHand 腕部上位机 · 双模式控制框图", ha="center", va="center",
        fontsize=19, color=TEXT, fontweight="bold")
ax.text(50, 60.9, "PC 内部两条循环 + 滤波桥 ｜ 位置模式 FF+P ｜ 张力·力控 PI→trim ｜ "
        "均终止于同一条编码器位置命令（m*_tgt）",
        ha="center", va="center", fontsize=10.5, color=MUTED)

# ============ 左侧：反馈链（循环 A） ============
ax.text(12.5, 58.6, "反馈链 · 循环 A（收数线程 ~128Hz）", fontsize=11.5,
        color=GOOD, fontweight="bold", ha="center")

box(2.5, 52.2, 22.5, 55.6,
    "磁编码器 J16/J17 帧\n(uint16 raw × 21 路)", "io", fs=10)
box(2.5, 45.6, 22.5, 50.8,
    "① 过圈解绕 unwrap\nraw + 16384·round((prev−raw)/16384)", "bridge", fs=9.6)
box(2.5, 39.0, 22.5, 44.2,
    "② 中值滤波 N=5（砍 EMI 尖刺）\n③ EMA α=0.05（1.4°→0.1°，~150ms 滞后）", "bridge", fs=9.6)
box(2.5, 32.4, 22.5, 37.6,
    "④ 角度换算\ndeg = raw/16384·360 × AXIS_SIGN\n相对角 = 最短角差(当前 − 归零基准)", "bridge", fs=9.6)

arrow(12.5, 52.2, 12.5, 50.8, GOOD)
arrow(12.5, 45.6, 12.5, 44.2, GOOD)
arrow(12.5, 39.0, 12.5, 37.6, GOOD)

# 滤波桥（共享数据）
box(2.5, 26.2, 22.5, 30.8,
    "★ 滤波桥 _enc_filt_raw[16/17]\n两条循环唯一的共享点", "bridge", fs=10, tc=BRIDGE, lw=2.0, bold=True)
arrow(12.5, 32.4, 12.5, 30.8, GOOD)

# 张力反馈（左下，力控用）
box(2.5, 19.0, 22.5, 23.6,
    "张力实测 f1/f2/f3 (ZNSV, 250Hz)\nCOM23 · t(送入时) 用于年龄判定", "io", fs=9.6, tc="#f0abfc")
ax.text(12.5, 17.6, "（观测台连接后有效）", fontsize=8.5, color=MUTED, ha="center")

# ============ 中上：模式选择 ============
box(29, 55.0, 71, 58.4,
    "控制定时器 _cl_timer · 200Hz（每 5ms 一拍）——  一拍八步："
    "安检 → 读反馈 → 读目标 → 张力守卫 → 参数(20Hz 节流) → 控制律 → 变更抑制 → 发送",
    "title", fs=9.8, tc=MUTED)

box(29, 47.6, 49, 51.6, "模式：位置模式", "pos", fs=12, bold=True)
box(51, 47.6, 71, 51.6, "模式：张力·力控", "force", fs=12, bold=True)

# ============ 中左：位置模式路径 ============
ax.text(39, 45.9, "被控量：关节角度 θ", fontsize=9.5, color=ACCENT, ha="center", style="italic")
box(29, 39.4, 49, 44.2,
    "目标 θ*（UI 框/扫掠三角波）\n钳制：UI限幅 ∩ 模型行程 ∩ pitch≥−24°\n"
    "+δ → deg→rad（全链唯一转换点）", "pos", fs=9.2)
box(29, 33.0, 49, 37.8,
    "模型求值 ×3（wrist_model）\n6 段几何: s=√(d1²+d2²+h²)\nR = 力臂 −∂l/∂θ (2×3)", "pos", fs=9.2)
box(29, 26.6, 49, 31.4,
    "前馈 ff = k·Δl        \"到位该走多少\"\n校正 corr = −kp·k·(R·e)  \"误差按力臂分配\"\n"
    "e 过死区 0.3°；out = origin + ff + corr", "pos", fs=9.2)

arrow(39, 47.6, 39, 44.2, ACCENT)
arrow(39, 39.4, 39, 37.8, ACCENT)
arrow(39, 33.0, 39, 31.4, ACCENT)

# ============ 中右：力控模式路径 ============
ax.text(61, 45.9, "被控量：三缆张力 f", fontsize=9.5, color=ACCENT2, ha="center", style="italic")
box(51, 39.4, 71, 44.2,
    "力矩目标 τ_d（N·m）+ 预紧\nTDA 力分配（零空间全正方向）\n→ 每缆张力目标 f*_i", "force", fs=9.2)
box(51, 33.0, 71, 37.8,
    "张力误差 e = f* − f（实测）\n纯 P：trim = Kp_f · e（死区 0.05N）\n【I 已按用户要求归零，结构保留】", "force", fs=9.2)
box(51, 26.6, 71, 31.4,
    "位置微调 trim（±max_trim 抗饱和）\n基准 base = 投入时刻的指令位置\n角度目标被忽略 · 手掰腕顺从回力", "force", fs=9.2)

arrow(61, 47.6, 61, 44.2, ACCENT2)
arrow(61, 39.4, 61, 37.8, ACCENT2)
arrow(61, 33.0, 61, 31.4, ACCENT2)

# 力控读张力实测（从左侧跨过来）
arrow(22.5, 21.3, 51, 28.5, "#c084fc", lw=1.6, conn="arc3,rad=-0.12")
ax.text(34.5, 24.8, "f 实测 → 张力环", fontsize=8.8, color="#c084fc", ha="center")

# 位置模式读滤波桥
arrow(22.5, 28.5, 29, 41.8, GOOD, lw=1.6, conn="arc3,rad=0.18")
ax.text(24.4, 36.2, "θ 反馈", fontsize=8.8, color=GOOD, ha="center", rotation=90)

# ============ 汇合：编码器位置命令 ============
box(29, 18.4, 71, 23.2,
    "★ 汇合：编码器位置命令 out_i = 位置目标（counts）\n"
    "位置模式: origin + ff + corr  ｜  力控: base + trim\n"
    "变更抑制（不变不发，稳态零流量）→ m27/m28/m29_tgt 通道 + 串口 0xDE",
    "io", fs=10, tc="#f5f8ff", lw=2.2, bold=True)

arrow(39, 26.6, 39, 23.2, ACCENT)
arrow(61, 26.6, 61, 23.2, ACCENT2)

# ============ 底部：安全层 ============
ax.text(50, 13.6, "安 全 层（每拍在岗 · 自上而下兜底）", fontsize=11,
        color=BAD, fontweight="bold", ha="center")
safes = [
    ("输入钳制\n限幅∩行程∩pitch抬底", 6.0),
    ("死区 0.3°/0.05N\n稳态防抖", 23.5),
    ("软限位 ±5000\n输出端末闸", 41.0),
    ("硬错误保持\nNaN/几何退化→冻结", 58.5),
    ("张力守卫\nf>f_max → 停环", 76.0),
    ("样本过期冻结\n>300ms 电机保持", 93.5),
]
for txt, x in safes:
    box(x - 7.2, 7.6, x + 7.2, 12.4, txt, "safe", fs=8.8, tc="#ffc9c9")

# ============ 底部注脚 ============
ax.text(50, 4.6, "文件归属：调度/UI = mmhand_scope.py ｜ 控制律 = wrist_control_law.py / wrist_force_law.py ｜ "
        "几何 = wrist_model.py ｜ 滤波 = wrist_filter.py",
        fontsize=9.2, color=MUTED, ha="center")
ax.text(50, 2.8, "标定参数：k=130,380 c/m（固定标称：绕线半径 5mm + 4096 c/圈）· δ=0（占位）· AXIS_SIGN={J16:+1, J17:−1}（实测） ｜ "
        "曲线通道：m*_tgt（两模式共用）· tension_f* · force_trim_* · force_tau_*_tgt",
        fontsize=9.2, color=MUTED, ha="center")
ax.text(50, 1.0, "P（两模式都有）· I（力控结构保留、当前=0）· D（全系统无）—— 用户 2026-11-01 指定纯 P",
        fontsize=9.2, color=WARN, ha="center")

fig.savefig("控制框图.png", dpi=170, facecolor=BG, bbox_inches="tight",
            pad_inches=0.25)
print("已生成: 控制框图.png")
