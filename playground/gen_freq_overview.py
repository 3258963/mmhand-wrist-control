# -*- coding: utf-8 -*-
"""腕部控制链路频率全景图生成脚本（2026-10-31）。

数据来源：mmhand_scope.py / wrist_*.py / znsv_app/znsv.py / ESP32-P4 ServoBoardMain /
ESP32-S3 System 的代码实测与注释口径（★ = 实机实测值）。
重画：.venv\\Scripts\\python playground/gen_freq_overview.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

C_UP, C_DOWN, C_TEN = "#1b7f4d", "#d8481f", "#7b2d8b"
FILL = {"s": "#e8f5e9", "p4": "#e3f2fd", "pc": "#fff8e1", "ten": "#f6ebfa", "strip": "#f4f4f4"}
EDGE = {"s": "#4c8c5a", "p4": "#39679b", "pc": "#b08a2e", "ten": "#9a5cad", "strip": "#bbbbbb"}

fig, ax = plt.subplots(figsize=(16, 9.92), dpi=170)
ax.set_xlim(0, 100); ax.set_ylim(0, 62); ax.axis("off")


def box(x0, y0, x1, y1, text, kind, fs=9.4):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                                boxstyle="round,pad=0.25,rounding_size=0.8",
                                facecolor=FILL[kind], edgecolor=EDGE[kind],
                                linewidth=1.4, zorder=2))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
            fontsize=fs, color="#1a1a1a", linespacing=1.5, zorder=2)


def arrow(points, color, lw=2.0):
    for i in range(len(points) - 2):
        (xa, ya), (xb, yb) = points[i], points[i + 1]
        ax.plot([xa, xb], [ya, yb], color=color, lw=lw,
                solid_capstyle="round", zorder=3)
    (xa, ya), (xb, yb) = points[-2], points[-1]
    ax.add_patch(FancyArrowPatch((xa, ya), (xb, yb), arrowstyle="-|>",
                                 mutation_scale=17, color=color, lw=lw,
                                 shrinkA=0, shrinkB=0, zorder=3))


def alabel(x, y, s, color, fs=8.6, ha="center", va="center", rot=0):
    ax.text(x, y, s, fontsize=fs, color=color, ha=ha, va=va, rotation=rot,
            fontweight="bold",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.88, pad=1.2),
            zorder=4)


# ---------------- 标题 ----------------
ax.text(50, 60.2, "腕部控制链路 · 频率全景图（状态量更新 + 控制频率）",
        ha="center", va="center", fontsize=19, fontweight="bold")
ax.text(50, 57.5, "2026-10-31 · 绿=上行反馈   橙=下行命令   紫=张力链（独立串口）· "
                  "★=实机实测值 · 邮箱队列=深度1，只留最新快照",
        ha="center", va="center", fontsize=10, color="#555555")

ax.text(12, 55, "传感器 / 执行器", ha="center", fontsize=12.5, fontweight="bold", color="#2f5d3a")
ax.text(43, 55, "P4 固件（FreeRTOS 任务）", ha="center", fontsize=12.5, fontweight="bold", color="#2c4d75")
ax.text(81, 55, "PC 上位机 mmhand_scope.py", ha="center", fontsize=12.5, fontweight="bold", color="#7a5c17")

# ---------------- 左列：传感器 / 执行器 ----------------
box(1, 46, 23, 53,
    "S3 磁编码器 ×21\nEncodersTask 2ms = 500Hz 采样\nJ16=ROLL · J17=PITCH", "s")
box(1, 28, 23, 35,
    "飞特舵机 M27/28/29\n内部位置 PID（限速 4RPM）", "s")
box(1, 8, 23, 15.5,
    "ZNSV 变送器（8 通道称重）\n设备刷新 1280Hz · 波特 600000\nFTDI LatencyTimer=1", "s")

# ---------------- 中列：P4 固件 ----------------
box(29, 46, 57, 54,
    "HostCommTask 200Hz（5ms + RX 事件唤醒）\n"
    "上行：每流每 tick ≤1 帧转发（≤200Hz 封顶）\n"
    "下行：解帧 → 暂存 pending + RUN_DIRECT 事件", "p4")
box(30.5, 36, 43, 43,
    "S3CanRxTask 1kHz\ncanRxQueue 邮箱\n深度1·覆盖旧值", "p4", fs=8.8)
box(29, 20, 57, 32,
    "执行链 100Hz：SystemStateTask 命令提升\n"
    "→ servoTargetQueue 邮箱 → ServoBusTask 写 UART\n"
    "同步读反馈 → servoFeedback / Telemetry 邮箱（深度1）", "p4")

# ---------------- 右列：PC 上位机 ----------------
box(63, 46, 99, 54,
    "SerialRxThread（后台线程）\n解帧 → rx_queue · 下行 TX 统一写出", "pc")
box(63, 36, 99, 44,
    "_drain_queue 100Hz（每 tick ≤4000 帧）\n"
    "状态量落点 RingBuffer（120s）：\n"
    "enc_raw ~130-150Hz★ · ABS/单圈/遥测 ~100Hz", "pc")
box(63, 28.5, 99, 34.5,
    "J16/17 滤波链：中值5 + EMA α=0.05\n"
    "跟随 enc_raw 逐帧更新 → _enc_filt_raw\n（闭环每拍直接读滤波值）", "pc", fs=9.0)
box(63, 17, 99, 26.5,
    "闭环 _cl_tick 200Hz（QTimer 5ms · dt 实测 1~50ms）\n"
    "位置环 wrist_control_law：手填系数 / 模型前馈+R·e\n"
    "力控 PI wrist_force_law：张力 250Hz★ 反馈\n"
    "变更抑制：输出不变不发送 · 守卫每拍", "pc", fs=9.2)
box(63, 7, 99, 14.5,
    "张力链 ZnsvTransmitter 250Hz★\n"
    "_tension_last（守卫 / 力控）· τ=R·f 每拍\n"
    "_tension_hist 走势 600 帧 ≈ 2.4s", "pc", fs=9.0)

# ---------------- 上行箭头（绿） ----------------
arrow([(23, 49.5), (30.5, 40)], C_UP)
alabel(26.8, 44.6, "CAN 250Hz 批发（4ms/批）", C_UP, fs=8.2)
arrow([(36.75, 43), (36.75, 46)], C_UP)
alabel(37.4, 44.5, "最新快照转发", C_UP, fs=7.8, ha="left")
arrow([(57, 51), (63, 51)], C_UP)
alabel(60, 52.2, "USB 921600", C_UP, fs=8.2)
arrow([(45.5, 32), (45.5, 46)], C_UP)
alabel(44.6, 39, "反馈/遥测 100Hz", C_UP, fs=8.2, rot=90)
arrow([(23, 28.5), (29, 23)], C_UP)
alabel(24.6, 24.2, "同步读 100Hz", C_UP, fs=8.2)
arrow([(81, 46), (81, 44)], C_UP)
arrow([(81, 36), (81, 34.5)], C_UP)
arrow([(81, 28.5), (81, 26.5)], C_UP)

# ---------------- 下行箭头（橙） ----------------
arrow([(29, 26), (23, 31.5)], C_DOWN)
alabel(26.4, 29.6, "UART 写目标", C_DOWN, fs=8.2)
arrow([(50, 46), (50, 32)], C_DOWN)
alabel(50.8, 39.5, "命令提升", C_DOWN, fs=8.2, ha="left")
arrow([(63, 21), (59.5, 21), (59.5, 49), (57, 49)], C_DOWN)
alabel(58.6, 33, "命令 200Hz（变更抑制：不变不发）", C_DOWN, fs=8.2, rot=90)

# ---------------- 张力链（紫，独立串口） ----------------
arrow([(12, 8), (12, 5.5), (81, 5.5), (81, 7)], C_TEN)
alabel(46.5, 4.2, "张力链：PC 直连 COM23 · Modbus 轮询 250Hz★（TENSION_POLL_HZ）· "
                  "RTT≈2ms · 每帧 8 通道 → C1/C2/C3", C_TEN, fs=8.8)
arrow([(81, 14.5), (81, 17)], C_TEN)
alabel(81.9, 15.7, "张力 → 守卫/力控", C_TEN, fs=8.0, ha="left")

# ---------------- 底部要点条 ----------------
box(0.5, 0.3, 99.5, 3.6,
    "PC GUI 刷新：曲线 100Hz · 磁编/电机表格 60Hz · R·张力独立窗 60Hz · 参数监视窗 60Hz · "
    "闭环状态行 33Hz · 张力链路状态 1Hz · 码率标签 1Hz · PC→P4 心跳 2Hz(500ms) · 目标扫掠 20Hz\n"
    "频率关系：磁编 ~130-150Hz★ < 闭环 200Hz（约 1/3 拍无新反馈，取最新滤波值）· 张力 250Hz★ ≥ 200Hz（每拍有新样本）· "
    "P4 应用 100Hz → 命令龄 5~20ms · 反馈样本龄 >300ms → STALE 冻结",
    "strip", fs=9.2)

out = "wrist_freq_overview.png"
fig.savefig(out, bbox_inches="tight", facecolor="white")
print("saved:", out)
