"""MMHand 示波器 + 腕部直控上位机。

实时读取并绘制 P4 上传的全部磁编码器（J00-J20）与 M27-M29 舵机数据，
并提供 M27-M29 logical ABS 直控（使能自动归零+保持，点动/绝对目标/急停）。
每根绳一个使能开关（M27-M29 行首复选框，随布局持久化）：勾选的绳才会被
使能并接收命令；未勾选的绳使能不入活动域、点动/回零/闭环一律不下发。
连接时按 UPLINK_MASK 裁剪不需要的上行流以腾出带宽，断开时恢复全开。
CSV 由 mmhand_scope_export 模块固定导出到 run_data/scope_exports/。

运行（仓库根目录）:
    .venv\\Scripts\\python.exe mmhand_scope.py [--port COM13]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import queue
import struct
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# 可选运行遥测：设 MMHAND_TELEMETRY=<jsonl 路径> 时，每秒追加一行运行指标，
# 供 tools/perf/watch_scope.py 读取并画实时看板。不设环境变量 = 完全零开销、
# 不写任何文件（默认路径即此行为）。
TELEMETRY_PATH = (os.environ.get("MMHAND_TELEMETRY") or "").strip()

# 安全取证日志：每条运动命令/保护动作立即 flush 落盘（run_data/运行日志/safety_*.log）。
# 与 session_log 的区别：session_log 只在正常退出时写文件，进程被杀/断电就丢，
# 而事故复盘恰恰最需要最后几秒。MMHAND_SAFETY_LOG=0 可关闭。
SAFETY_LOG_ON = os.environ.get("MMHAND_SAFETY_LOG", "1") != "0"
_safety_log_path_cache: Path | None = None


def safety_log_path() -> Path:
    global _safety_log_path_cache
    if _safety_log_path_cache is None:
        folder = REPO_ROOT / "run_data" / "运行日志"
        folder.mkdir(parents=True, exist_ok=True)
        _safety_log_path_cache = folder / f"safety_{datetime.now():%Y%m%d}.log"
    return _safety_log_path_cache


def safety_log(action: str, **fields) -> None:
    """追加一行带毫秒时间戳的安全日志并立即落盘（失败静默，绝不影响控制）。"""
    if not SAFETY_LOG_ON:
        return
    try:
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        with open(safety_log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S.%f}"[:-3]
                     + f" [{action}] {detail}\n")
            fh.flush()
    except OSError:
        pass

import numpy as np
import serial
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QPlainTextEdit, QScrollArea
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFrame,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg
from pyqtgraph import ViewBox

# 曲线渲染方式（2026-11-03 两轮定案）：默认**软件光栅+33FPS 门**（实测稳定）。
# 全局 useOpenGL 在用户 Windows 机器上产生严重渲染伪影（两图 y 轴刻度叠印、
# 图区被残影横线铺满——GL 曲面与普通控件合成错位），已回滚。想试验 GL 时设
# 环境变量 MMHAND_GL=1（自担风险；GL 正常时主图自动升 100FPS）。
PLOT_GL_OK = False
if os.environ.get("MMHAND_GL") == "1":
    try:
        pg.setConfigOption("useOpenGL", True)
        pg.setConfigOption("enableExperimental", True)
        PLOT_GL_OK = True
        print("[plot] OpenGL 已按 MMHAND_GL=1 启用（实验性）")
    except Exception as exc:
        print(f"[plot] OpenGL 启用失败，回退软件光栅: {exc}")
# 主图帧率：默认 75FPS（数据链路 0.5ms + paint 实测最坏 13ms，预算够）。
# 数据源只有 100Hz（P4 控制周期 10ms），75~90 已经接近"一帧一个新点"，再往上
# 没有新数据可画，反而和 drain/表格定时器抢线程（实测把间隔压到 8ms/5ms，
# 帧率反掉到 ~57）。想省电可 MMHAND_PLOT_HZ=30。
# 2026-11-24：帧率不再只靠环境变量 —— 工具栏有「帧率」下拉（60/75/90），
# 见 _set_plot_hz()；这里的常量只是启动默认值。
# 曲线点数由 _adapt_density 按 paint 实测自适应，帧率不会被点数拖下来。
try:
    PLOT_HZ = float(os.environ.get("MMHAND_PLOT_HZ", "75"))
except ValueError:
    PLOT_HZ = 75.0
PLOT_HZ = max(5.0, min(120.0, PLOT_HZ))
PLOT_INTERVAL_MS = max(1, int(round(1000.0 / PLOT_HZ)))

# 全局主题（app_theme：夜间/白天/赛博朋克/自定义；工具栏可切，即时生效）
import app_theme as AT
# antialias 默认 **关**：实测（4 条 100Hz 曲线，原生窗口）+5.4ms/帧
# （paint 7.5→12.9ms），75FPS 预算下会掉帧。想要顺滑线条可勾工具栏
# 「抗锯齿」，见 _set_plot_aa()（会按需重建曲线项）。
pg.setConfigOptions(background=AT.T("plot_bg"), foreground=AT.T("plot_fg"),
                    antialias=False)

from desktop.core.communication.frame_decoder import FrameDecoder
from desktop.core.generated_upper_protocol import (
    CMD_UPLINK_MASK,
    PACKET_TYPE_ENCODER_RAW,
    PACKET_TYPE_FAULT_STATUS,
    PACKET_TYPE_PROTO_ACK,
    PACKET_TYPE_SERVO_ANGLE,
    PACKET_TYPE_SERVO_LOGICAL_RANGE,
    PACKET_TYPE_SERVO_RAW,
    PACKET_TYPE_SERVO_ROUTE_STATUS,
    PACKET_TYPE_SERVO_TELEM,
    PACKET_TYPE_SYSTEM_STATUS,
    P4_TIMESTAMP_BYTES,
    PROTOCOL_HEADER,
    PROTOCOL_TAIL,
    UPLINK_MASK_ALL_PERIODIC,
    UPLINK_MASK_ENCODER_RAW,
    UPLINK_MASK_SERVO_ANGLE,
    UPLINK_MASK_SERVO_RAW,
    UPLINK_MASK_SERVO_ROUTE,
    UPLINK_MASK_SERVO_TELEM,
)
from desktop.core.protocol import (
    DISCONNECT_SENTINEL,
    ENCODER_COUNT,
    SYSTEM_FAULT_OVERLOAD,
    SYSTEM_STATE_IDLE,
    SYSTEM_STATE_READY,
    SYSTEM_STATE_RECOVERY_REQUIRED,
    SYSTEM_STATE_RUN_DIRECT,
    SYSTEM_STATE_UNCONTROLLABLE,
    build_active_scope_cmd,
    build_reset_cmd,
    build_host_heartbeat_cmd,
    build_motor_pos_abs_cmd,
    build_servo_reset_zero_cmd,
    build_start_cmd,
    build_state_sync_request_cmd,
    build_stop_cmd,
    parse_fault_status_packet,
    parse_proto_ack,
    parse_servo_angle_packet,
    parse_servo_logical_range_packet,
    parse_servo_raw_packet,
    parse_servo_route_status_packet,
    parse_servo_telem_packet,
    parse_system_status_packet,
)
try:                                  # 状态同步位（生成的协议常量）
    from desktop.core.generated_upper_protocol import (
        STATE_SYNC_SERVO_LOGICAL_RANGE as _SYNC_LOGICAL_RANGE)
except Exception:                     # 老版本没有该常量时退回字面量 4（bit2）
    _SYNC_LOGICAL_RANGE = 4

# 示波器保留的上行流：映射角 + 舵机 ABS + 磁编 raw + 路由（状态/故障/安全事件不受掩码影响）。
SCOPE_UPLINK_MASK = (UPLINK_MASK_SERVO_ANGLE |
                     UPLINK_MASK_SERVO_TELEM | UPLINK_MASK_SERVO_RAW |
                     UPLINK_MASK_ENCODER_RAW | UPLINK_MASK_SERVO_ROUTE)
# 逐绳使能开关（2026-11-02）后活动域不再是固定 M27-29 全集：使能时按勾选
# 动态算掩码（ScopeWindow._enabled_motor_mask），故不再有模块级 MOTOR_SCOPE_MASK。
MOTOR_SOFT_LIMIT = 2000000  # counts 输出上界（≈int32 安全域，等效解除 ±5000；仅防溢出）
# 伺服可持续速度上限 [counts/s]：必须与固件 `SERVO_TARGET_SPEED_DEFAULT` 一致。
# 固件已从 1000 拉满到 **3400**（ServoConfig.h，2026-11-20），这里原来还写 1000，
# 导致「命令能力 vs 伺服能力」的告警按过时的数误判（2026-11-24 修正）。
#
# ⚠ 但这只是**天花板**，不是闭环能达到的速度。固件注释实测：
#   「闭环实际速度由『命令领先量 × 伺服内环』决定（领先 20c 时只有 ~267 c/s）」。
# 因为力控输出是增量式 `target = 实测 + 步长`，**实测每拍刷新**，所以舵机看到的
# 位置误差恒等于 `步长`。`max_step_f` 在本架构里充当的是**位置领先量**，
# 不是速度上限 —— 它决定"给舵机喂多大误差"，舵机按误差给速度：
#     v ≈ 13.35 × 领先量 [c/s]        （实测标定：20c → 267 c/s）
#   领先 10c  → ~133 c/s（≈6 N/s 张力斜率）→ 松绳起步会慢到像"推不动"
#   领先 20c  → ~267 c/s（≈12 N/s）
#   领先 30c  → ~400 c/s（≈18 N/s）
#   领先 120c → ~1600 c/s（≈74 N/s）
#   领先 255c → ~3400 c/s  ← **才真的打满固件天花板**（3400/13.35 ≈ 255）
# ⟹ **想让它跑快，`max_step` 要给到"比较大的值"**；给 34 只有 454 c/s。
# 代价是过冲 ≈ 张力斜率 × 延时(26 ms)，所以它是"快 ↔ 过冲"的单旋钮；
# 压过冲要靠 Kp/延时/速度前馈，不是靠把 max_step 压小。
# 详见 docs/每拍限幅_领先量与舵机速度_20261124.md。
SERVO_MAX_COUNTS_PER_S = 3400.0
# 闭环控制周期 [s]。
#
# 2026-11-20 用户选定 **100 Hz**（10 ms）：控制节拍与 P4 内环、舵机总线同拍。
# 力控输出是增量式的（`out = 实测 + 步长`），命令**不会**跑到实测前面。
#
# ⚠ 2026-11-24 更正：以前这里写着「乘法约束 max_step × 频率 ≤ 伺服 c/s」是**错的**，
# 那是把"领先量"当成了"速度"。按那条规则算出的 34 counts/拍，舵机只会跑 454 c/s。
# `max_step × 频率` 只是"若舵机能完全跟上"的假想速率，用来做**饱和提示**可以，
# 但不能当 `max_step` 的上限。真实速度见上面 13.35 c/s per count 的标定。
CL_LOOP_PERIOD_S = 0.010
# 力矩模式 α 的告警阈值（**只告警，不停环**）。
# 2026-11-23 用户定案：目标超能力时**始终给到可行最大**（α=m_max/k），不拒绝启动；
# α 小于本值时每秒提示一次"你填了多少、实际只有多少"。
# 安全由 `f > f_max` 过载停环负责。
ALPHA_WARN = 0.5
# 位姿超出力封闭域多少度就**停环**（2026-11-23）。
# 背景：现场 roll 读数 16.85°（可行域上限 +10°）被静默钳到 10° 继续控，
# 模型 R/n̂ 与真实几何不符 → 分配出的 f_d 错 → C3 被单独收到 30N+ 还在收。
# 钳制 >3° 就说明已经不在"能算准"的区域内，必须停下让用户摆回去。
POSE_CLAMP_STOP_DEG = 3.0
# 零空间份额下限（2026-11-23）。`n̂_i` 是第 i 根缆在"预紧"里能分到的比例；
# 靠近力封闭边界时某一根会趋近 0（实测 roll=−18.2° 时 n̂=[0.235,0.972,**0.002**]）。
# 这时那根缆**几乎无法承载预紧**：
#   · 分配要它 ≥ f_min=0.2N ⟹ t 得抬到 0.2/0.002 = 100 N ⟹ 其它缆爆掉 ⟹ 无解
#   · 就算有解，它也会被"永远收不满"→ 现场表现为**一直收绳**
# 所以在分配之前先判"病态"，直接停下并告诉用户把腕摆离边界。
FORCE_NULL_MIN_SHARE = 0.05
# 分配层给 f_max 留的余量（2026-11-23）。f_d 不再顶到 f_max 天花板：
# 现场某边界位姿下，目标力矩把 C3 分到正好 25.00 N，内环一次正常超调
# （实测 25.06~26.05）就触发"张力过载 ≥25N"停环，表现为"跑一会就自动停"。
# 留 min(1 N, 10% f_max) 给超调，真正的过载仍由守卫按 f_max 判。
FORCE_FMAX_HEADROOM_N = 1.0
# 力矩修正（慢积分外环）的修正量上限 [N·m]（2026-11-24）。
# 意义：`τ_cmd = τ* + trim`，`|trim| ≤ 本值`。取 0.3 大约是本机最强方向（1.44）的 21%、
# 最弱方向（0.43）的 70% —— 足够补"内环到不了"的差距，又不会把目标推到能力之外。
TAU_TRIM_MAX = 0.3
# 过载停环的去抖拍数（2026-11-23）：连续 N 拍超 f_max 才停。
# 目标贴着 f_max 时单拍超调（25.06 N）不应停环；真过载会持续 >30 ms。
OVERLOAD_STOP_TICKS = 3
# ---------- 张力链（ZNSV6-F8-485 八通道称重变送器，驱动 znsv_app/znsv.py） ----------
# 逻辑通道号(1..8) → C1/C2/C3。2026-10-28 用户实机确认：C1↔CH1、C2↔CH2、
# C3↔CH3（原工程体检报告曾测得传感器落 CH1/5/7，以本次确认为准）。
# 拉绳复核工具（如再变）：.venv\Scripts\python znsv_app/channel_scan.py COM23 --watch
TENSION_CH_FOR_CABLE = (1, 2, 3)
# 电机号(按缆序 C1/C2/C3) → 拉该缆的电机。2026-11-02 用户实机确认为恒等映射
# （M27↔C1/M28↔C2/M29↔C3）——10-29"绳序互换"悬案就此关闭；若日后换接线，
# 改此一行即可（张力/张紧/力矩三模式的 trim 都按本映射出电机；trim_sign/k
# 只能表达方向符号，表达不了换序）。
MOTOR_FOR_CABLE = (27, 28, 29)
# 换算系数（每缆独立，按缆序 C1/C2/C3）：f_N = raw × 系数，受拉为正。
# C1 极性二次定案（2026-11-03 晚）：上午按"C1 符号反"报修把 C1 系数改正，
# 实机复核 C1 受拉仍读负 → 上午判断反了，**C1 与 C2/C3 同极性，三缆全负**
# （1 raw = 1 g，受拉 raw 为负）。挂砝码校准：新系数 = 期望读数 ÷ 当前读数
# × 现系数（逐缆各自校）。每缆独立元组架构保留——下次极性有变只改对应位。
TENSION_N_PER_RAW = (-0.00980665, -0.00980665, -0.00980665)
TENSION_MODBUS_ADDRESS = 1   # 变送器出厂默认从站地址
TENSION_POLL_HZ = 200.0     # 2026-11-25 晚 用户定案：**200 Hz**（250→100→200）。
                            # 周期 5 ms，样本年龄 ≤5 ms（平均 2.5 ms）；控制环 100 Hz
                            # 每拍必有新值。比 250 Hz 留 20% 余量（早先 250 Hz 下曾
                            # 出现回复被下一轮冲掉而丢帧），又不牺牲内环带宽。
                            # 一帧事务 0.75 ms @600000，带宽占用约 15%，余量充足。
# J16/J17 角度显示方向（-1 = 与磁编原始方向相反，按用户实测约定）。
AXIS_SIGN = {16: 1.0, 17: -1.0}   # J16=ROLL / J17=PITCH 方向（2026-11-23 用户要求改回）
# 界面 pitch ↔ 模型 pitch（+X 右手定则）的换算。
# 2026-11-23 曾按现场读数成对取反（+1 / −1）验证过，用户要求**改回原约定**：
# 界面角 = AXIS_SIGN[17]·raw，模型角 = 界面角（本常数 +1）。
# 若以后要翻 pitch 正方向：**两个一起改**（AXIS_SIGN[17] 与 PITCH_MODEL_SIGN 同时取反），
# 只改一个会让 R/l 与编码器错位、闭环变正反馈。
PITCH_MODEL_SIGN = 1.0
# 阻抗外环输出的 roll 符号（2026-11-23 台架：给正 roll 目标，腕往反方向走）。
# 只作用于**阻抗外环的最终 τ_roll**（弹簧 K·e、阻尼 D·ė、前馈 τ_ff 一起翻），
# 不影响位置环 / 张力 / 张紧 / 力矩四个模式。
# 放在这里而不是 `wrist_impedance.py`：该模块保持"UI 角度口径的纯函数"，
# 硬件方向约定统一由调用方（本文件）负责——与 MODEL_AXIS_SIGN 同款。
IMPEDANCE_ROLL_SIGN = -1.0


def pitch_model_deg(pitch_deg: float) -> float:
    """界面 pitch（用户看到/输入的角度）→ 模型 pitch（+X 右手定则）。"""
    return PITCH_MODEL_SIGN * pitch_deg


def pitch_ui_range() -> tuple:
    """界面 pitch 的可用范围（模型行程按 PITCH_MODEL_SIGN 镜像后的结果）。"""
    a = PITCH_MODEL_SIGN * RANGE_DEG[PITCH][0]
    b = PITCH_MODEL_SIGN * RANGE_DEG[PITCH][1]
    return (min(a, b), max(a, b))

# J16/J17 滤波链：中值5(砍EMI尖刺) + EMA低通(压宽带噪声)——实现抽出为
# wrist_filter.py（可移植模块），此处仅引用；设计依据见该模块 docstring。
from wrist_filter import FILTER_ALPHA, FILTER_MEDIAN_N, WristAxisFilter, unwrap_counts
from wrist_model import (FORCE_CLOSURE_ENVELOPE_PITCH_DEG,
                         FORCE_CLOSURE_ENVELOPE_ROLL_DEG, PITCH, RANGE_DEG,
                         ROLL, clamp_force_closure, positive_null_direction,
                         wrist_eval)
from znsv_app.widgets import Sparkline
from znsv_app.znsv import ZnsvTransmitter

# 一键松绳的每台放绳量（counts；方向由 trim_sign 决定，PLAN v8.2 D2）
RELEASE_COUNTS = 2500


def cable_state(v, fmin, fmax, stale=False, hyst=0.05):
    """单缆状态（chip/汇总共用，滞回一致——REVIEW P1-3）。返回 (state, html)。"""
    if stale or v is None or not math.isfinite(v):
        return "no_data", "<span style='color:#8b95a6'>\u26aa 无数据</span>"
    has_lo = fmin is not None and fmin > 0.0
    has_hi = fmax is not None and fmax > 0.0
    if has_hi and v > fmax + hyst:
        return "over", "<span style='color:#f87171;font-weight:700'>\U0001f534 过紧</span>"
    if has_lo and v < fmin - hyst:
        return "slack", "<span style='color:#fbbf24;font-weight:700'>\U0001f7e1 放松</span>"
    if not has_lo:
        return "normal", "<span style='color:#8b95a6'>— 未设 fmin</span>"
    return "normal", "<span style='color:#34d399;font-weight:700'>\U0001f7e2 正常</span>"


def rope_state(f_vals, fmin, fmax, recovery, hyst=0.05):
    """绳状态判定（PLAN v8.2 D6 / v8.3：纯函数，绝对张力，无停环权力）。

    Args:
        f_vals: 三缆张力 [N]（绝对值）；None/长度≠3 → no_data
        fmin/fmax: 有效阈值（fmin≤0=跳过下界判定；fmax 非法=跳过上界）
        recovery: 恢复模式标志（True 且无过紧时显示 recovering）
        hyst: 滞回 [N]，防边界抖动（fmin−hyst 以上不算放松等）

    Returns:
        (state, text)：state ∈ no_data/over/slack/recovering/normal/unset
    """
    if f_vals is None or len(f_vals) != 3:
        return "no_data", "⚪ 无数据"
    if any(not math.isfinite(v) for v in f_vals):
        return "no_data", "⚪ 无数据"          # NaN 不得当正常（P1-4）
    if (isinstance(fmin, (int, float)) and isinstance(fmax, (int, float))
            and fmin > 0.0 and fmax > 0.0 and fmax <= fmin):
        return "unset", "⚠ 阈值非法"          # fmax≤fmin（P1-4）
    has_lo = isinstance(fmin, (int, float)) and fmin > 0.0
    has_hi = isinstance(fmax, (int, float)) and fmax > 0.0
    if not has_lo and not has_hi:
        return "unset", "未设阈值"
    if has_hi and any(v > fmax + hyst for v in f_vals):
        return "over", "🔴 过紧"
    if has_lo and any(v < fmin - hyst for v in f_vals):
        return "slack", "🟡 放松"
    if recovery:
        return "recovering", "🟡 恢复中"
    if not has_lo:
        # 下界未启用：不能宣称"正常"（0N 也过）——2026-11-03 台架 BUG 修复
        return "normal", "🟢 正常（⚠未设 fmin，不判放松）"
    return "normal", "🟢 紧绳·正常"


def release_delta(trim_sign, counts=RELEASE_COUNTS):
    """逐台放绳方向（PLAN v8.2 D2）：delta_i = -counts × sign_i。

    sign=+1（counts↑⇒张力↑）→ delta=-counts（counts 减=放）；
    sign=−1 → delta=+counts（counts 增=放）。trim_sign 非法返回 None。"""
    if (not isinstance(trim_sign, (list, tuple)) or len(trim_sign) != 3
            or any(v not in (-1, 1) for v in trim_sign)):
        return None
    return [-int(counts) * int(s) for s in trim_sign]


def tighten_t_use(t_tgt_raw, t_min_ui, t_max_ui, t_min_req, t_max_allow):
    """一键紧绳的 t_use 计算+校验（PLAN v8.2 D3 / v8.3：条件式，空=跳过）。

    Returns:
        (t_use | None, 拒绝原因 | None)——t_use=None 即拒绝。
    """
    if t_min_ui > 0 and t_max_ui > 0 and t_max_ui <= t_min_ui:
        return None, f"tmin={t_min_ui:g} 必须 < tmax={t_max_ui:g}"
    t_use = float(t_tgt_raw)
    if t_min_ui > 0:
        t_use = max(t_use, t_min_ui)
    if t_max_ui > 0:
        t_use = min(t_use, t_max_ui)
    if t_use <= 0:
        return None, f"t_use={t_use:g} 必须 > 0"
    if t_use > 100:
        return None, "预紧上限 100N"
    if not (t_min_req <= t_use <= t_max_allow):
        return None, (f"t_use={t_use:g} 超出当前位姿可行域 "
                      f"[{t_min_req:.2f},{t_max_allow:.2f}]（UI t 界与 f 盒冲突）")
    return t_use, None


def CHC(i: int) -> str:
    """C{i+1} 缆分类色（随主题）。"""
    return AT.T("channels")[i]
from wrist_tension import (TENSION_OVERLOAD, TENSION_SLACK, TENSION_STALE,
                           TensionConfig, tension_evaluate)
import wrist_autotune as wrist_autotune
import wrist_hybrid_autotune as hybrid_autotune
from wrist_force_law import (D_TERM_MAX_FRAC, F_SENSOR_MIN_N, FORCE_OK,
                              FORCE_NO_NULL,
                              FORCE_OVERLOAD, FORCE_SENSOR_FAULT,
                              FORCE_STALE, FORCE_TDA_INFEASIBLE, STALE_MS,
                              WristForceV2Params, WristForceV2State,
                              WristTensionParams, WristTensionState,
                              WristTightParams,
                              parse_per_cable, sine_target_step,
                              tau_trim_step, tension_i_term_lim_counts,
                              wrist_force_v2_step, wrist_tension_step)
from wrist_hybrid_control import (C1TensionParams, C1TensionState, HybridWristParams,
                                  c1_tension_target, coupling_ratios)
from wrist_tension_observer import TensionEstimatePanel
from wrist_impedance import (IMP_NO_TARGET, IMP_OK, IMP_TAU_CLAMPED,
                             RateFilter, WristImpedanceParams,
                             gravity_tau_sine, wrist_impedance_torque)
from wrist_tda import (TDA_INFEASIBLE, TDA_NO_NULL, TDA_PRELOAD_INFEASIBLE,
                       allocation_step, capacity_closed_form, preload_window,
                       tda_solve, torque_capacity)
DIRECT_REJECT_NAMES = {
    0: "无", 1: "状态不允许", 2: "硬件不可控", 3: "多圈未知",
    4: "事件队列满", 5: "命令过期", 6: "系统故障",
}
from mmhand_scope_export import (EXPORT_DIR, dump_csv, load_layout_json,
                                 load_named_json, safe_export_path,
                                 save_layout_json, save_named_json)
from wrist_control_law import (FLAG_FEEDBACK_CLAMPED, FLAG_GEOM_INVALID,
                               FLAG_I_CLAMPED, FLAG_LOW_PITCH, FLAG_NONFINITE,
                               FLAG_TARGET_CLAMPED, K_NOMINAL_ABS, MODEL_AXIS_SIGN,
                               SPOOL_RADIUS_M, WristCalib, WristControlParams,
                               WristPidState,
                               parse_wrist_calib,
                               wrist_control_step_pid)

# 位置环状态行短名（控制律标志 → 用户可读）
CL_FLAG_NAMES = (
    (FLAG_TARGET_CLAMPED, "目标钳制"),
    (FLAG_LOW_PITCH, "低pitch区"),
    (FLAG_FEEDBACK_CLAMPED, "反馈越界"),
    (FLAG_GEOM_INVALID, "几何无效"),
    (FLAG_NONFINITE, "输入无效"),
    (FLAG_I_CLAMPED, "积分饱和"),
)

SERVO_TARGETS = [27, 28, 29]
BAUDRATE = 921600
BUFFER_SECONDS = 120
MAX_RATE_HZ = 160  # ENCODER_RAW 实测约 150Hz，取整留裕量
BUFFER_LEN = BUFFER_SECONDS * MAX_RATE_HZ

STATE_NAMES = {
    0: "UNCONTROLLABLE", 1: "IDLE", 2: "RUN_FEEDBACK", 4: "CALIBRATION_RUNNING",
    5: "READY", 6: "RUN_DIRECT", 7: "PAUSED", 8: "ROPE_INIT_RUNNING", 9: "RECOVERY_REQUIRED",
}

PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0",
    "#f032e6", "#bcf60c", "#fabebe", "#008080", "#9a6324", "#fffac8",
    "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]


class RelativeTimeAxis(pg.AxisItem):
    """X 轴：默认相对秒，可切换为绝对时间 HH:MM:SS。"""

    absolute = False

    def tickStrings(self, values, scale, spacing):
        if not self.absolute:
            return [f"{v:.1f}" for v in values]
        out = []
        for v in values:
            stamp = time.strftime("%H:%M:%S", time.localtime((SCOPE_WINDOW_T0 or time.time()) + v))
            out.append(stamp)
        return out


SCOPE_WINDOW_T0 = None


class RingBuffer:
    """预分配环形缓冲，存一路时间序列。"""

    def __init__(self, capacity: int = BUFFER_LEN):
        self.capacity = capacity
        self.t = np.full(capacity, np.nan)
        self.v = np.full(capacity, np.nan)
        self.head = 0  # 下一个写入位置
        self.count = 0

    def append(self, t: float, value: float) -> None:
        self.t[self.head] = t
        self.v[self.head] = value
        self.head = (self.head + 1) % self.capacity
        self.count = min(self.count + 1, self.capacity)

    def clear(self) -> None:
        self.t[:] = np.nan
        self.v[:] = np.nan
        self.head = 0
        self.count = 0

    def last(self) -> float:
        if self.count == 0:
            return math.nan
        idx = (self.head - 1) % self.capacity
        return float(self.v[idx])

    def last_sample(self) -> tuple[float, float]:
        if self.count == 0:
            return math.nan, math.nan
        idx = (self.head - 1) % self.capacity
        return float(self.t[idx]), float(self.v[idx])

    def series(self, tail_seconds: float) -> tuple[np.ndarray, np.ndarray]:
        """按时间倒取最近 tail_seconds 的数据，按时间升序返回。"""
        if self.count == 0:
            return self.t[:0], self.v[:0]
        if self.count < self.capacity:
            t_all, v_all = self.t[:self.head], self.v[:self.head]
        else:
            # 双段拼接比 roll 的索引重排少一次整块拷贝。
            t_all = np.concatenate((self.t[self.head:], self.t[:self.head]))
            v_all = np.concatenate((self.v[self.head:], self.v[:self.head]))
        t_end = t_all[-1]
        if not math.isnan(t_end):
            mask = t_all >= (t_end - tail_seconds)
            t_all, v_all = t_all[mask], v_all[mask]
        return t_all, v_all


def peak_decimate(t: np.ndarray, v: np.ndarray, max_pts: int):
    """保峰抽稀：每 bin 取 min/max 两点，NaN 用 fmin/fmax 保留断口。

    为什么必须自己抽：pyqtgraph 的 autoDownsample 发生在 paint 内部，而且
    每帧都要对**交给它的原始数组**做一遍裁剪/降采样（O(n)，与最终画出多少点
    无关）。120s 窗口 150Hz = 18000 点/曲线，20 条曲线每帧就是 36 万点的
    Python/NumPy 处理——实测 paint 27ms（37FPS）。在这里先抽到 ~2 点/像素，
    pyqtgraph 只需处理 ~1800 点，paint 降到 13ms 以下（>75FPS）。
    保峰（min/max 包络）保证不会把拉力尖峰、编码器跳变画丢。
    """
    n = t.size
    if n <= max_pts or max_pts < 4:
        return t, v
    step = int(math.ceil(n / max(2, max_pts // 2)))
    if step <= 1:
        return t, v
    m = (n // step) * step
    if m < step * 2:
        return t, v
    block_v = v[:m].reshape(-1, step)
    lo = np.fmin.reduce(block_v, axis=1)
    hi = np.fmax.reduce(block_v, axis=1)
    dt = (t[1] - t[0]) if n > 1 else 1.0
    tb = t[:m:step] + (step - 1) * 0.5 * dt
    x = np.repeat(tb, 2)
    y = np.empty(lo.size * 2, dtype=v.dtype)
    y[0::2] = lo
    y[1::2] = hi
    if m < n:                       # 余段原样接上，避免末尾掉点
        x = np.concatenate((x, t[m:]))
        y = np.concatenate((y, v[m:]))
    return x, y


class SerialRxThread(threading.Thread):
    """串口接收线程：解码帧并推送解析结果到队列。"""

    def __init__(self, port: str, out_queue: queue.Queue):
        super().__init__(daemon=True)
        self.port = port
        self.out_queue = out_queue
        self.stop_event = threading.Event()
        self.serial = None
        self.error = None
        # 所有下行字节经此队列由本线程统一写出，避免 GUI 线程直接写串口。
        self.tx_queue: queue.Queue = queue.Queue()
        # 急停专用抢占通道：不走 FIFO，_drain_tx 每次先写它。
        self.tx_priority: queue.Queue = queue.Queue()

    def send(self, data: bytes, priority: bool = False) -> bool:
        """把下行帧交给 RX 线程统一写出；priority=True 走急停抢占通道。

        为什么要抢占：STOP 原先和普通运动指令共用一条 FIFO，最坏要排在
        200 帧 0xD3 批量目标之后（约 280ms）才轮得到写出，急停就变成了"慢停"。
        """
        if self.stop_event.is_set():
            return False
        (self.tx_priority if priority else self.tx_queue).put(data)
        return True

    def drop_pending_tx(self) -> int:
        """丢弃尚未写出的普通下行帧（急停时先清队列，免得旧目标抢先落地）。"""
        dropped = 0
        while True:
            try:
                self.tx_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                return dropped

    def _drain_tx(self) -> None:
        while True:
            try:
                data = self.tx_priority.get_nowait()      # 急停优先
            except queue.Empty:
                try:
                    data = self.tx_queue.get_nowait()
                except queue.Empty:
                    return
            if self.serial is None:
                return
            try:
                if self.serial.write(data) != len(data):
                    self.out_queue.put(("error", "tx write incomplete"))
                    return
            except (serial.SerialException, OSError) as exc:
                self.out_queue.put(("error", f"tx failed: {exc}"))
                return

    def run(self) -> None:
        try:
            # 读超时 10ms：RX 线程每轮先 _drain_tx，急停等待上限由此决定
            # （原 50ms → 急停最坏要多等 50ms 才被写出）。
            self.serial = serial.Serial(port=self.port, baudrate=BAUDRATE, timeout=0.01)
        except serial.SerialException as exc:
            self.error = str(exc)
            self.out_queue.put(("error", str(exc)))
            return
        decoder = FrameDecoder(PROTOCOL_HEADER, PROTOCOL_TAIL)
        while not self.stop_event.is_set():
            self._drain_tx()
            try:
                chunk = self.serial.read(4096)
            except (serial.SerialException, OSError) as exc:
                self.out_queue.put(("error", str(exc)))
                break
            if not chunk:
                continue
            for packet_type, payload in decoder.feed(chunk):
                body = payload[:-P4_TIMESTAMP_BYTES] if len(payload) >= P4_TIMESTAMP_BYTES else payload
                self._dispatch(packet_type, body)
        # 退出前把已排队的下行（如断开时的恢复掩码/STOP）写完再关串口。
        self._drain_tx()
        try:
            self.serial.close()
        except Exception:
            pass

    def _dispatch(self, packet_type: int, body: bytes) -> None:
        now = time.monotonic()
        if packet_type == PACKET_TYPE_ENCODER_RAW and len(body) >= ENCODER_COUNT * 2:
            vals = [(body[i * 2] << 8) | body[i * 2 + 1] for i in range(ENCODER_COUNT)]
            # 断连哨兵按需求显示为 0；在线列的 ○/● 仍可区分真实零位与断连。
            vals = [0 if v == DISCONNECT_SENTINEL else v for v in vals]
            self.out_queue.put(("enc_raw", now, vals))
        elif packet_type == PACKET_TYPE_SERVO_ANGLE:
            angles = parse_servo_angle_packet(body)
            if angles:
                self.out_queue.put(("servo_abs", now, [angles[i] for i in SERVO_TARGETS]))
                self.out_queue.put(("servo_abs_all", now, angles))
        elif packet_type == PACKET_TYPE_PROTO_ACK:
            ack = parse_proto_ack(body)
            if ack:
                self.out_queue.put(("ack", now, list(ack)))
        elif packet_type == PACKET_TYPE_SERVO_ROUTE_STATUS:
            route = parse_servo_route_status_packet(body)
            if route:
                self.out_queue.put(("route", now, {
                    "scan_state": route["scan_state"],
                    "controllable_bitmap": route["controllable_bitmap"],
                    "valid_bitmap": route["valid_bitmap"],
                }))
        elif packet_type == PACKET_TYPE_SERVO_RAW:
            raws = parse_servo_raw_packet(body)
            if raws:
                self.out_queue.put(("servo_raw", now, [raws[i] for i in SERVO_TARGETS]))
        elif packet_type == PACKET_TYPE_SERVO_LOGICAL_RANGE:
            rng = parse_servo_logical_range_packet(body)
            if rng:
                bitmap, mins, maxs = rng
                self.out_queue.put(("servo_range", now, {
                    "bitmap": int(bitmap), "min": list(mins), "max": list(maxs),
                }))
        elif packet_type == PACKET_TYPE_SERVO_TELEM:
            telem = parse_servo_telem_packet(body)
            if telem:
                speeds, loads, currents, volts, temps = telem
                self.out_queue.put(("servo_telem", now, {
                    "speed": [speeds[i] for i in SERVO_TARGETS],
                    "load": [loads[i] for i in SERVO_TARGETS],
                    "current": [currents[i] for i in SERVO_TARGETS],
                    "volt": [volts[i] / 10.0 for i in SERVO_TARGETS],
                    "temp": [float(temps[i]) for i in SERVO_TARGETS],
                }))
        elif packet_type == PACKET_TYPE_FAULT_STATUS:
            fault = parse_fault_status_packet(body)
            if fault:
                mask, loads = fault
                self.out_queue.put(("overload", now, {
                    m: load for m, load in enumerate(loads) if mask & (1 << m)
                }))
        elif packet_type == PACKET_TYPE_SYSTEM_STATUS:
            st = parse_system_status_packet(body)
            if st:
                self.out_queue.put(("status", now, {
                    "state": st[0],
                    "control_enabled": st[1],
                    "owner": st[2],
                    "control_mode": st[3],
                    "faults": st[5],
                    "servo_online": st[12],
                    "encoder_online": st[13],
                    "can_online": st[14],
                    "multiturn_unknown": st[7],
                    # 活动域：0xD3 批量帧在固件里会与它求交（0xDE 单电机不查），
                    # 上位机必须核对，否则"只有活动域里那台动"。
                    "active_motor_mask": st[8] if len(st) > 8 else 0,
                    "pending_generation": st[32] if st[35] else None,
                    "applied_generation": st[33] if st[35] else None,
                    "direct_reject": st[34],
                }))


class Channel:
    """一个可绘制通道：名称 + 环形缓冲 + 曲线对象。"""

    def __init__(self, key: str, name: str, group: str):
        self.key = key
        self.name = name
        self.group = group
        self.color = "#ffffff"
        self.buf = RingBuffer()
        self.curve = None
        self.tree_item = None


# 观测台样式随主题生成：AT.build_dashboard_qss()（app_theme.py，切主题即时重建）。


class CableCard(QWidget):
    """观测台单缆卡：●C 标题 + CH 来源下拉 + 状态章 + 张力大字（状态着色）
    + 迷你走势 + 零点/去皮小按钮。（力臂/τ 行已删，R 矩阵卡有全表）"""

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("card")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(4)
        head = QHBoxLayout()
        title = QLabel(f'<span style="color:{CHC(index)}">●</span> C{index + 1}')
        title.setTextFormat(Qt.RichText)
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.ch_combo = QComboBox()
        self.ch_combo.addItems([f"CH{n}" for n in range(1, 9)])
        self.ch_combo.setFixedHeight(26)
        self.ch_combo.setMinimumWidth(64)
        head.addWidget(self.ch_combo)
        root.addLayout(head)
        # 逐缆状态章（PLAN v8.2 D6）：张力大字旁的显式状态（正常/放松/过紧）
        self.chip = QLabel("⚪ 无数据")
        self.chip.setTextFormat(Qt.RichText)
        head.insertWidget(1, self.chip)
        self.value = QLabel("--")
        self.value.setObjectName("bigValue")
        root.addWidget(self.value)
        # 力臂/τ贡献行已删（2026-11-03 用户要求：右侧只看张力，R 矩阵卡
        # 已有力臂全表，逐缆重复显示无必要）。
        self.spark = Sparkline(CHC(index))
        # 走势装进带底色边框的图框（2026-11-04 用户反馈"框不明显"）：
        # 原先一条细线浮在卡上没有边界感；QFrame 原生支持 QSS 背景边框。
        # spark_host 存到实例：取消「张力走势」时整框收起（只藏线会剩空框）。
        self.spark_host = QFrame()
        self.spark_host.setObjectName("sparkHost")
        spark_lay = QHBoxLayout(self.spark_host)
        spark_lay.setContentsMargins(4, 4, 4, 4)
        spark_lay.addWidget(self.spark)
        root.addWidget(self.spark_host, 1)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.zero_btn = QPushButton("零点")
        self.zero_btn.setObjectName("ghost")
        self.tare_btn = QPushButton("去皮")
        self.tare_btn.setObjectName("ghost")
        for b in (self.zero_btn, self.tare_btn):
            b.setFixedHeight(24)
            b.setToolTip("零点校准须空载，会覆盖该路标定；去皮随时可做")
            btns.addWidget(b)
        root.addLayout(btns)

    def set_row(self, value_html, hist):
        self.value.setText(value_html)
        self.spark.set_data(hist)

    def set_value(self, value_html):
        """只刷张力大字（走势隐藏时 _refresh 走这里，跳过 spark 绘制）。"""
        self.value.setText(value_html)


class RTensionWindow(QWidget):
    """张力 · R 观测台（2026-10-28 v2；2026-11-04 方案二改：选项卡两页）。

    页1「📊 张力·R」（日常主视图，数据全同屏——用户定案 R/绳长不得与张力分页）：
    - 左：R(θ) 力臂矩阵卡（位姿 + 2×3 表 + R(0°) 对照 + 绳状态徽章 + τ/t 汇总）
      + 绳长 l(θ) 卡（▸ 可折叠，状态随布局记住）。塞不下纵向滚动。
    - 右：三张缆卡（张力大字三态着色 + 走势 + CH 来源下拉 + 零点/去皮）。
    - 底：力状态曲线卡——τ 双向与 t **左右并排**一行（纵向只占 ~200px），
      全宽；「显示曲线」开关与 💾CSV 不变。
    页2「🔧 链路·CH」：CH1-8 原始条（放大版）+ 通道复核/零点-去皮语义提示，
    平时不看的信息收进这页，主视图让出全部纵向给数据。
    常驻底部：链路健康行（口/龄/超时/错帧/温度）。
    R 为几何力臂（wrist_model，mm），与 v1 手填系数（counts/°）无关。
    """

    def __init__(self, scope):
        super().__init__(scope)
        self.scope = scope
        self.setWindowTitle("张力 · R 观测台")
        # 最小高度 700（原 880，2026-11-04 小屏实报 BUG）：1366×768 笔记本可用
        # 高仅 ~700-720，880 最小窗本身就超出屏幕；配合曲线卡 420 纵向封顶，
        # 勾「显示曲线」不再把缆卡/R 矩阵数据挤出视野。
        self.setMinimumSize(1140, 700)
        # 首开尽量给到「全展开」高度（2026-11-04 实测 1023=R+绳长+曲线全见），
        # 屏幕不够就贴着可用高度（小屏回退到最小 700，可折叠绳长省高度）。
        _avail = QApplication.primaryScreen().availableGeometry()
        self.resize(1140, max(700, min(1023, _avail.height() - 16)))
        self.setWindowFlag(Qt.Window, True)
        self.setStyleSheet(AT.build_dashboard_qss())
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ---- 工具行：串口/波特/连接 + 守卫阈值 + 全部去皮 ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        w = self.scope
        w.tension_port_combo = QComboBox()
        for pn in w._list_ports():
            w.tension_port_combo.addItem(pn)
        # 默认张力串口：采集盒固定在 COM23
        _i23 = w.tension_port_combo.findText("COM23")
        if _i23 >= 0:
            w.tension_port_combo.setCurrentIndex(_i23)
        w.tension_port_combo.setMinimumWidth(96)
        bar.addWidget(QLabel("串口"))
        bar.addWidget(w.tension_port_combo)
        w.tension_baud_combo = QComboBox()
        for b in ("9600", "19200", "38400", "57600", "115200", "230400", "460800",
                  "500000", "512000", "600000"):
            w.tension_baud_combo.addItem(b)
        # 变送器已提速到 600000（掉电保持，znsv_app/rate_upgrade.py）；拨码 8 可强制回 115200
        w.tension_baud_combo.setCurrentText("600000")
        bar.addWidget(w.tension_baud_combo)
        # 串口号/波特率跨重启持久化：回填存档（端口须在当前列表内才生效）+
        # 选择实时镜像（控件每次重建，真身在 scope._tension_link_saved）。
        _sp = w._tension_link_saved.get("port", "")
        if _sp:
            _spi = w.tension_port_combo.findText(_sp)
            if _spi >= 0:
                w.tension_port_combo.setCurrentIndex(_spi)
        _sb = w._tension_link_saved.get("baud", "")
        if _sb:
            w.tension_baud_combo.setCurrentText(_sb)
        w.tension_port_combo.currentTextChanged.connect(
            lambda s: w._set_tension_link_saved("port", s))
        w.tension_baud_combo.currentTextChanged.connect(
            lambda s: w._set_tension_link_saved("baud", s))
        w.tension_btn = QPushButton("连接")
        w.tension_btn.setObjectName("primary")
        w.tension_btn.clicked.connect(w._toggle_tension_port)
        bar.addWidget(w.tension_btn)
        bar.addSpacing(14)
        bar.addWidget(QLabel("松绳N"))
        w.tension_fmin_edit = QLineEdit()
        w.tension_fmin_edit.setPlaceholderText("f_min")
        w.tension_fmin_edit.setFixedWidth(64)
        w.tension_fmin_edit.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhLatinOnly)
        bar.addWidget(w.tension_fmin_edit)
        bar.addWidget(QLabel("过载N"))
        w.tension_fmax_edit = QLineEdit()
        w.tension_fmax_edit.setPlaceholderText("f_max")
        w.tension_fmax_edit.setFixedWidth(64)
        w.tension_fmax_edit.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhLatinOnly)
        bar.addWidget(w.tension_fmax_edit)
        # 守卫阈值跨重启持久化：回填上次存档 + 输入实时镜像（控件每次重建，
        # 文本真身存 scope._tension_guard_saved，随布局 JSON 落盘）。
        w.tension_fmin_edit.setText(w._tension_guard_saved.get("f_min", ""))
        w.tension_fmax_edit.setText(w._tension_guard_saved.get("f_max", ""))
        w.tension_fmin_edit.textChanged.connect(
            lambda s: w._set_tension_guard_saved("f_min", s))
        w.tension_fmax_edit.textChanged.connect(
            lambda s: w._set_tension_guard_saved("f_max", s))
        bar.addStretch(1)
        # 张力走势开关（2026-11-04 用户需求）：缆卡迷你走势自选看不看。
        # 关=只刷张力大字（省 3×1500 点/60Hz 绘制），记录缓冲不受影响。
        self.trend_show = QCheckBox("张力走势")
        self.trend_show.setChecked(w._tension_trend_on)
        self.trend_show.setToolTip(
            "三张缆卡的迷你张力走势显示开关：\n"
            "关 = 只看张力大字（省 GUI 绘制开销），重新勾选即恢复；\n"
            "张力记录/守卫/CSV 均不受影响。选择随布局记住。")
        self.trend_show.toggled.connect(self._on_trend_show)
        bar.addWidget(self.trend_show)
        zero_btn = QPushButton("清零")
        zero_btn.setToolTip("把最新一帧张力记为本地零位：显示/走势变相对值\n（τ 与守卫仍用绝对张力，安全判定不受影响）")
        zero_btn.clicked.connect(w._tension_set_zero)
        bar.addWidget(zero_btn)
        clr_zero_btn = QPushButton("清除零位")
        clr_zero_btn.clicked.connect(w._tension_clear_zero)
        bar.addWidget(clr_zero_btn)
        all_tare = QPushButton("全部去皮")
        all_tare.setToolTip("八路同时去皮归零（0x0026 写 1，需确认）")
        all_tare.clicked.connect(w._tension_all_tare)
        bar.addWidget(all_tare)
        root.addLayout(bar)

        # ---- 主体（2026-11-04 方案二改）：选项卡两页 ----
        # 页1 张力·R：R 矩阵 + 绳长(可折叠) + 三缆卡 + τ/t 并排曲线全同屏
        # （用户定案：R/绳长不得与张力分页二选一）；页2 链路·CH 收 CH1-8
        # 原始条与链路提示，主视图让出全部纵向给数据。
        main_row = QHBoxLayout()
        main_row.setSpacing(12)
        left_col = QVBoxLayout()
        left_col.setSpacing(12)
        self.r_card = self._build_r_card()
        left_col.addWidget(self.r_card, 0)
        self._len_card = self._build_length_card()
        left_col.addWidget(self._len_card, 0)
        left_col.addStretch(1)
        left_host = QScrollArea()
        left_host.setWidgetResizable(True)
        left_host.setFrameShape(QFrame.Shape.NoFrame)
        left_host.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_inner = QWidget()
        left_inner.setLayout(left_col)
        left_host.setWidget(left_inner)
        main_row.addWidget(left_host, 0)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.cards = []
        for i in range(3):
            card = CableCard(i)
            card.ch_combo.setCurrentIndex(w._tension_ch_map[i] - 1)
            card.ch_combo.currentIndexChanged.connect(
                lambda ch, idx=i: w._set_tension_ch_map(idx, ch + 1))
            card.zero_btn.clicked.connect(
                lambda _=False, idx=i: w._tension_zero_ch(w._tension_ch_map[idx]))
            card.tare_btn.clicked.connect(
                lambda _=False, idx=i: w._tension_tare_ch(w._tension_ch_map[idx]))
            self.cards.append(card)
            cards.addWidget(card, 1)
        self._apply_trend_visible()   # 按持久化开关初始化走势可见性
        main_row.addLayout(cards, 1)
        # 力状态曲线卡：页1 底部全宽，τ/t 左右并排一行（纵向只占 ~200px）。
        self.force_curve_card = self._build_force_curve_card()

        page1 = QWidget()
        p1 = QVBoxLayout(page1)
        p1.setContentsMargins(2, 10, 2, 0)
        p1.setSpacing(12)
        p1.addLayout(main_row, 3)
        p1.addWidget(self.force_curve_card, 2)

        # 页2：CH1-8 原始（放大）+ 链路/操作语义提示
        page2 = QWidget()
        p2 = QVBoxLayout(page2)
        p2.setContentsMargins(6, 12, 6, 0)
        p2.setSpacing(10)
        self.ch_strip = QLabel("CH1-8 raw：未连接")
        self.ch_strip.setObjectName("muted")
        self.ch_strip.setTextFormat(Qt.RichText)
        self.ch_strip.setWordWrap(True)
        self.ch_strip.setStyleSheet("font-size: 14px;")
        p2.addWidget(self.ch_strip)
        ch_hint = QLabel(
            "通道复核（换接线/疑映射有变时）：\n"
            ".venv\\Scripts\\python znsv_app\\channel_scan.py COM23 --watch\n\n"
            "三层『清零』语义：清零=仅上位机显示相对值；去皮=变送器侧归零"
            "（改绝对读数，力控运行时勿随手去皮）；零点校准=覆盖该路标定（须空载）。")
        ch_hint.setObjectName("muted")
        ch_hint.setWordWrap(True)
        p2.addWidget(ch_hint)
        p2.addStretch(1)

        self.tabs = QTabWidget()
        self.tabs.addTab(page1, "📊 张力 · R")
        self.tabs.addTab(page2, "🔧 链路 · CH")
        self.estimate_panel = TensionEstimatePanel(w)
        self.tabs.addTab(self.estimate_panel, "张力预估")
        root.addWidget(self.tabs, 1)

        # 常驻底部：链路健康行
        w.tension_status = QLabel("张力：未连接（阈值须实测给定，不设默认）")
        w.tension_status.setObjectName("muted")
        w.tension_status.setWordWrap(True)
        root.addWidget(w.tension_status)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        # 60Hz 拉满：单次 _refresh 实测 0.03–0.2ms，60Hz 也只占 GUI 线程个位数百分比。
        # （之前设的 20Hz 是给「降档」留的余量，现在改成按需降，见 _apply_run_prio）
        self._timer.start(16)

    def _on_trend_show(self, on: bool) -> None:
        """缆卡张力走势开关：只控可见性/绘制；张力记录、守卫、数值刷新不受影响。"""
        self.scope._tension_trend_on = on
        self._apply_trend_visible()
        self.scope._save_layout()

    def _apply_trend_visible(self) -> None:
        for card in self.cards:
            # 藏整框（spark_host）而非只藏线：只藏线会在卡上剩一个空图框。
            card.spark_host.setVisible(self.trend_show.isChecked())

    def closeEvent(self, ev):
        """关窗唯一出口：按钮、右上角 X、主窗级联关闭都走这里。

        2026-11-03 泄漏根修之二：只在 _toggle_* 里停表不够——用户点 X 时 Qt 只
        hide()，隐藏窗的 60Hz 定时器继续跑，每开关一轮永久多一个（探针实测：
        X 关 3 轮 → 活动定时器 6→9，实例 3→6）。这里统一停表 + 释放 scope 侧
        控件引用（各消费点已有 None 守卫）+ 销毁实例。
        """
        self._timer.stop()
        w = self.scope
        if getattr(w, "rt_window", None) is self:
            w.rt_window = None
            w.tension_btn = None
            w.tension_status = None
            w.tension_fmin_edit = None
            w.tension_fmax_edit = None
        self.deleteLater()
        super().closeEvent(ev)

    # ---------- R 矩阵卡（主角） ----------
    def _build_r_card(self):
        card = QWidget()
        card.setObjectName("card")
        card.setFixedWidth(400)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(6)

        head = QHBoxLayout()
        title = QLabel("R(θ) 力臂矩阵 · mm")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.pose_label = QLabel("@ --")
        self.pose_label.setStyleSheet(
            f"color:{AT.T('accent2')}; font-family:'{AT.MONO_FAMILY}'; font-size:13px; font-weight:600;")
        head.addWidget(self.pose_label)
        box.addLayout(head)

        # 位姿大字（扫掠时单窗看全"角度→力臂→张力→力矩"因果链）
        pose_row = QHBoxLayout()
        self.pose_roll = QLabel("ROLL  --")
        self.pose_pitch = QLabel("PITCH --")
        for lbl in (self.pose_roll, self.pose_pitch):
            lbl.setStyleSheet(
                f"font-family:'{AT.MONO_FAMILY}'; font-size:17px; font-weight:700;"
                f"color:{AT.T('accent2')};")
            pose_row.addWidget(lbl)
        pose_row.addStretch(1)
        box.addLayout(pose_row)

        grid = QGridLayout()
        grid.setSpacing(2)
        grid.setContentsMargins(4, 6, 4, 6)
        for col in range(3):
            cap = QLabel(f'<span style="color:{CHC(col)}">●</span> C{col + 1}')
            cap.setTextFormat(Qt.RichText)
            cap.setAlignment(Qt.AlignCenter)
            cap.setObjectName("muted")
            grid.addWidget(cap, 0, col + 1)
        self.r_cells = []
        # 行标签按轴着色（ROLL=accent 蓝 / PITCH=good 绿，粗体）：白天亮环境可读，
        # 与缆卡力臂/τ 行、主面板大字的分轴配色一致。
        for row, (axis, ax_color) in enumerate(
                (("ROLL", AT.T("accent")), ("PITCH", AT.T("good")))):
            lab = QLabel(axis)
            lab.setStyleSheet(f"color:{ax_color}; font-weight:700;")
            grid.addWidget(lab, row + 1, 0)
            cells = []
            for col in range(3):
                cell = QLabel("--")
                cell.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setStyleSheet(
                    f"font-family:'{AT.MONO_FAMILY}'; font-size:16px;"
                    f"color:{AT.T('text')}; padding:4px 10px;")
                grid.addWidget(cell, row + 1, col + 1)
                cells.append(cell)
            self.r_cells.append(cells)
        box.addLayout(grid)

        self.r_ref = QLabel(" ")
        self.r_ref.setObjectName("muted")
        self.r_ref.setWordWrap(True)
        box.addWidget(self.r_ref)

        line = QLabel("─" * 44)
        line.setObjectName("muted")
        box.addWidget(line)

        tau_cap = QLabel("<b>力状态 = P·f（两个方向的力矩 + 张紧程度 t）</b>")
        box.addWidget(tau_cap)
        # 绳状态徽章 + 汇总行（PLAN v8.2 D6/D7：纯显示，15Hz 节流）
        self.rope_badge = QLabel("⚪ 无数据")
        self.rope_badge.setTextFormat(Qt.RichText)
        self.rope_badge.setStyleSheet("font-size:15px; padding:1px 0;")
        box.addWidget(self.rope_badge)
        self.rope_summary = QLabel(" ")
        self.rope_summary.setObjectName("muted")
        box.addWidget(self.rope_summary)
        self._rope_frame = 0
        # τ 与 t 分两行（2026-11-04 截图复核：|τ|>100 mN·m 时三项挤一行会被
        # 400px 卡宽裁尾，"−174.2 mN·m" 显示成 "−174."）。
        tau_row = QHBoxLayout()
        self.tau_roll = QLabel("--")
        self.tau_pitch = QLabel("--")
        for cap, lbl, color in (("τ ROLL", self.tau_roll, AT.T("accent")),
                                ("τ PITCH", self.tau_pitch, AT.T("good"))):
            cap_lbl = QLabel(f"<span style='color:{AT.T('muted')}'>{cap}</span>")
            tau_row.addWidget(cap_lbl)
            lbl.setStyleSheet(
                f"font-family:'{AT.MONO_FAMILY}'; font-size:16px;"
                f"font-weight:700; color:{color};")
            tau_row.addWidget(lbl)
            tau_row.addSpacing(12)
        tau_row.addStretch(1)
        box.addLayout(tau_row)
        t_row = QHBoxLayout()
        self.preload = QLabel("--")
        t_cap = QLabel(f"<span style='color:{AT.T('muted')}'>张紧 t</span>")
        t_row.addWidget(t_cap)
        self.preload.setStyleSheet(
            f"font-family:'{AT.MONO_FAMILY}'; font-size:16px;"
            f"font-weight:700; color:{CHC(0)};")
        t_row.addWidget(self.preload)
        t_row.addSpacing(12)
        t_row.addStretch(1)
        box.addLayout(t_row)
        # t 的三缆分配（几何唯一分法 f_preload = t·n̂，随位姿实时变）
        self.t_alloc = QLabel(" ")
        self.t_alloc.setObjectName("muted")
        self.t_alloc.setWordWrap(True)
        box.addWidget(self.t_alloc)
        box.addStretch(1)
        note = QLabel("力臂 = −∂l/∂θ，随位姿实时变化；R(0°) 为模型零位参考")
        note.setObjectName("muted")
        box.addWidget(note)
        return card

    # ---------- 力状态曲线卡（τ 双向 + 张紧 t，pyqtgraph 带坐标轴 + CSV 导出） ----------
    def _build_force_curve_card(self):
        card = QWidget()
        card.setObjectName("card")
        # 不再 setFixedWidth(520)：2026-11-04 移到底部全宽，吃满窗口横向空间。
        # 纵向封顶动态切（见 _on_force_plot_show）：显示=280（两图并排 ~230 起，
        # 且默认即显示），隐藏=110——隐藏时若仍 280，stretch 会给空卡白留
        # 170px（2026-11-04 实测发现）。
        card.setMaximumHeight(280)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("<b>力状态曲线（τ 双向 + 张紧 t）</b>"))
        self.force_plot_show = QCheckBox("显示曲线")
        self.force_plot_show.setToolTip(
            "默认开（2026-11-04 用户定案：观测台默认全展开）；\n"
            "取消勾选=数据照常 60Hz 记录（💾CSV 全量可导），只是不画图省 GUI，\n"
            "且空卡收缩（280→110px）把纵向还给数据区。")
        self.force_plot_show.setChecked(True)
        cap_row.addStretch(1)
        cap_row.addWidget(self.force_plot_show)
        box.addLayout(cap_row)

        fg = AT.T("plot_fg") if AT.T("plot_fg") else AT.T("text")
        def _mk_plot(y_name):
            plt = pg.PlotWidget()
            plt.setBackground("transparent")
            plt.setMouseEnabled(x=True, y=True)
            plt.showGrid(x=True, y=True, alpha=0.25)
            plt.setLabel("left", y_name)
            plt.setLabel("bottom", "时间", units="s")
            # 渲染减压：峰值降采样（clipToView 已撤——与手动 setXRange 组合在
            # 边界帧有裁剪边角，参与"显示不全"）。抗锯齿跟随主图开关。
            pi = plt.getPlotItem()
            pi.setDownsampling(mode="peak")
            plt.setAntialiasing(pg.getConfigOption("antialias"))
            for ax in ("left", "bottom"):
                plt.getAxis(ax).setPen(fg)
                plt.getAxis(ax).setTextPen(fg)
            return plt

        # 图 1：τ 双向（同单位 mN·m 共轴，双色）
        self._tau_plot = _mk_plot("τ  mN·m")
        self._tau_c_roll = self._tau_plot.plot(
            pen=pg.mkPen(AT.T("accent"), width=2), name="ROLL")
        self._tau_c_pitch = self._tau_plot.plot(
            pen=pg.mkPen(AT.T("good"), width=2), name="PITCH")
        self._tau_plot.addLegend(offset=(8, 8))
        self._tau_plot.setMinimumHeight(110)
        # 图 2：张紧 t（N）——与 τ **左右并排**一行（方案二改，2026-11-04）：
        # 纵向只占一张图的高度，小屏不再被两图叠放吃掉。
        self._t_plot = _mk_plot("t  N")
        self._t_curve = self._t_plot.plot(pen=pg.mkPen(AT.T("accent2"), width=2))
        self._t_plot.setMinimumHeight(110)
        plots_row = QHBoxLayout()
        plots_row.setSpacing(10)
        plots_row.addWidget(self._tau_plot, 3)
        plots_row.addWidget(self._t_plot, 2)
        box.addLayout(plots_row)
        # 手动开关（默认开=全展开定案）：数据始终入缓冲，取消勾选只停绘制。
        self.force_plot_show.toggled.connect(self._on_force_plot_show)

        # 数据行缓冲：(t_rel, τR, τP, t)，缺量记 NaN；60s @60Hz
        self._force_rows = deque(maxlen=3600)
        self._force_t0 = None
        self._force_plot_frame = 0

        btn_row = QHBoxLayout()
        exp_btn = QPushButton("💾 导出 CSV")
        exp_btn.clicked.connect(self._export_force_rows)
        btn_row.addWidget(exp_btn)
        diag_btn = QPushButton("🔬 诊断 CSV")
        diag_btn.setToolTip(
            "导出 20 Hz 诊断数据到 run_data/scope_exports/：\n"
            "· 位置模式 → diag_pos_*.csv（角度/目标角/下发 counts/实测 counts，调 PID 用）\n"
            "· 力控/张力 → diag_*.csv（位姿 + 三缆张力 + τ + 预紧 + 下发 trim）\n"
            "缓冲约 25 分钟；每次起环清空。")
        diag_btn.clicked.connect(lambda: self.scope._export_diag_csv())
        btn_row.addWidget(diag_btn)
        btn_row.addStretch(1)
        note = QLabel("左键拖动=平移/滚轮=缩放（坐标可读）；自动跟随最近 30s；"
                      "缓冲 60s；NaN=该帧无 n̂/位姿")
        note.setObjectName("muted")
        note.setWordWrap(True)
        btn_row.addWidget(note, 1)
        box.addLayout(btn_row)
        return card

    def _on_force_plot_show(self, on: bool) -> None:
        """显示曲线开关：只控可见性（数据记录/CSV 不受影响）；同时动态切卡
        高度封顶（显示=280 / 隐藏=110），隐藏时不给空卡留 170px 白空间。"""
        self._tau_plot.setVisible(on)
        self._t_plot.setVisible(on)
        self.force_curve_card.setMaximumHeight(280 if on else 110)

    def _export_force_rows(self):
        """力状态历史导出 CSV（t_s, τR, τP, t；NaN 行由 csv 写空）。

        2026-11-20 修：`dump_csv` 会自己前置一列 `t_s`，这里**不能**再写 `t_s`，
        否则表头多一列、各列名整体右移一格（曾导致"τ_roll 读到 τ_pitch"的误判）。
        """
        rows = list(self._force_rows)
        if len(rows) < 2:
            if getattr(self.scope, "tension_status", None) is not None:
                self.scope.tension_status.setText("力状态：还没有数据可导出")
            return
        name = "force_status_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        path = dump_csv(
            name,
            header=["tau_roll_mNm", "tau_pitch_mNm", "tight_t_N"],
            t=[r[0] for r in rows],
            columns=[[r[1] for r in rows], [r[2] for r in rows],
                     [r[3] for r in rows]])
        msg = (f"力状态：已导出 {len(rows)} 行 → {name}"
               if path else "力状态：导出失败（路径校验不过）")
        if getattr(self.scope, "tension_status", None) is not None:
            self.scope.tension_status.setText(msg)

    def _update_force_plots(self, t_rel, tau_r, tau_p, t_v) -> None:
        """每帧压一行历史；重绘 20Hz（GL 后可承受；数据仍 60Hz 全量入缓冲，
        CSV 导出不受影响）。"""
        self._force_rows.append((t_rel,
                                 tau_r if tau_r is not None else math.nan,
                                 tau_p if tau_p is not None else math.nan,
                                 t_v if t_v is not None else math.nan))
        self._force_plot_frame += 1
        if self._force_plot_frame % 3:
            return
        if not self.force_plot_show.isChecked():
            return                      # 关=只记录不画（CSV 全量不受影响）
        arr = np.array(self._force_rows)
        t_x = arr[:, 0]
        self._tau_c_roll.setData(t_x, arr[:, 1])
        self._tau_c_pitch.setData(t_x, arr[:, 2])
        self._t_curve.setData(t_x, arr[:, 3])
        # 显示不全根修（2026-11-03）：NaN 行（无位姿/无 n̂）会毒化 Y autorange
        # （min/max 变 NaN → 轴废）→ 改手动算有限值范围并加 10% 余量。
        for plt, cols in ((self._tau_plot, (1, 2)), (self._t_plot, (3,))):
            vb = plt.getViewBox()
            vb.disableAutoRange(axis=ViewBox.XAxis)
            vb.setXRange(max(0.0, t_x[-1] - 30.0), max(30.0, t_x[-1]),
                         padding=0)
            vb.disableAutoRange(axis=ViewBox.YAxis)
            vals = arr[:, cols].ravel()
            vals = vals[np.isfinite(vals)]
            if vals.size:
                lo, hi = float(vals.min()), float(vals.max())
                pad = max((hi - lo) * 0.1, 1e-6)
            else:
                lo, hi, pad = 0.0, 1.0, 0.0
            vb.setYRange(lo - pad, hi + pad, padding=0)

    # ---------- 绳长卡（每缆 ROLL 段 / PITCH 段 / 合计 / Δ vs 零位；▸ 可折叠） ----------
    def _build_length_card(self):
        card = QWidget()
        card.setObjectName("card")
        card.setFixedWidth(400)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 10, 16, 12)
        box.setSpacing(6)
        head = QHBoxLayout()
        self.len_fold_btn = QPushButton("▾")
        self.len_fold_btn.setFixedSize(28, 22)
        self.len_fold_btn.setToolTip("折叠/展开绳长表（状态随布局记住）")
        self.len_fold_btn.clicked.connect(self._on_len_fold)
        head.addWidget(self.len_fold_btn)
        title = QLabel("绳长 l(θ) · mm")
        title.setObjectName("cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        box.addLayout(head)

        # 表体整体收进 _len_body：折叠=只留标题行（方案二改，2026-11-04）。
        self._len_body = QWidget()
        body = QVBoxLayout(self._len_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        note = QLabel("每绳 = ROLL段(θr) + PITCH段(θp)")
        note.setObjectName("muted")
        body.addWidget(note)

        grid = QGridLayout()
        grid.setSpacing(2)
        grid.setContentsMargins(4, 6, 4, 6)
        for col, cap in enumerate(("ROLL段", "PITCH段", "两段合计", "Δ vs 0°")):
            lab = QLabel(cap)
            lab.setObjectName("muted")
            lab.setAlignment(Qt.AlignCenter)
            grid.addWidget(lab, 0, col + 1)
        self.len_cells = []   # [缆][列] -> QLabel
        for i in range(3):
            clab = QLabel(f'<span style="color:{CHC(i)}">●</span> C{i + 1}')
            clab.setTextFormat(Qt.RichText)
            grid.addWidget(clab, i + 1, 0)
            cells = []
            for col in range(4):
                cell = QLabel("--")
                cell.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setStyleSheet(
                    f"font-family:'{AT.MONO_FAMILY}'; font-size:14px;"
                    f"color:{AT.T('text')}; padding:3px 8px;")
                grid.addWidget(cell, i + 1, col + 1)
                cells.append(cell)
            self.len_cells.append(cells)
        body.addLayout(grid)

        self.len_ref = QLabel(" ")
        self.len_ref.setObjectName("muted")
        self.len_ref.setWordWrap(True)
        body.addWidget(self.len_ref)
        note2 = QLabel("绝对全长 = 两段合计 + 基线 cᵢ（模型给差分；前馈只用 Δl，正好是右列）")
        note2.setObjectName("muted")
        note2.setWordWrap(True)
        body.addWidget(note2)
        box.addWidget(self._len_body)
        self._apply_len_fold(self.scope._tension_len_folded)
        return card

    def _on_len_fold(self) -> None:
        """绳长卡折叠开关：只控可见性；状态镜像到 scope 并随布局落盘。"""
        folded = not self.scope._tension_len_folded
        self.scope._tension_len_folded = folded
        self._apply_len_fold(folded)
        self.scope._save_layout()

    def _apply_len_fold(self, folded: bool) -> None:
        self._len_body.setVisible(not folded)
        self.len_fold_btn.setText("▸" if folded else "▾")

    # ---------- 60Hz 刷新 ----------
    def _refresh(self):
        w = self.scope
        last = getattr(w, "_tension_last", None)
        fvals = last[1] if last is not None else None
        stale = last is None or (time.monotonic() - last[0]) * 1000.0 > 500.0
        fmin_eff, fmax_eff, _ok = w._effective_flimits()
        fmin = fmin_eff if fmin_eff > 0 else None
        fmax = fmax_eff

        # R(0°) 零位参考是常量（CAD 几何固定），60Hz 每帧算两次纯属浪费 → 实例缓存
        if getattr(self, "_ref_cache", None) is None:
            self._ref_cache = wrist_eval(0.0, 0.0)
        ref = ref_len = self._ref_cache

        pose = w._r_at_current()
        self.estimate_panel.refresh(pose)
        if pose is not None:
            roll_deg, pitch_deg, out, roll_rad, pitch_rad = pose
        else:
            roll_deg = pitch_deg = out = None

        # R 矩阵表（主角）：当前值 + 位姿 + R(0) 参考
        if pose is not None:
            self.pose_label.setText(f"@ {roll_deg:+.1f}° / {pitch_deg:+.1f}°")
            self.pose_roll.setText(f"ROLL {roll_deg:+6.2f}°")
            self.pose_pitch.setText(f"PITCH {pitch_deg:+6.2f}°")
            for row, ax in enumerate((ROLL, PITCH)):
                for col in range(3):
                    self.r_cells[row][col].setText(f"{out.r_m[ax][col] * 1000.0:+8.2f}")
            self.r_ref.setText(
                "R(0°)  roll [{:+7.2f} {:+7.2f} {:+7.2f}]  "
                "pitch [{:+7.2f} {:+7.2f} {:+7.2f}]".format(
                    *(ref.r_m[ROLL][i] * 1000.0 for i in range(3)),
                    *(ref.r_m[PITCH][i] * 1000.0 for i in range(3))))
        else:
            self.pose_label.setText("@ --")
            self.pose_roll.setText("ROLL  --")
            self.pose_pitch.setText("PITCH --")
            for row in range(2):
                for col in range(3):
                    self.r_cells[row][col].setText("--")
            self.r_ref.setText("R(θ)：等待 J16/J17 位姿（未归零或磁编无数据）")

        # 绳长表：ROLL 段 / PITCH 段 / 两段合计 / Δ vs 零位（Δ = 前馈用的 dl）
        if pose is not None:
            for i in range(3):
                sr = out.s_m[ROLL][i] * 1000.0
                sp = out.s_m[PITCH][i] * 1000.0
                dsum = ((out.s_m[ROLL][i] + out.s_m[PITCH][i])
                        - (ref_len.s_m[ROLL][i] + ref_len.s_m[PITCH][i])) * 1000.0
                texts = (f"{sr:8.2f}", f"{sp:8.2f}", f"{sr + sp:8.2f}", f"{dsum:+8.2f}")
                for cell, txt in zip(self.len_cells[i], texts):
                    cell.setText(txt)
            self.len_ref.setText(
                "l(0°) 两段合计  " + "   ".join(
                    f"C{i + 1}={(ref_len.s_m[ROLL][i] + ref_len.s_m[PITCH][i]) * 1000.0:6.2f}"
                    for i in range(3)))
        else:
            for i in range(3):
                for cell in self.len_cells[i]:
                    cell.setText("--")
            self.len_ref.setText("绳长：等待 J16/J17 位姿（未归零或磁编无数据）")

        # 缆卡
        for i, card in enumerate(self.cards):
            # CH 下拉与 scope 映射同步（外部恢复布局时）
            want = w._tension_ch_map[i] - 1
            if card.ch_combo.currentIndex() != want:
                card.ch_combo.blockSignals(True)
                card.ch_combo.setCurrentIndex(want)
                card.ch_combo.blockSignals(False)
            if fvals is None:
                card.set_row(f"<span style='color:{AT.T('dim')}'>--</span>", [])
                card.chip.setText("<span style='color:#8b95a6'>\u26aa 无数据</span>")
                continue
            v_abs = fvals[i]   # 阈值判定用绝对张力（守卫同口径）
            zero = w._tension_zero
            v = v_abs - (zero[i] if zero is not None else 0.0)   # 显示相对值
            if stale:
                color, tag = AT.T("dim"), "（旧）"
            elif fmax is not None and v_abs > fmax:
                color, tag = AT.T("bad"), "（过载）"
            elif fmin is not None and v_abs < fmin:
                color, tag = AT.T("warn"), "（松绳）"
            else:
                color, tag = AT.T("text"), ("（相对）" if zero is not None else "")
            value_html = (f"<span style='color:{color}'>{v:+7.2f} N</span>"
                          f"<span style='color:{AT.T('muted')};font-size:11px'>{tag}</span>")
            # 逐缆力臂/τ文本已删（用户 2026-11-03 要求），只画张力+章+走势
            if self.trend_show.isChecked():
                hist = w._tension_hist_disp[i]  # 显示缓冲已 1/5 抽稀（1500 点=30s）
                card.set_row(value_html, list(hist))
            else:
                card.set_value(value_html)      # 走势隐藏：只刷大字，省绘制
            # 逐缆状态章（REVIEW P0-1/P1-3 修复：stale 判无数据与徽章一致；
            # 三处判定统一走 cable_state 共享 0.05N 滞回）
            _st_c, _chip = cable_state(v_abs, fmin, fmax, stale)
            card.chip.setText(_chip)

        # τ 双向 + 张紧 t（力状态汇总）+ t 的三缆分配 + 曲线推数（同一份数值）
        tau_r_v = tau_p_v = t_v = None
        if fvals is not None and pose is not None:
            # **2026-11-23：观测台这块原来没做 roll 换号** → 显示的是模型系，
            # 与状态行/曲线（UI 系）反号。用户实测"C2 加、τ ROLL 减小"就是这个。
            # 现在统一走 `w._roll_tau_sign()`（界面「τ方向」可翻转），单位 mN·m。
            _s_r = w._roll_tau_sign()
            tau_r_v = _s_r * sum(out.r_m[ROLL][i] * fvals[i] for i in range(3)) * 1000.0
            tau_p_v = sum(out.r_m[PITCH][i] * fvals[i] for i in range(3)) * 1000.0
            self.tau_roll.setText(f"{tau_r_v:+8.1f} mN·m")
            self.tau_pitch.setText(f"{tau_p_v:+8.1f} mN·m")
            n = positive_null_direction(roll_rad, pitch_rad, out_model=out)
            if n is not None:
                t_v = sum(fvals[i] * n[i] for i in range(3))
                tb = w._t_bound_note()
                self.preload.setText(f"{t_v:6.2f} N" + (f"  {tb}" if tb else ""))
                self.t_alloc.setText(
                    "t 分配 = t·n̂（几何唯一分法，τ 不变）→ "
                    f"C1 {n[0]*100:.0f}% · C2 {n[1]*100:.0f}% · C3 {n[2]*100:.0f}%"
                    f"　即 t=5N 时 C1={5*n[0]:.2f} / C2={5*n[1]:.2f} / C3={5*n[2]:.2f} N")
            else:
                self.preload.setText("—")
                self.t_alloc.setText("该位姿无全正 n̂：t 不可定义（张紧模式不可用）")
        else:
            self.tau_roll.setText("--")
            self.tau_pitch.setText("--")
            self.preload.setText("--")
            self.t_alloc.setText(" ")

        # 绳状态徽章 + 汇总（15Hz 节流；阈值/恢复标志同源于 effective/控制）
        self._rope_frame += 1
        if self._rope_frame % 4 == 1:
            f_for_state = None if (fvals is None or stale) else fvals
            st, txt = rope_state(f_for_state, fmin_eff, fmax_eff,
                                 recovery=getattr(w, "_force_recovery", False))
            self.rope_badge.setText(f"<b>{txt}</b>")
            if f_for_state is None:
                self.rope_summary.setText(" ")
            else:
                sts = [cable_state(f_for_state[i], fmin, fmax, False)[0]
                       for i in range(3)]
                lo = [i for i in range(3) if sts[i] == "slack"]
                hi = [i for i in range(3) if sts[i] == "over"]
                ok = [i for i in range(3) if sts[i] == "normal"]
                self.rope_summary.setText(
                    "放松：{} ｜ 过紧：{} ｜ 正常：{}".format(
                        "、".join(f"C{i+1}" for i in lo) or "无",
                        "、".join(f"C{i+1}" for i in hi) or "无",
                        "、".join(f"C{i+1}" for i in ok) or "无"))

        # 力状态曲线（pyqtgraph 带轴）：每帧一行（缺量 NaN），隔帧刷图
        if self._force_t0 is None:
            self._force_t0 = time.monotonic()
        self._update_force_plots(time.monotonic() - self._force_t0,
                                 tau_r_v, tau_p_v, t_v)


        # CH1-8 原始条（映射通道着缆色）
        raws = getattr(w, "_tension_raws_last", None)
        if raws is not None:
            parts = []
            for ch in range(1, 9):
                if ch in w._tension_ch_map:
                    ci = w._tension_ch_map.index(ch)
                    parts.append(f"<span style='color:{CHC(ci)};"
                                 f"font-weight:600'>CH{ch} {raws[ch - 1]:+d}</span>")
                else:
                    parts.append(f"CH{ch} {raws[ch - 1]:+d}")
            self.ch_strip.setText("CH:   " + "   ".join(parts))
        else:
            self.ch_strip.setText("CH1-8 raw：未连接")


class WatchTile(QLabel):
    """参数块：右键删除。富文本两行（小灰标题 + 大值），无滚动。"""
    removed = None  # 由窗口注入回调

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton and self.removed is not None:
            self.removed(self.property("param_key"))


class ServoInfoWindow(QWidget):
    """舵机信息窗（2026-11-20）：每台电机的实时状态 + 会话逻辑行程。

    数据全部来自**已有上行**，不需要改固件：
      · `0x03 SERVO_ANGLE`  → ABS
      · `0x09 SERVO_RAW`    → 单圈 raw
      · `0x05 SERVO_TELEM`  → 速度/负载/电流/电压/温度
      · `0x13 SERVO_LOGICAL_RANGE` → 逻辑行程 min/max（点「读取行程」发 0xED 请求）
    **舵机 EEPROM 里的 P/D/I/力矩限制/加速度，目前协议没有读命令**（要改固件）。
    """

    COLS = ["电机", "ID", "在线", "ABS", "raw", "速度 c/s", "负载",
            "电流", "电压 V", "温度 ℃", "逻辑min", "逻辑max", "行程", "起点", "目标", "累计"]

    def __init__(self, scope):
        super().__init__(scope)
        self.scope = scope
        self.setWindowTitle("舵机信息（M27-M29）")
        self.setMinimumWidth(980)
        self.setWindowFlag(Qt.Window, True)
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        btn_read = QPushButton("🔄 读取行程")
        btn_read.setToolTip("向 P4 请求 30 路会话逻辑行程（CMD_STATE_SYNC_REQUEST, bit2）")
        btn_read.clicked.connect(self.request_range)
        bar.addWidget(btn_read)
        btn_csv = QPushButton("💾 导出 CSV")
        btn_csv.clicked.connect(self.export_csv)
        bar.addWidget(btn_csv)
        self.note = QLabel("逻辑行程 = P4 上电会话可达范围；EEPROM 的 P/D/I/力矩限制需固件支持")
        self.note.setObjectName("muted")
        bar.addWidget(self.note, 1)
        root.addLayout(bar)

        self.table = QTableWidget(len(SERVO_TARGETS), len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 16 列按内容宽（原来只拉伸最后一列 → 总宽超窗口，最右「温度/行程」被裁）
        _hdr = self.table.horizontalHeader()
        _hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        _hdr.setStretchLastSection(False)
        _hdr.setDefaultAlignment(Qt.AlignCenter)
        self.table.verticalHeader().setDefaultSectionSize(28)
        root.addWidget(self.table, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(200)          # 5Hz：只刷 3 行 16 列，开销可忽略
        self._refresh()

    # ---------- 数据 ----------
    def _row_values(self, m: int) -> list:
        sc = self.scope
        ch = sc.channels
        def last(name, default=None):
            c = ch.get(name)
            v = c.buf.last() if c is not None else None
            return default if v is None or math.isnan(v) else v
        abs_v = last(f"m{m}_abs")
        raw_v = last(f"m{m}_raw")
        spd = last(f"m{m}_speed")
        load = last(f"m{m}_load")
        cur = last(f"m{m}_current")
        volt = last(f"m{m}_volt")
        temp = last(f"m{m}_temp")
        rng = getattr(sc, "servo_range", None)
        lo = hi = None
        if rng and (int(rng.get("bitmap", 0)) >> m) & 1:
            lo, hi = rng["min"][m], rng["max"][m]
        online = "●" if sc._motor_enabled(m) and abs_v is not None else "○"
        origin = sc._motor_origin.get(m)
        tgt = sc.targets.get(m)
        acc = (int(abs_v) - int(origin)) if (abs_v is not None and origin is not None) else None
        fmt = lambda v, nd=0: ("—" if v is None else f"{v:+.{nd}f}")
        return [
            f"M{m}", str(m), online, fmt(abs_v), fmt(raw_v), fmt(spd), fmt(load),
            fmt(cur), fmt(volt, 1), fmt(temp, 0),
            fmt(lo), fmt(hi),
            ("—" if (lo is None or hi is None) else f"{hi - lo}"),
            fmt(origin), fmt(tgt), fmt(acc),
        ]

    def _refresh(self) -> None:
        for r, m in enumerate(SERVO_TARGETS):
            for c, v in enumerate(self._row_values(m)):
                if self.table.item(r, c) is None:
                    item = QTableWidgetItem(v)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(r, c, item)
                elif self.table.item(r, c).text() != v:
                    self.table.item(r, c).setText(v)

    # ---------- 动作 ----------
    def request_range(self) -> None:
        """请求 P4 回传 30 路会话逻辑行程。"""
        sc = self.scope
        if sc.rx_thread is None:
            sc._ctrl_status("舵机信息：未连接，无法读取行程", log=False)
            return
        ok = sc.rx_thread.send(build_state_sync_request_cmd(_SYNC_LOGICAL_RANGE))
        sc._ctrl_status("舵机信息：已请求逻辑行程" if ok else "舵机信息：请求发送失败",
                        log=False)

    def export_csv(self) -> None:
        """把当前表导出 CSV（UTF-8-BOM，Excel 可直接开）。"""
        name = "servo_info_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        rows = [[self.table.item(r, c).text() if self.table.item(r, c) else ""
                 for c in range(len(self.COLS))] for r in range(self.table.rowCount())]
        buf = io.StringIO(newline="")
        w = csv.writer(buf)
        w.writerow(self.COLS)
        w.writerows(rows)
        path = safe_export_path(name)
        if path is None:
            self.scope._ctrl_status("舵机信息：导出失败（路径校验不过）", log=False)
            return
        try:
            path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")
        except OSError as exc:
            self.scope._ctrl_status(f"舵机信息：导出失败 {exc}", log=False)
            return
        self.scope._ctrl_status(f"舵机信息：已导出 → {name}", log=False)

    def closeEvent(self, ev):  # noqa: N802
        self._timer.stop()
        self.scope.servo_info_window = None
        super().closeEvent(ev)


class ParameterWatchWindow(QWidget):
    """独立参数监视窗：自选参数平铺、60Hz 刷新、可置顶、随主窗关闭。"""

    def __init__(self, scope):
        super().__init__(scope)
        self.scope = scope
        self.setWindowTitle("参数监视（右键块删除 / 下拉添加）")
        self.setMinimumWidth(480)
        self.setWindowFlag(Qt.Window, True)
        root = QVBoxLayout(self)
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        root.addLayout(self.grid)
        bottom = QHBoxLayout()
        self.add_combo = QComboBox()
        self.add_combo.setMinimumHeight(30)
        self.add_combo.currentIndexChanged.connect(self._on_add)
        bottom.addWidget(self.add_combo, 1)
        self.top_check = QCheckBox("置顶")
        self.top_check.toggled.connect(self._on_top)
        bottom.addWidget(self.top_check)
        root.addLayout(bottom)
        self.tiles = []  # [(key, WatchTile)]
        self._registry = None   # 注册表缓存：见 _reg()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(16)  # 60Hz：只刷十来个数字块，实测 ~0.05ms/次
        self._rebuild_combo()

    def closeEvent(self, ev):
        """关窗统一出口（按钮/X/主窗级联）：停表 + 释放 scope 引用 + 销毁。

        与 RTensionWindow.closeEvent 同因：X 关闭只 hide，隐藏窗定时器会一直跑。
        """
        self._timer.stop()
        w = self.scope
        if getattr(w, "watch_window", None) is self:
            w.watch_window = None
        self.deleteLater()
        super().closeEvent(ev)

    # ---- 参数注册表：key -> (名称, 取值函数) ----
    @staticmethod
    def registry(w):
        import math as _m

        def ang(j):
            raw = w._enc_filt_raw.get(j)
            if raw is None:
                return None
            cur = w._axis_deg(j, raw)
            b = w.angle_baseline.get(j)
            return cur if b is None else w._angle_delta(cur, b)

        def fval(key, default=0.0):
            return w._cl_fval(key, default, -1e9, 1e9)

        def num(v, unit="", digits=2):
            if v is None or (isinstance(v, float) and _m.isnan(v)):
                return "--"
            return f"{v:+.{digits}f}{unit}" if isinstance(v, float) else f"{v}{unit}"

        reg = {}
        reg["roll_cur"] = ("ROLL 当前°", lambda: num(ang(16), ""))
        reg["roll_tgt"] = ("ROLL 目标°", lambda: num(fval("roll_tgt"), ""))
        reg["roll_err"] = ("ROLL 误差°", lambda: num(fval("roll_tgt") - (ang(16) or 0.0), ""))
        reg["roll_base"] = ("ROLL 基准°", lambda: num(w.angle_baseline.get(16), ""))
        reg["pitch_cur"] = ("PITCH 当前°", lambda: num(ang(17), ""))
        reg["pitch_tgt"] = ("PITCH 目标°", lambda: num(fval("pitch_tgt"), ""))
        reg["pitch_err"] = ("PITCH 误差°", lambda: num(fval("pitch_tgt") - (ang(17) or 0.0), ""))
        reg["pitch_base"] = ("PITCH 基准°", lambda: num(w.angle_baseline.get(17), ""))
        for m in (27, 28, 29):
            buf = w.channels[f"m{m}_abs"].buf
            origin = w._motor_origin.get(m)
            reg[f"m{m}_abs"] = (f"M{m} 实际", lambda b=buf: num(b.last(), "", 0))
            reg[f"m{m}_tgt"] = (f"M{m} 目标", lambda mm=m: num(w.targets.get(mm), "", 0))
            reg[f"m{m}_off"] = (f"M{m} 累计", lambda b=buf, o=origin:
                                "--" if o is None or _m.isnan(b.last()) else f"{int(b.last())-o:+d}")
            reg[f"m{m}_load"] = (f"M{m} 负载", lambda mm=m: num(w.channels[f"m{m}_load"].buf.last(), "", 1))
            reg[f"m{m}_cur"] = (f"M{m} 电流", lambda mm=m: num(w.channels[f"m{m}_current"].buf.last(), "", 1))
            reg[f"m{m}_volt"] = (f"M{m} 电压", lambda mm=m: num(w.channels[f"m{m}_volt"].buf.last(), "V", 1))
            reg[f"m{m}_temp"] = (f"M{m} 温度", lambda mm=m: num(w.channels[f"m{m}_temp"].buf.last(), "°C", 1))
            reg[f"m{m}_spd"] = (f"M{m} 速度", lambda mm=m: num(w.channels[f"m{m}_speed"].buf.last(), "", 0))
        for m in (27, 28, 29):
            reg[f"r_roll_m{m}"] = (f"R:ROLL→M{m}", lambda mm=m: num(
                w._cl_gain_vals.get(mm, (0.0, 0.0))[0], "", 2))
            reg[f"r_pitch_m{m}"] = (f"R:PITCH→M{m}", lambda mm=m: num(
                w._cl_gain_vals.get(mm, (0.0, 0.0))[1], "", 2))
        reg["cl_state"] = ("闭环", lambda: "运行中" if w.cl_enabled else "停止")
        reg["cl_kp"] = ("Kp", lambda: num(fval("kp"), ""))
        reg["cl_dead"] = ("死区°", lambda: num(fval("deadband"), ""))
        reg["cl_limit"] = ("限幅°", lambda: num(fval("limit"), ""))
        reg["sys_state"] = ("系统状态", lambda: "直控" if w.status_info.get("control_mode") == 1
                            else str(w.status_info.get("state")))
        reg["online_enc"] = ("磁编在线", lambda: f"{bin(w.status_info.get('encoder_online', 0)).count('1')}/21")
        reg["online_srv"] = ("M27-29在线", lambda: f"{sum(1 for m in (27,28,29) if w.status_info.get('servo_online',0)>>m&1)}/3")
        return reg

    # ---- 块管理 ----
    def _reg(self):
        """注册表缓存：键/名称/取值函数全是静态的（lambda 运行时读 scope 活
        数据），60Hz _refresh 不必每次重建整个 dict + 30 个闭包。"""
        if self._registry is None:
            self._registry = self.registry(self.scope)
        return self._registry

    def add_param(self, key):
        if any(k == key for k, _ in self.tiles):
            return
        reg = self._reg()
        if key not in reg:
            return
        tile = WatchTile()
        tile.setProperty("param_key", key)
        tile.removed = self.remove_param
        tile.setObjectName("tile")
        self.tiles.append((key, tile))
        self._layout_tiles()
        self._rebuild_combo()
        self._refresh()

    def remove_param(self, key):
        self.tiles = [(k, t) for k, t in self.tiles if k != key]
        self._rebuild_combo()
        self._layout_tiles()

    def _layout_tiles(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                self.grid.removeWidget(it.widget())
                it.widget().setParent(None)
        cols = 2
        for i, (_, tile) in enumerate(self.tiles):
            self.grid.addWidget(tile, i // cols, i % cols)
        self.adjustSize()

    def _rebuild_combo(self):
        reg = self._reg()
        used = {k for k, _ in self.tiles}
        self.add_combo.blockSignals(True)
        self.add_combo.clear()
        self.add_combo.addItem("＋ 添加参数…")
        for k in sorted(reg):
            if k not in used:
                self.add_combo.addItem(reg[k][0], k)
        self.add_combo.blockSignals(False)

    def _on_add(self, idx):
        if idx <= 0:
            return
        key = self.add_combo.itemData(idx)
        self.add_combo.setCurrentIndex(0)
        if key:
            self.add_param(key)

    def _on_top(self, checked):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def _refresh(self):
        reg = self._reg()
        for key, tile in self.tiles:
            name, getter = reg.get(key, ("?", lambda: "--"))
            try:
                val = getter()
            except Exception:
                val = "--"
            tile.setText(f"<div style='color:{AT.T('muted')};font-size:11px'>{name}</div>"
                         f"<div style='color:{AT.T('text')};font-size:19px;font-weight:bold'>{val}</div>")


class CustomThemeDialog(QDialog):
    """自定义配色：逐槽取色器；保存后随布局持久化（未设槽继承夜间预设）。"""

    def __init__(self, parent, overrides):
        super().__init__(parent)
        self.setWindowTitle("自定义配色")
        self.setMinimumWidth(360)
        self.overrides = dict(overrides or {})
        grid = QGridLayout()
        grid.setSpacing(6)
        self._btns = {}
        for i, slot in enumerate(AT.EDITABLE_SLOTS):
            grid.addWidget(QLabel(AT.SLOT_LABELS[slot]), i // 2, (i % 2) * 2)
            btn = QPushButton()
            btn.setFixedHeight(26)
            btn.clicked.connect(lambda _=False, s=slot: self._pick(s))
            grid.addWidget(btn, i // 2, (i % 2) * 2 + 1)
            self._btns[slot] = btn
        self._sync()
        box = QVBoxLayout(self)
        box.addLayout(grid)
        hint = QLabel("保存并应用后随布局记住；分类色与其余槽继承夜间预设")
        hint.setObjectName("muted")
        box.addWidget(hint)
        row = QHBoxLayout()
        ok = QPushButton("保存并应用")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        box.addLayout(row)

    def _color(self, slot):
        return self.overrides.get(slot, AT.PRESETS["night"][slot])

    def _sync(self):
        for slot, btn in self._btns.items():
            color = self._color(slot)
            btn.setText(color)
            btn.setStyleSheet(
                f"background:{color}; color:#ffffff; border:none; border-radius:6px;")

    def _pick(self, slot):
        color = QColorDialog.getColor(QColor(self._color(slot)), self,
                                      f"选择 {AT.SLOT_LABELS[slot]}")
        if color.isValid():
            self.overrides[slot] = color.name()
            self._sync()


class _NoWheelValueGuard(QObject):
    """全局滚轮守卫：禁止滚轮改变下拉框/数值框的值。

    Qt 默认行为：QComboBox / QAbstractSpinBox 获得焦点后，鼠标滚轮会直接切换
    当前项 / 加减数值。控制模式（位置·张力·张紧·力矩）被滚轮误改会触发停环，
    波特率、步长、斜坡速率同理——都是"手滑一下就改设备行为"的事故级误操作。
    这里只吞 Wheel 事件，不影响键盘、点击，也不影响滚动区（滚动区不是这两类控件）。
    """

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and isinstance(obj, (QComboBox, QAbstractSpinBox)):
            ev.ignore()
            return True      # 吞掉：不改值、不误触
        return False


def install_no_wheel_guard(app=None) -> None:
    """给应用装一次滚轮守卫（幂等；之后新建的窗口也自动覆盖）。"""
    app = app or QApplication.instance()
    if app is None or getattr(app, "_no_wheel_guard", None) is not None:
        return
    guard = _NoWheelValueGuard(app)
    app.installEventFilter(guard)
    app._no_wheel_guard = guard


class _TimedPlotWidget(pg.PlotWidget):
    """主图控件：始终统计 paint 用时（喂给自适应点数阀门）；MMHAND_FPS=1 时每 2s 打印。

    另带一个"贴在图区正中的提示层"：早先用 pg.TextItem 挂在 ViewBox 上，
    位置按数据坐标算，窗口一改大小就漂到图区上沿、被裁成半行（用户看到的
    那两行乱码）。改成子 QLabel + resize 时重新居中，永远压在图区正中间。

    2026-11-24 新增：双击事件上抛给 ScopeWindow（加/删水平标记线）。
    """

    _report = os.environ.get("MMHAND_FPS") == "1"
    paint_ema_ms = 0.0
    last_paint_ms = 0.0

    def add_overlay(self, label: QLabel) -> None:
        label.setParent(self)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setAlignment(Qt.AlignCenter)
        self._overlays = getattr(self, "_overlays", [])
        self._overlays.append(label)
        self._place_overlays()

    def _place_overlays(self) -> None:
        for lb in getattr(self, "_overlays", ()):
            if lb is None:
                continue
            lb.adjustSize()
            lb.move(max(0, (self.width() - lb.width()) // 2),
                    max(0, (self.height() - lb.height()) // 2))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_overlays()

    def mouseDoubleClickEvent(self, ev):  # noqa: N802 (Qt 命名)
        scope = getattr(self, "scope", None)
        handler = getattr(scope, "_on_plot_double_click", None)
        if handler is not None and handler(ev):
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def leaveEvent(self, ev):  # noqa: N802
        super().leaveEvent(ev)
        scope = getattr(self, "scope", None)
        hide = getattr(scope, "_hide_hover", None)
        if hide is not None:
            hide()

    def paintEvent(self, ev):
        t0 = time.perf_counter()
        super().paintEvent(ev)
        dt = (time.perf_counter() - t0) * 1000.0
        self.last_paint_ms = dt
        prev = self.paint_ema_ms
        # 0.9/0.1 指数滑动平均：单帧抖动不参与决策，只反映"现在画一帧要多久"
        self.paint_ema_ms = dt if prev <= 0.0 else prev * 0.9 + dt * 0.1
        if not self._report:
            return
        st = getattr(self, "_fps_state", None)
        if st is None:
            st = self._fps_state = {"n": 0, "sum": 0.0, "max": 0.0, "t": time.perf_counter()}
        st["n"] += 1
        st["sum"] += dt
        if dt > st["max"]:
            st["max"] = dt
        now = time.perf_counter()
        span = now - st["t"]
        if span >= 2.0:
            print(f"[fps] 主图 {st['n'] / span:5.1f} FPS  paint 平均 {st['sum'] / st['n']:5.1f} ms  "
                  f"峰值 {st['max']:5.1f} ms")
            st.update(n=0, sum=0.0, max=0.0, t=now)


class RejectDialog(QWidget):
    """门禁拒绝弹窗（2026-11-09 定案）：居中置顶、不自动消失、必须手动关。

    交互语义（与用户逐条确认）：
    - 纯观察者：不在任何控制路径上；「知道了」只关窗——不重试、不放行、
      不解锁任何东西；取证（GATE_REJECT）在拒绝瞬间已落盘，与关窗无关。
    - 不锁主窗：以**子控件**实现（不经窗口管理器、不抢键盘焦点），急停/
      复位等一切主窗操作照常可用；标题栏可拖动避开读数，出界被钳回。
    - 唯一"活"按钮 = ⛔急停：与主窗 _on_stop 同一条路（抢占 STOP+锁存+
      解除武装），按完自动关窗。
    - 合并防风暴：未关期间的新拒绝并入本窗（×N 计数 + 末 MAX_ITEMS 条原因），
      绝不叠出第二个窗；autoRepeat 点动长按安全。注意：合并后只有**最新**
      一条的门禁参与复查（✅/❌ 行不代表列表里每条都已复核）。
    - 1Hz 复查（用户定案做①）：recheck 为纯读 callable，返回 None=条件已
      满足 / str=仍不满足的原因；正文行实时显示，改没改好不用试错。
    """

    MAX_ITEMS = 3

    def __init__(self, scope: "ScopeWindow"):
        super().__init__(scope)
        self._scope = scope
        self._items = []            # [(gate, reason)]，保留末 MAX_ITEMS 条
        self._count = 0             # 自上次关闭以来的拒绝总次数
        self._recheck = None
        self._recheck_failed = False
        self._drag_off = None
        self._verb = "被拒"
        self.setFixedWidth(460)
        self._build_ui()
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setInterval(1000)
        self._recheck_timer.timeout.connect(self._recheck_tick)
        self.hide()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.setObjectName("reject_dialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._bar = QWidget()
        self._bar.setAttribute(Qt.WA_StyledBackground, True)
        self._bar.setStyleSheet(
            f"background:{AT.T('bad')};")
        self._bar.installEventFilter(self)
        bh = QHBoxLayout(self._bar)
        bh.setContentsMargins(12, 6, 6, 6)
        self._title = QLabel("⛔ 被拒")
        self._title.setStyleSheet(
            f"color:white; font-weight:700; font-size:13px;"
            f" border:none; background:transparent;")
        bh.addWidget(self._title, 1)
        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(26)
        close_btn.setStyleSheet(
            "color:white; font-weight:700; font-size:13px;"
            " border:none; background:transparent;")
        close_btn.clicked.connect(self._dismiss)
        bh.addWidget(close_btn)
        lay.addWidget(self._bar)

        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, True)
        body.setStyleSheet(f"background:{AT.T('panel')};")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(14, 10, 14, 10)
        bv.setSpacing(8)
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._body.setStyleSheet(
            f"color:{AT.T('text')}; font-size:12.5px;"
            f" border:none; background:transparent;")
        bv.addWidget(self._body)
        self._status = QLabel()
        self._status.setWordWrap(True)
        bv.addWidget(self._status)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self._estop_btn = QPushButton("⛔ 急停")
        self._estop_btn.clicked.connect(self._on_estop)
        self._know_btn = QPushButton("知道了")
        self._know_btn.clicked.connect(self._dismiss)
        btns.addWidget(self._estop_btn)
        btns.addStretch(1)
        btns.addWidget(self._know_btn)
        bv.addLayout(btns)
        lay.addWidget(body)
        self._apply_theme()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            f"#reject_dialog{{background:{AT.T('panel')};"
            f" border:1px solid {AT.T('bad')};}}")
        self._estop_btn.setStyleSheet(
            f"color:white; background:{AT.T('bad')}; font-weight:700;"
            f" border:none; border-radius:5px; padding:7px 16px;")
        self._know_btn.setStyleSheet(
            f"color:{AT.T('text')}; background:{AT.T('input')};"
            f" font-weight:600; border:1px solid {AT.T('input_line')};"
            f" border-radius:5px; padding:7px 22px;")

    # ------------------------------------------------------------ 事件
    def eventFilter(self, obj, ev):
        """标题栏拖动：按住标题栏可在主窗内移动弹窗（避开读数），钳在父窗内。

        坐标全用**父窗坐标系**（child widget 的 move() 吃父坐标；REVIEW
        Important#1：全局坐标直减会让弹窗瞬移到 父窗原点+原位置 之外）。"""
        if obj is not getattr(self, "_bar", None):
            return super().eventFilter(obj, ev)
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            parent = self.parentWidget()
            if parent is not None:
                self._drag_off = (parent.mapFromGlobal(
                    ev.globalPosition().toPoint()) - self.pos())
            return False
        if t == QEvent.MouseMove and self._drag_off is not None:
            parent = self.parentWidget()
            if parent is None:
                return False
            target = (parent.mapFromGlobal(ev.globalPosition().toPoint())
                      - self._drag_off)
            g = parent.rect()
            self.move(max(0, min(target.x(), g.width() - self.width())),
                      max(0, min(target.y(), g.height() - self.height())))
            return False
        if t == QEvent.MouseButtonRelease:
            self._drag_off = None
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------ 行为
    def push(self, gate: str, reason: str, recheck=None, verb: str = "被拒") -> None:
        """推送一条拒绝/停止通知（新条目或未关期间的合并条目）。

        verb：标题动词（拒绝=被拒；一键紧绳会话的停环通知=已停止）。"""
        self._items.append((gate, reason))
        del self._items[:-self.MAX_ITEMS]
        self._count += 1
        self._recheck = recheck
        self._recheck_failed = False
        self._verb = verb
        was_hidden = not self.isVisible()
        self._refresh()
        self.adjustSize()
        if was_hidden:
            self._center()
        self.show()
        self.raise_()
        if self._recheck is not None:
            self._recheck_tick()            # 立即出一次状态，不等满 1s
            if not self._recheck_failed:    # 首查即炸 → 已停表，不再拉起
                self._recheck_timer.start()
        else:
            self._recheck_timer.stop()
            self._status.hide()

    def _center(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        g = parent.rect()
        self.move((g.width() - self.width()) // 2,
                  max(0, (g.height() - self.height()) // 2 - 40))

    def _refresh(self) -> None:
        gate = self._items[-1][0] if self._items else ""
        count = f"（共 {self._count} 次，已合并）" if self._count > 1 else ""
        self._title.setText(f"⛔ {gate} {self._verb}{count}")
        self._body.setText("\n".join(f"• [{g}] {r}" for g, r in self._items))

    def _recheck_tick(self) -> None:
        """1Hz 复查当初拒你的门禁：显示 ✅可重试 / ❌仍不满足+原因。"""
        if self._recheck is None or self._recheck_failed:
            return
        self._status.show()
        try:
            reason = self._recheck()
        except Exception as exc:   # 复查应是纯读；万一炸：报一次即闩死，不打断 UI
            self._recheck_failed = True
            self._recheck_timer.stop()
            self._status.setStyleSheet(
                f"color:{AT.T('warn')}; font-size:12px;"
                f" border:none; background:transparent;")
            self._status.setText(f"⚠ 复查异常，已停止自动复查：{exc}")
            self.adjustSize()
            return
        if reason:
            self._status.setStyleSheet(
                f"color:{AT.T('bad')}; font-size:12px; font-weight:600;"
                f" border:none; background:transparent;")
            self._status.setText(f"❌ 仍不满足：{reason}")
        else:
            self._status.setStyleSheet(
                f"color:{AT.T('good')}; font-size:12px; font-weight:600;"
                f" border:none; background:transparent;")
            self._status.setText("✅ 条件已满足，可重试（关窗不改变任何状态）")
        # REVIEW Minor#5/#10：文案变长会撑高状态行 → 重算高度并钳回父窗可见区
        self.adjustSize()
        self._clamp_into_parent()

    def _clamp_into_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        g = parent.rect()
        self.move(max(0, min(self.x(), g.width() - self.width())),
                  max(0, min(self.y(), g.height() - self.height())))

    def _dismiss(self) -> None:
        """「知道了」/✕：只关窗并清零重计——不触发、不放行任何控制动作。"""
        self._recheck_timer.stop()
        self._recheck = None
        self._items = []
        self._count = 0
        self.hide()

    def _on_estop(self) -> None:
        self._dismiss()
        self._scope._on_stop()


class _ClLoopThread(QThread):
    """闭环控制线程：固定周期调用 `win._cl_tick()`（2026-11-19 新增）。

    **为什么存在**：原来闭环由 `QTimer` 驱动，和主图/表格/曲线重绘**在同一个
    GUI 线程**排队；实测控制拍周期 22~28 ms（设计 10 ms）→ 只有 36~44 Hz，
    `max_step=20 × 44 Hz = 880 c/s` 远低于设计 2000 c/s，"电机变化慢"的一部分
    就是它。本线程用「绝对时间表 + sleep」调度，抖动约 1 ms，不再受重绘影响。

    **线程安全约定**：
    · 线程里只调 `_cl_tick()`（已把 UI 写操作改成 `_ui_call` 投递）；
    · UI 一律通过 `win._ui_call(...)` 排队，由 GUI 线程的 `_drain_ui_queue` 执行；
    · 停环：GUI 线程调 `stop()` 置 `_halt`，线程在下一拍开头退出。
    """

    def __init__(self, win, period_s: float = 0.01):
        super().__init__(win if isinstance(win, QObject) else None)
        self._win = win
        self._period = float(period_s)
        self._halt = False

    def stop(self) -> None:
        self._halt = True

    def run(self) -> None:
        win = self._win
        period = self._period
        # 2026-11-24：把本线程提到 Windows 高优先级，并把 GIL 切换间隔缩到 1 ms。
        # 现场 dt 中位 15.6 ms、38% 连跑 —— 与"GUI 曲线/表格每秒 60~75 帧、
        # 单帧 17 ms"吻合：控制线程抢不到 GIL，晚到后又被"追补"连跑。
        # 这两项只是缓解；真正的负载要 GUI 侧降帧（MMHAND_PLOT_HZ）。
        try:
            import sys as _sys
            _sys.setswitchinterval(0.001)
        except Exception:
            pass
        try:
            import ctypes as _ct
            _k32 = _ct.windll.kernel32
            _k32.SetThreadPriority(_k32.GetCurrentThread(), 2)   # HIGHEST
        except Exception:
            pass
        t_next = time.perf_counter() + period
        while not self._halt:
            if win._cl_stop_request is not None:
                break
            try:
                win._cl_tick()
            except Exception as exc:       # 线程异常不能静默，交给 GUI 停环
                win._cl_stop_request = f"控制线程异常：{exc!r}"
                # 2026-11-23：以前只置标志、GUI 没人消费 —— 线程悄悄死掉，
                # 界面还显示"运行中"，按启动只会动一下。现在写日志 + 走 GUI 停环。
                try:
                    win._safety("CL_THREAD_DIED", err=repr(exc))
                except Exception:
                    pass
                try:
                    win._ui_call(win._stop_closed_loop,
                                 f"控制线程异常：{exc!r}", popup=True)
                except Exception:
                    pass
                break
            now = time.perf_counter()
            # 2026-11-24：**不追补**。
            # 旧实现 `t_next += period` 累加欠账：一旦某拍超过 10 ms（GUI 抢
            # GIL / 串口发送阻塞），`t_next` 就落在过去 → `gap ≤ 0` → 下一拍
            # **立刻连跑**，用的还是同一个张力样本 → P 作用两遍、连发两帧。
            # 现场证据（run_data/sine/*.csv）：dt 中位 15~16 ms，且 38% 的相邻
            # 行时间戳完全相同（连跑），而两行的 trim 不同（确实算了两遍）。
            # 现在：落后超过一整拍就**重锚**到"现在 + 周期"，绝不连跑两拍。
            if now - t_next > period:
                t_next = now + period
            else:
                t_next += period
            gap = t_next - now
            if gap > 0.0:
                time.sleep(gap)


class _TensionPollThread(QThread):
    """同一线程串行执行采集和重开；只有通过校验的重量帧才能确认恢复。"""

    _no_frame_s = 2.0
    _retry_initial_s = 0.5
    _retry_max_s = 5.0

    def __init__(self, win, sensor, port="", baud=600000):
        super().__init__(win if isinstance(win, QObject) else None)
        self._win = win
        self._sensor = sensor
        self._port_name = str(port or "")
        self._baud = int(baud or 600000)
        self._stop_event = threading.Event()
        self._reconnects = 0
        self.link_status = "等待首帧"
        self.stop_reason = ""

    def stop(self) -> None:
        self._stop_event.set()

    def _log(self, state, **detail):
        safety_log("TENSION_LINK", port=self._port_name, baud=self._baud,
                   state=state, **detail)

    def run(self) -> None:
        sys.setswitchinterval(0.001)
        try:
            self._poll_loop()
        except Exception as exc:
            self.stop_reason = f"采集线程退出：{exc!r}"
            self._log("worker_failed", error=repr(exc))
        finally:
            try:
                self._sensor.disconnect()
            except Exception as exc:
                self._log("close_failed", error=repr(exc))

    def _poll_loop(self) -> None:
        sensor = self._sensor
        last_frame = time.perf_counter()
        healthy_since = None
        delay = self._retry_initial_s
        attempt = 0
        fault = ""
        last_feed_error = None
        self._log("opened")
        while not self._stop_event.is_set():
            if fault:
                if not self._port_name:
                    self.stop_reason = fault
                    return
                attempt += 1
                self.link_status = f"第 {attempt} 次重连，{delay:g} 秒后重试 · {fault}"
                self._log("retry", attempt=attempt, wait_s=delay, reason=fault)
                try:
                    sensor.disconnect()
                except Exception as exc:
                    self._log("close_failed", error=repr(exc))
                if self._stop_event.wait(delay):
                    return
                delay = min(self._retry_max_s, 2 * delay)
                try:
                    sensor.connect(self._port_name, self._baud)
                except Exception as exc:
                    fault = f"打开串口失败：{exc!r}"
                    continue
                self.link_status = f"第 {attempt} 次重连，串口已打开，等待有效重量帧"
                healthy_since = None
                last_frame = time.perf_counter()
                fault = ""
                continue

            try:
                raws = sensor.poll()
            except Exception as exc:
                fault = f"采集异常：{exc!r}"
                continue
            now = time.perf_counter()
            if raws is None:
                silence = now - last_frame
                if silence >= self._no_frame_s:
                    fault = (f"{silence:.1f} 秒无有效重量帧，超时 {sensor.timeouts}，"
                             f"错帧 {sensor.protocol_errors}，{sensor.error or '无响应'}")
                    continue
                # 传输中让出 CPU，避免无字节时持续查询 Windows 串口。
                time.sleep(max(0.00025, min(sensor.next_poll_delay(), 0.002)))
                continue

            if self._stop_event.is_set():
                return
            last_frame = now
            if healthy_since is None:
                healthy_since = now
                if attempt:
                    self._reconnects += 1
                self._log("streaming", attempt=attempt, recoveries=self._reconnects)
                self.link_status = ""
                attempt = 0
            elif delay != self._retry_initial_s and now - healthy_since >= 3.0:
                delay = self._retry_initial_s
            try:
                self._win._tension_feed(raws)
                last_feed_error = None
            except Exception as exc:
                # 与串口故障分开记录，避免数据处理异常被静默丢掉。
                error = repr(exc)
                if error != last_feed_error:
                    self._log("feed_error", error=error)
                    last_feed_error = error


class ScopeWindow(QMainWindow):
    exportFinished = Signal()
    # 双击加的横线标记：上限（同时也限制写进布局存档的条数）
    _H_MARKER_MAX = 20

    def __init__(self, default_port: str = "COM13"):
        super().__init__()
        install_no_wheel_guard()   # 滚轮不得改控制模式/步长/波特率等（全局一次）
        self.setWindowTitle("MMHand 示波器+直控 - 磁编 J00-J20 + M27-M29")
        # 默认尺寸按屏幕算（原来硬写 1600x900：1366/1280 屏会超出可视区）
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(1600, max(1100, screen.width() - 80))
        h = min(900, max(620, screen.height() - 80))
        self.resize(w, h)
        self.move(max(0, screen.x() + (screen.width() - w) // 2),
                  max(0, screen.y() + (screen.height() - h) // 2))
        self.channels = {}
        self.rx_queue = queue.Queue()
        self.rx_thread = None
        self.connected = False
        self.plot_frozen = False
        self.t0 = None
        self.status_info = {"state": None, "servo_online": 0, "encoder_online": 0, "can_online": 0,
                            "multiturn_unknown": 0, "direct_reject": 0, "control_mode": 0,
                            "control_enabled": 0}
        self.route_info = {"scan_state": 0, "controllable_bitmap": 0, "valid_bitmap": 0}
        self.last_servo_abs_all = None
        self._overload_motors = {}
        self._status_rx_at = 0.0
        self._admit_sent_at = 0.0
        self._prior_applied_generation = None
        self.armed = False
        self.targets = {m: None for m in SERVO_TARGETS}
        self._zero_poll_count = 0
        self._ramp_state = {}
        self._ramp_first_tick = False
        self._visible_series = {}
        # 曲线点数密度（点/像素）：_adapt_density 按 paint 实测在 0.25~3 之间自动调，
        # 帧率钉在 PLOT_HZ，点数让路（不会出现"为了画全点把帧率拖到 30"）。
        self._pts_per_px = 2.0
        # 运行遥测计数（仅 MMHAND_TELEMETRY 生效时被写入/读取）
        self._table_frames = 0
        self._tele_gap_ms = 0.0
        self._tele_last = None
        self._tele_max: dict[str, float] = {}
        self._release_plan = None      # 一键松绳分步执行态
        self._reject_dlg = None        # 门禁拒绝弹窗（懒建，_reject 里创建）
        self._tighten_cl_active = False   # 当前闭环是否由一键紧绳启动（停环弹窗用）
        self._latest_t = None
        self._motor_origin = {m: None for m in SERVO_TARGETS}
        self.target_edits = {}
        # 逐绳使能开关（2026-11-02 用户需求：每根绳一个勾选框，勾了才允许使能）。
        # 未勾选的电机：使能时不纳入 ACTIVE_SCOPE/归零/在线检查，点动/Go/斜坡/
        # 回零/闭环一律不下发命令。固件对单电机命令(0xDE)不与 ACTIVE_SCOPE 求交，
        # 所以门禁必须落在上位机每条发送路径上（_send_motor_target 等）。
        self.cable_enable_checks = {}       # motor -> QCheckBox（_build_control_panel 填）
        self.jog_buttons_by_motor = {}      # motor -> [minus, plus]
        self.go_buttons = {}                # motor -> Go 按钮
        self._cl_motor_on = frozenset(SERVO_TARGETS)   # 本轮闭环实际驱动的电机（启动时快照）
        self.cl_enabled = False
        self._want_closed_loop = False
        self._want_goto_zero = False
        self.cl_edits = {}
        self.watch_window = None
        self.rt_window = None
        self.wrist_calib = None
        self._tension_sensor = None     # ZnsvTransmitter（连接后非 None，观测台直接持有）
        self._tension_port_name = ""
        self._tension_ch_map = list(TENSION_CH_FOR_CABLE)   # C1/C2/C3 ← CHn（观测台可改）
        # 2026-11-25：轮询搬进独立线程（`_TensionPollThread`）。实测裸串口 249.9 Hz、
        # 而原来的 GUI-QTimer 方案只有 ~15 Hz —— 张力环的等效延迟主要就是它造成的。
        self._tension_thread = None
        # 旧的 QTimer 保留但**不再启动**（`tools/perf` 与测试仍引用这个属性）。
        self._tension_poll_timer = QTimer(self)
        self._tension_poll_timer.setInterval(1)
        self._tension_poll_timer.setTimerType(Qt.PreciseTimer)
        self._tension_poll_timer.timeout.connect(
            self._timed_slot("tension", self._tension_poll))
        self._tension_last = None       # (time.monotonic(), [f1,f2,f3]) 绝对张力（守卫用）
        self._tension_zero = None       # 本地零位 [z1,z2,z3]N | None（仅观测台显示用）
        self._tension_hist = [deque(maxlen=7500) for _ in range(3)]  # 全量历史：7500 帧@250Hz=30s
        # 显示抽稀缓冲：每 5 帧取 1 → 1500 点=30s。走势刷新直接 list() 这个，
        # 避免 60Hz×3 卡 ×O(7500) 切片（2026-11-02 张力模式卡死的次因）。
        self._tension_hist_disp = [deque(maxlen=1500) for _ in range(3)]
        self._tension_feed_count = 0
        self._tension_arrivals = deque(maxlen=512)  # 高于支持的 250 Hz，供界面统计近一秒
        self._tension_raws_last = None  # 最近一帧 8 通道 raw（观测台 CH 条）
        # 张力 UI 控件在张力·R 观测台打开时才创建；此前置空防 AttributeError。
        self.tension_btn = None
        self.tension_status = None
        self.tension_fmin_edit = None
        self.tension_fmax_edit = None
        # 守卫阈值的持久镜像：观测台每次打开重建控件，文本存在这里才能跨重启
        # （2026-11-01 用户报"写入的上限每次重启都是0"——根因=保存清单漏了这两个框）。
        self._tension_guard_saved = {"f_min": "", "f_max": ""}
        # 串口号/波特率同款持久镜像（换 USB 口后不必每次重选）。
        self._tension_link_saved = {"port": "", "baud": ""}
        self._tension_estimate_k = ["", ""]  # C2/C3 标定刚度，N/mm
        # 观测台缆卡张力走势显示开关（2026-11-04 用户需求：自选看不看）。
        self._tension_trend_on = True
        # 观测台绳长卡折叠态（方案二改：R/绳长与张力同屏，绳长默认展开可折）。
        self._tension_len_folded = False
        self._calib_rec = None          # 标定记录态 {t0, t[], cols[][]} | None
        self._force_recovery = False    # 一键紧绳恢复态（徽章"恢复中"；停环清）
        self._recovery_ok_since = None  # 全缆进界连续起始时刻（300ms 自动清标志）
        self.estop_latched = False
        self._admit_poll = 0
        self.angle_baseline = {16: None, 17: None}
        self._angle_baseline_raw = {16: None, 17: None}
        self._enc_filt_raw = {16: None, 17: None}
        self._axis_filter = {16: WristAxisFilter(), 17: WristAxisFilter()}
        self._pending_target = None
        self.rate_counters = {k: deque() for k in
                              ("enc_raw", "enc_mapped", "servo_abs", "servo_raw", "servo_telem")}

        self._build_channels()
        self._build_ui(default_port)
        self._build_timers()
        self.exportFinished.connect(self._export_done)
        # 标定：默认就可用（k 幅值=结构常数、符号=−trim方向、δ=0），
        # 文件只是**可选覆盖**（换卷筒/换线径/需要 δ 时）。放在布局之后载入，
        # 这样「trim方向」已从布局恢复，符号反推用的是最终值。
        self._load_layout()
        self._load_wrist_calib(quiet=True)

    # ---------- 数据通道 ----------
    def _build_channels(self) -> None:
        for j in range(ENCODER_COUNT):
            self.channels[f"enc_raw_{j}"] = Channel(f"enc_raw_{j}", f"J{j:02d} raw", "磁编码器 raw")
        for m in SERVO_TARGETS:
            self.channels[f"m{m}_abs"] = Channel(f"m{m}_abs", f"M{m} ABS", f"M{m} 位置")
            self.channels[f"m{m}_tgt"] = Channel(f"m{m}_tgt", f"M{m} 目标", f"M{m} 位置")
            self.channels[f"m{m}_raw"] = Channel(f"m{m}_raw", f"M{m} 单圈", f"M{m} 位置")
            self.channels[f"m{m}_speed"] = Channel(f"m{m}_speed", f"M{m} 速度", f"M{m} 遥测")
            self.channels[f"m{m}_load"] = Channel(f"m{m}_load", f"M{m} 负载", f"M{m} 遥测")
            self.channels[f"m{m}_current"] = Channel(f"m{m}_current", f"M{m} 电流", f"M{m} 遥测")
            self.channels[f"m{m}_volt"] = Channel(f"m{m}_volt", f"M{m} 电压V", f"M{m} 遥测")
            self.channels[f"m{m}_temp"] = Channel(f"m{m}_temp", f"M{m} 温度℃", f"M{m} 遥测")
        for i in (1, 2, 3):
            self.channels[f"tension_f{i}"] = Channel(
                f"tension_f{i}", f"C{i} 张力N", "腕部张力")
            # 2026-11-24 用户要求：张力**目标值**与实测值同图对比（力控族三模式都有）
            self.channels[f"tension_f{i}_tgt"] = Channel(
                f"tension_f{i}_tgt", f"C{i} 张力目标N", "腕部张力")
        # 位姿曲线（2026-11-23 用户要求）：roll/pitch 的目标角与当前角同图对比
        self.channels["pose_roll"] = Channel(
            "pose_roll", "ROLL 当前°", "位姿角度")
        self.channels["pose_roll_tgt"] = Channel(
            "pose_roll_tgt", "ROLL 目标°", "位姿角度")
        self.channels["pose_pitch"] = Channel(
            "pose_pitch", "PITCH 当前°", "位姿角度")
        self.channels["pose_pitch_tgt"] = Channel(
            "pose_pitch_tgt", "PITCH 目标°", "位姿角度")
        # 张紧程度 t = f·n̂ 常驻曲线（数据驱动，无需闭环；无 n̂ 位姿记 NaN 断口）
        self.channels["tension_preload"] = Channel(
            "tension_preload", "张紧 t N", "腕部张力")
        # 力控目标/trim 曲线通道（张力·力控模式下绘制目标 vs 实测用）
        for i in (1, 2, 3):
            self.channels[f"force_trim_{i}"] = Channel(
                f"force_trim_{i}", f"C{i} 位置trim", "力控")
        self.channels["force_tau_roll_tgt"] = Channel(
            "force_tau_roll_tgt", "τ 目标 ROLL N·m", "力控")
        self.channels["force_tau_pitch_tgt"] = Channel(
            "force_tau_pitch_tgt", "τ 目标 PITCH N·m", "力控")
        # 实测力矩 τ=R(q)·f：传感器只给张力，真实力矩必须经 R 换算（2026-11-02
        # 用户修复需求）。三力控模式共用，与目标曲线同单位同量程可直接对拍。
        self.channels["force_tau_roll_meas"] = Channel(
            "force_tau_roll_meas", "τ 实测 ROLL N·m", "力控")
        self.channels["force_tau_pitch_meas"] = Channel(
            "force_tau_pitch_meas", "τ 实测 PITCH N·m", "力控")
        # α 饱和缩放系数（TDA）：1=全力矩，<1=目标不可达被打折（论文 §8.3）
        self.channels["force_alpha"] = Channel(
            "force_alpha", "α 缩放", "力控")

    # ---------- 界面 ----------
    def _build_ui(self, default_port: str) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # ---------------- 顶部工具栏（两行分组，统一行高/间距） ----------------
        # 2026-11-24 重排：原来 25 个控件全挤在一行 HBox 里 —— 间距随文字长度乱变、
        # 复选框和按钮基线不齐、最右边「舵机信息」被挤出窗口（窗口最小宽度被顶到
        # 1936px，1366/1600 屏直接看不全）。现在拆两行，每行按语义分组：
        #   ① 连接 / 运行   ② 曲线显示 / 预设 / 独立窗口
        # 行高与控件尺寸由 app_theme 的 QWidget#toolbar 规则统一（26px），
        # 组间用 1px 竖线分隔，组内 8px。
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.addItem(default_port)
        for p in self._list_ports():
            if p != default_port:
                self.port_combo.addItem(p)
        self.port_combo.setMinimumWidth(120)
        bar.addWidget(QLabel("串口"))
        bar.addWidget(self.port_combo)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self._toggle_connect)
        bar.addWidget(self.connect_btn)
        self.pause_btn = QPushButton("暂停曲线")
        self.pause_btn.clicked.connect(self._toggle_pause)
        bar.addWidget(self.pause_btn)
        # 🔒运行优先（2026-11-03）：闭环运行期间 GUI 降一档（60→30FPS），
        # 把 GUI 线程余量让给 100Hz 控制环。**默认不勾**——主图点数自适应后
        # 60FPS 只占 paint 预算一半，不勾也能跑满；勾上是"保险档"。
        self.runprio_check = QCheckBox("🔒运行优先")
        self.runprio_check.setChecked(False)
        self.runprio_check.setToolTip(
            "闭环运行时 GUI 降一档（主图 60→30FPS、表格 60→30Hz、观测台 60→30Hz），\n"
            "把线程余量让给 100Hz 控制环。停环自动恢复全速。\n"
            "曲线数据照常全量记录，只降显示刷新率；勾上后控制环时间抖动最小。")
        self.runprio_check.toggled.connect(lambda _c=False: self._apply_run_prio())
        bar.addWidget(self.runprio_check)
        # 🛡 安全保护总开关：**只作用于闭环**。2026-11-03 用户定案——
        # 直控（点动/Go/斜坡/回零）与一键松绳不做张力检测，张力保护只在闭环。
        self.safety_check = QCheckBox("🛡 安全保护")
        self.safety_check.setChecked(True)          # 安全默认：勾选
        self.safety_check.setToolTip(
            "只影响闭环（直控与一键松绳本来就不做张力检测）：\n"
            "· 张力阈值非法（fmin≥fmax）→ 停环，不放行无保护的闭环\n"
            "· 闭环位置模式每拍限幅（与力控共用 max_step_f）\n"
            "取消勾选 = 以上两项关闭（风险自负，状态栏持续显示 ⚠ 并记入 safety 日志）")
        self.safety_check.toggled.connect(self._on_safety_toggled)
        bar.addWidget(self.safety_check)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_buffers)
        bar.addWidget(self.clear_btn)
        self.export_btn = QPushButton("导出CSV")
        self.export_btn.clicked.connect(self._export_csv)
        bar.addWidget(self.export_btn)
        bar.addStretch(1)

        # ---- 第二行：曲线显示 / 预设 / 独立窗口 ----
        bar2 = QHBoxLayout()
        bar2.setSpacing(8)
        bar2.addWidget(QLabel("窗口"))
        self.window_combo = QComboBox()
        self.window_combo.addItems(["10s", "30s", "60s", "120s"])
        self.window_combo.setCurrentIndex(1)
        bar2.addWidget(self.window_combo)
        # 主图帧率上限（2026-11-24 新增）：60/75/90，即时生效。
        # 数据源只有 100Hz，再高没有新点可画，反会和 drain/表格抢线程。
        bar2.addWidget(QLabel("帧率"))
        self.plot_hz_combo = QComboBox()
        self.plot_hz_combo.addItems(["60", "75", "90"])
        # 环境变量 MMHAND_PLOT_HZ 给了非预设值（如 30）时也如实显示
        _hz_txt = str(int(PLOT_HZ))
        if self.plot_hz_combo.findText(_hz_txt) < 0:
            self.plot_hz_combo.addItem(_hz_txt)
        self.plot_hz_combo.setCurrentText(_hz_txt)
        self.plot_hz_combo.setFixedWidth(64)
        self.plot_hz_combo.setToolTip(
            "主图刷新率上限（FPS）。数据源只有 100Hz（P4 控制周期 10ms）：\n"
            "· 60 = 最省 CPU，一帧约 1.7 个新点\n"
            "· 75 = 默认，一帧约 1.3 个新点\n"
            "· 90 = 接近原生 100Hz，GUI 线程忙时吃不满\n"
            "勾「运行优先」时闭环运行期间减半。改完立即生效，不写存档。")
        self.plot_hz_combo.currentTextChanged.connect(self._set_plot_hz)
        bar2.addWidget(self.plot_hz_combo)
        # 抗锯齿（默认关）：勾上线条明显顺滑，代价是 paint 约 +70%。
        self.aa_check = QCheckBox("抗锯齿")
        self.aa_check.setChecked(False)
        self.aa_check.setToolTip(
            "曲线抗锯齿（默认关）。\n"
            "· 开 = 线条顺滑（高 DPI 下差别明显），但 paint +70%，"
            "帧率高时会掉帧\n"
            "· 关 = 省 CPU，锯齿感重一些\n"
            "只有曲线重绘受影响，数据链不受影响。")
        self.aa_check.toggled.connect(self._set_plot_aa)
        bar2.addWidget(self.aa_check)
        self.xauto_check = QCheckBox("X跟随")
        self.xauto_check.setChecked(True)
        self.xauto_check.setToolTip("X 轴自动跟随最新数据滚动（示波器模式）；取消勾选可手动拖动/缩放")
        bar2.addWidget(self.xauto_check)
        self.yauto_check = QCheckBox("Y自适应")
        self.yauto_check.setChecked(True)
        self.yauto_check.toggled.connect(self._on_yauto_toggled)
        bar2.addWidget(self.yauto_check)
        bar2.addWidget(QLabel("Y限"))
        self._loading_layout = False
        self.ymin_spin = QSpinBox()
        self.ymax_spin = QSpinBox()
        for s, default in ((self.ymin_spin, 0), (self.ymax_spin, 16384)):
            s.setRange(-200000, 200000)
            s.setValue(default)
            s.setFixedWidth(76)
            s.valueChanged.connect(lambda _=0: self._apply_y_limits())
            bar2.addWidget(s)
        self.norm_check = QCheckBox("归一化")
        self.norm_check.setToolTip("每条曲线按窗口内自身 min/max 归一化，解决量纲混画")
        bar2.addWidget(self.norm_check)
        self.abstime_check = QCheckBox("绝对时间")
        self.abstime_check.toggled.connect(self._on_abstime_toggled)
        bar2.addWidget(self.abstime_check)
        bar2.addWidget(QLabel("预设"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["自定义", "腕部调试", "混合调试", "全磁编raw",
                                    "M27-29遥测", "全清"])
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        bar2.addWidget(self.preset_combo)
        self.only_online_check = QCheckBox("只显示在线")
        self.only_online_check.setChecked(True)
        self.only_online_check.toggled.connect(self._refresh_table_visibility)
        bar2.addWidget(self.only_online_check)
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("全局配色：切换立即生效并随布局记住\n自定义=逐槽选色（未设槽继承夜间）")
        self.theme_combo.addItems(list(AT.DISPLAY_NAMES.values()))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        bar2.addWidget(self.theme_combo)
        bar2.addStretch(1)
        # 带宽指示 + 三个独立窗口按钮移到第一行右侧：第二行加了「帧率/抗锯齿」
        # 后单行放不下（整窗最小宽度会被顶到 1500），拆开两边之后两行都约 1100。
        self.bw_label = QLabel("带宽: 全开")
        bar.addWidget(self.bw_label)
        self.rt_btn = QPushButton("📐 张力·R")
        self.rt_btn.setToolTip("R 矩阵 + 腱张力代理量（负载/电流/电压/温度）独立窗口")
        self.rt_btn.clicked.connect(self._toggle_rt_window)
        bar.addWidget(self.rt_btn)
        self.watch_btn = QPushButton("🪟 参数窗")
        self.watch_btn.setToolTip("打开独立参数监视窗口（右键删除块/下拉添加/可置顶）")
        self.watch_btn.clicked.connect(self._toggle_watch_window)
        bar.addWidget(self.watch_btn)
        # 2026-11-20：舵机信息窗（ABS/raw/速度/负载/电流/电压/温度/逻辑行程）
        self.servo_info_btn = QPushButton("🔧 舵机信息")
        self.servo_info_btn.setToolTip(
            "打开舵机信息窗：M27-M29 的 ABS/raw/速度/负载/电流/电压/温度，\n"
            "以及会话逻辑行程 min..max（点「读取行程」向 P4 请求）。\n"
            "可导出 CSV。舵机 EEPROM 里的 P/D/I/力矩限制需要固件支持（暂无）。")
        self.servo_info_btn.clicked.connect(self._toggle_servo_info_window)
        bar.addWidget(self.servo_info_btn)

        bar_host = QWidget()
        bar_host.setObjectName("toolbar")
        bar_v = QVBoxLayout(bar_host)
        bar_v.setContentsMargins(0, 0, 0, 0)
        bar_v.setSpacing(6)
        bar_v.addLayout(bar)
        bar_v.addLayout(bar2)
        root_layout.addWidget(bar_host)

        # 中部：通道树 + 曲线
        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter, 1)

        tree_wrap = QVBoxLayout()
        self.tree_search = QComboBox()
        self.tree_search.setEditable(True)
        self.tree_search.setInsertPolicy(QComboBox.NoInsert)
        self.tree_search.lineEdit().setPlaceholderText("搜索通道…")
        self.tree_search.lineEdit().textChanged.connect(self._filter_tree)
        tree_wrap.addWidget(self.tree_search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("通道（勾选上曲线，双击换色）")
        self.tree.setMinimumWidth(180)
        groups = {}
        color_i = 0
        for ch in self.channels.values():
            if ch.group not in groups:
                g = QTreeWidgetItem([ch.group])
                g.setFlags(g.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                g.setCheckState(0, Qt.Unchecked)
                self.tree.addTopLevelItem(g)
                groups[ch.group] = g
            item = QTreeWidgetItem([ch.name])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, ch.key)
            ch.color = PALETTE[color_i % len(PALETTE)]
            color_i += 1
            groups[ch.group].addChild(item)
            ch.tree_item = item
        self.tree.itemChanged.connect(self._on_tree_changed)
        self.tree.itemDoubleClicked.connect(self._on_tree_double_click)
        tree_wrap.addWidget(self.tree, 1)
        tree_host = QWidget()
        tree_host.setLayout(tree_wrap)
        splitter.addWidget(tree_host)

        self.time_axis = RelativeTimeAxis(orientation="bottom")
        self.plot = _TimedPlotWidget(axisItems={"bottom": self.time_axis})
        self.plot.setMinimumWidth(460)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        # 渲染减压（2026-11-03 卡顿修复）：多通道 100FPS 光栅是 GUI 卡顿主源，
        # 配合 33FPS 门 + 峰值降采样 + 视口裁剪，曲线密度再高也稳。
        _pi = self.plot.getPlotItem()
        _pi.setDownsampling(mode="peak")
        _pi.setClipToView(True)
        # 2026-11-24：抗锯齿默认关（原生窗口实测 +5.4ms paint），
        # 需要更顺滑的线条时勾工具栏「抗锯齿」，见 _set_plot_aa()。
        self.plot.setAntialiasing(False)
        self.legend = self.plot.addLegend(offset=(10, 10))
        self._style_legend()
        self.plot.setLabel("bottom", "时间")
        self.plot.getPlotItem().showButtons()
        # 暂停覆盖标记 / 空图提示：用子 QLabel 贴在图区正中（见 _TimedPlotWidget）
        self.paused_text = QLabel("⏸ 已暂停（点『恢复曲线』继续）")
        self.paused_text.setObjectName("plotHint")
        self.plot.add_overlay(self.paused_text)
        self.paused_text.setVisible(False)
        # 无曲线提示：勾选为空时给出可操作的指引
        self.empty_plot_text = QLabel(
            "曲线区为空：在左侧通道树勾选通道，或用工具栏「预设」一键加载")
        self.empty_plot_text.setObjectName("plotHint")
        self.plot.add_overlay(self.empty_plot_text)
        # 十字游标 + 采样点高亮 + 悬停数值浮层（2026-11-24）
        self.plot.scope = self          # 双击事件回抛（加/删水平标记线）
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen="#888")
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen="#888")
        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.addItem(self.hLine, ignoreBounds=True)
        # 悬停时高亮的"最近采样点"（每条可见曲线一个，颜色同曲线）
        self._hover_dots = pg.ScatterPlotItem(size=7, pen=pg.mkPen(None))
        self._hover_dots.setZValue(96)
        self.plot.addItem(self._hover_dots, ignoreBounds=True)
        # 数值浮层：子 QLabel 贴着鼠标走，比 pg.TextItem 清晰（不受数据坐标缩放）
        self._hover_tip = QLabel(self.plot)
        self._hover_tip.setObjectName("plotTip")
        self._hover_tip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._hover_tip.hide()
        self._h_markers = []            # 双击加的水平标记线
        self._series_color = {}         # 通道名 → 颜色（浮层/高亮点用）
        # 鼠标移动事件每秒可达上百次：限流到 30Hz，避免每个事件都全量扫曲线。
        self._mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved, rateLimit=30, delay=0.04,
            slot=lambda evt: self._on_plot_mouse_moved(evt[0]))
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # 控制面板装进滚动区：窗口高度不再被面板内容撑爆，16:9 尺寸可达。
        # 2026-10-28 面板改两列（左使能/右 M27-29）后加宽：620-680 面板需匹配视口，
        # 横向滚动关闭——宽度不够时控件会被裁（上一版 390 宽即此 bug）。
        panel_scroll = QScrollArea()
        panel_scroll.setWidget(self._build_control_panel())
        panel_scroll.setWidgetResizable(True)
        # 2026-11-24：面板改成"两列 + 固定列宽"后内容最小宽度约 600，视口给
        # 600~720 刚好不裁；整窗最小宽度从 1936 降到 ~1300（1366 屏可用）。
        # 视口必须 ≥ 面板内容最小宽度（622 + 滚动条），否则右侧又被裁。
        panel_scroll.setMinimumWidth(640)
        panel_scroll.setMaximumWidth(760)
        # 2026-11-23：原来强制横向滚动条关闭，视口比内容窄时控件被**裁掉**
        # （用户看到的"框太小、字被挡住"）。改成需要时出现横向滚动条，宁滚不裁。
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        splitter.addWidget(panel_scroll)

        # 底部：数值表
        tables = QSplitter(Qt.Horizontal)
        self.enc_table = QTableWidget(ENCODER_COUNT, 4)
        self.enc_table.setHorizontalHeaderLabels(["通道", "raw", "角度°", "在线"])
        self.enc_table.verticalHeader().setVisible(False)
        self.enc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 4 列铺满整表宽度（原来是 4 个 90px 的窄列 + 一大片空白，看着像没对齐）
        _enc_hdr = self.enc_table.horizontalHeader()
        _enc_hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for _c in range(1, 4):
            _enc_hdr.setSectionResizeMode(_c, QHeaderView.Stretch)
        enc_row_names = {16: "J16 ROLL", 17: "J17 PITCH"}
        for r in range(ENCODER_COUNT):
            self.enc_table.setItem(r, 0, QTableWidgetItem(enc_row_names.get(r, f"J{r:02d}")))
            for c in range(1, 4):
                self.enc_table.setItem(r, c, QTableWidgetItem("-"))
        tables.addWidget(self.enc_table)

        self.servo_table = QTableWidget(len(SERVO_TARGETS), 11)
        self.servo_table.setHorizontalHeaderLabels(
            ["电机", "ABS", "ABS最小", "ABS最大", "单圈", "速度", "负载", "电流", "电压V", "温度℃", "在线"])
        self.servo_table.verticalHeader().setVisible(False)
        self.servo_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # 11 列按内容宽 + 最后一列吃掉余量：不再让「电压/温度/在线」被窗口边缘裁掉
        _srv_hdr = self.servo_table.horizontalHeader()
        _srv_hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        for r, m in enumerate(SERVO_TARGETS):
            self.servo_table.setItem(r, 0, QTableWidgetItem(f"M{m}"))
            for c in range(1, 11):
                self.servo_table.setItem(r, c, QTableWidgetItem("-"))
        tables.addWidget(self.servo_table)
        tables.setStretchFactor(0, 3)
        tables.setStretchFactor(1, 2)
        root_layout.addWidget(tables)

        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel("未连接")
        sb.addWidget(self.status_label)
        self.rate_label = QLabel("")
        sb.addPermanentWidget(self.rate_label)

        # 启动零曲线：默认不勾选任何通道，由用户主动选择（预设/手动勾选）。

    def _build_control_panel(self) -> QWidget:
        """腕部直控面板：左列=使能/状态/急停/归零/步长，右列=M27-M29 电机块（2026-10-28
        应用户要求把 M27-M29 移到"未使能"旁边，两列并排；2026-10-29 把组框标题
        "腕部直控 M27-M29"移入面板，与"● 未使能"同一行）。"""
        box = QGroupBox()
        box.setObjectName("ctrlPanel")
        # 面板宽度按"内容最小宽度"给，不再用 640 硬塞：940 宽的两列被挤成
        # 646 时，右侧的 Go / +500 会被裁成 "Sc"（2026-11-24 用户截图）。
        box.setMinimumWidth(622)
        box.setMaximumWidth(760)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("腕部直控 M27-M29")
        title.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {AT.T('muted')}; padding: 2px;")
        head.addWidget(title)
        self.arm_light = QLabel("● 未使能")
        self.arm_light.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {AT.T('muted')}; padding: 2px;")
        head.addWidget(self.arm_light)
        head.addStretch(1)
        lay.addLayout(head)

        # 两列：左=使能/急停/归零/步长（固定宽，按钮列对齐），右=M27-29 逐绳块（自适应）。
        # 用两个真正的容器 widget（而不是裸 layout）才能锁住左列宽度，让右列所有
        # 电机的 −/+/目标框/Go 共用同一组列边界。
        body = QHBoxLayout()
        body.setSpacing(14)
        lay.addLayout(body)
        left_host = QWidget()
        left_host.setFixedWidth(240)
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        right_host = QWidget()
        right = QGridLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setHorizontalSpacing(6)
        right.setVerticalSpacing(4)
        right.setColumnMinimumWidth(0, 92)
        right.setColumnStretch(1, 0)
        right.setColumnStretch(2, 0)
        right.setColumnStretch(3, 1)
        right.setColumnMinimumWidth(3, 86)
        right.setColumnMinimumWidth(4, 40)
        body.addWidget(left_host, 0, Qt.AlignTop)
        body.addWidget(right_host, 1, Qt.AlignTop)

        self.roll_label = QLabel("ROLL  --.-°")
        self.roll_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {AT.T('accent')}; padding: 0;")
        self.roll_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.pitch_label = QLabel("PITCH --.-°")
        self.pitch_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {AT.T('good')}; padding: 0;")
        self.pitch_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.roll_detail = QLabel("绝对 --.-°  raw --  基准 --")
        self.roll_detail.setObjectName("muted")
        self.pitch_detail = QLabel("绝对 --.-°  raw --  基准 --")
        self.pitch_detail.setObjectName("muted")
        # 数值与自己的说明行紧挨着（原来 4 行是 "ROLL/PITCH/说明/说明"，
        # 两条「无数据」叠在一起看不出是哪根轴）；说明允许换行，别撑宽左列。
        for _w in (self.roll_detail, self.pitch_detail):
            _w.setWordWrap(True)
        left.addWidget(self.roll_label)
        left.addWidget(self.roll_detail)
        left.addWidget(self.pitch_label)
        left.addWidget(self.pitch_detail)
        zero_row = QHBoxLayout()
        zero_row.setSpacing(6)
        tip = "把当前角度记为 0 点参考，Δ 立即归零；随时可按，不影响控制"
        self.zero_roll_btn = QPushButton("ROLL 归零")
        self.zero_roll_btn.setToolTip("ROLL(J16) 零位 = 当前角度。" + tip)
        self.zero_roll_btn.clicked.connect(lambda _=False: self._set_angle_baseline_now(16))
        self.zero_pitch_btn = QPushButton("PITCH 归零")
        self.zero_pitch_btn.setToolTip("PITCH(J17) 零位 = 当前角度。" + tip)
        self.zero_pitch_btn.clicked.connect(lambda _=False: self._set_angle_baseline_now(17))
        self.zero_both_btn = QPushButton("双轴")
        self.zero_both_btn.setToolTip("ROLL+PITCH 同时归零。" + tip)
        self.zero_both_btn.clicked.connect(lambda _=False: self._set_angle_baseline_now(None))
        for b in (self.zero_roll_btn, self.zero_pitch_btn, self.zero_both_btn):
            zero_row.addWidget(b, 1)
        left.addLayout(zero_row)

        self.enable_btn = QPushButton("使能直控（自动归零+保持）")
        self.enable_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.enable_btn.clicked.connect(self._on_enable_direct)
        left.addWidget(self.enable_btn)

        estop_row = QHBoxLayout()
        estop_row.setSpacing(6)
        self.stop_btn = QPushButton("⛔ 急停 STOP")
        self.stop_btn.setToolTip(
            "抢占式下发 STOP：先清空待发运动指令、不等记账。\n"
            "固件收到后**关闭舵机力矩**（不是保持位置）——腕部会松开/下垂，\n"
            "张力随之释放。要重新使能请先按「复位」。")
        self.stop_btn.setStyleSheet(
            f"color: white; background-color: {AT.T('bad')}; font-weight: bold; padding: 8px;")
        self.stop_btn.clicked.connect(self._on_stop)
        estop_row.addWidget(self.stop_btn, 1)
        self.reset_btn = QPushButton("复位")
        self.reset_btn.setFixedWidth(64)
        self.reset_btn.setStyleSheet("padding: 8px;")
        self.reset_btn.setToolTip("清除 E-STOP 锁存与可恢复故障（CMD_RESET）")
        self.reset_btn.clicked.connect(self._on_reset)
        estop_row.addWidget(self.reset_btn)
        left.addLayout(estop_row)
        zero_row = QHBoxLayout()
        zero_row.setSpacing(6)
        self.save_zero_btn = QPushButton("💾 存储零位")
        self.save_zero_btn.setToolTip("记录当前 M27-29 位置与 ROLL/PITCH 编码器零点，存到 wrist_zero.json")
        self.save_zero_btn.clicked.connect(self._save_wrist_zero)
        zero_row.addWidget(self.save_zero_btn, 1)
        self.goto_zero_btn = QPushButton("🎯 回到零位")
        self.goto_zero_btn.setToolTip("斜坡回到上次存储的零位（受 ±5000 软限位约束）")
        self.goto_zero_btn.clicked.connect(self._goto_wrist_zero)
        zero_row.addWidget(self.goto_zero_btn, 1)
        left.addLayout(zero_row)

        # 绳一键操作（PLAN v8.2 D2/D3）：紧绳=TDA 恢复到标准分布；松绳=全放
        rope_row = QHBoxLayout()
        rope_row.setSpacing(6)
        self.tighten_rope_btn = QPushButton("🪢 一键紧绳")
        self.tighten_rope_btn.setToolTip(
            "事务化：切力矩模式→τd=0→预紧=t_tgt→启动闭环（TDA 拉三缆到标准分布\n"
            "t·n̂，f 界内保证；腕会沉降找平衡=分布决定力矩的数学必然）。\n"
            "门禁：已使能∧非闭环∧张力新鲜∧三缆全勾∧n̂全正∧位姿在行程内∧t 可行。\n"
            "失败自动回滚模式/参数。恢复中守卫=现状（过载停环+行程钳位）。\n"
            "会话内故障停环（过载/越界/丢数据等）会弹窗告知原因，并 1Hz 复查\n"
            "紧绳门禁：故障清除后弹窗自动转 ✅可重试。")
        self.tighten_rope_btn.clicked.connect(self._on_tighten_rope)
        rope_row.addWidget(self.tighten_rope_btn, 1)
        self.release_rope_btn = QPushButton("🪢 一键松绳")
        self.release_rope_btn.setToolTip(
            "全部勾选电机按 trim_sign 方向放绳 2500 counts（sign=+1→counts−，\n"
            "sign=−1→counts+；三台 counts↑=收绳口径下即统一放绳）。\n"
            "走斜坡+逐绳门禁；门禁：已使能∧非闭环∧张力新鲜∧trim_sign 合法。")
        self.release_rope_btn.clicked.connect(self._on_release_rope)
        rope_row.addWidget(self.release_rope_btn, 1)
        left.addLayout(rope_row)

        step_row = QHBoxLayout()
        step_row.setSpacing(6)
        step_row.addWidget(QLabel("步长"))
        self.step_combo = QComboBox()
        self.step_combo.addItems(["100", "250", "500", "1000", "2000"])
        self.step_combo.setCurrentIndex(2)
        step_row.addWidget(self.step_combo)
        self.step_combo.setFixedWidth(96)
        step_row.addStretch(1)
        left.addLayout(step_row)
        # 步长快捷档：一键切换（与下拉框同步，按钮文字随选中的档位高亮）
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self.step_preset_btns = []
        for s in ("100", "500", "1000", "2000"):
            b = QPushButton(s)
            b.setCheckable(True)
            b.setMinimumHeight(26)
            b.clicked.connect(lambda _=False, ss=s: self.step_combo.setCurrentText(ss))
            preset_row.addWidget(b, 1)
            self.step_preset_btns.append(b)
        left.addLayout(preset_row)
        self._sync_step_presets()

        self.motor_info = {}
        self.jog_buttons = []
        # 逐电机一行 + 一行状态说明，全部落在同一套列边界上：
        #   col0 使能勾选 | col1 −步长 | col2 +步长 | col3 相对目标输入(拉伸) | col4 Go
        # 原来每台电机是 3 个独立 HBoxLayout，勾选框/按钮/输入框/Go 的宽度各算各的，
        # 三台电机之间、以及同一台的上下行之间都错位（2026-11-24 重排）。
        for i, m in enumerate(SERVO_TARGETS):
            row0 = i * 2
            # 逐绳使能开关：替代原 "Mxx" 标签。缆号按 MOTOR_FOR_CABLE 动态算，
            # 换序时标签跟着换（如 M28·C3）。默认勾选=与旧行为一致，布局持久化。
            cable = self._cable_label(m)
            tag = QCheckBox(f"M{m}" + (f"·{cable}" if cable else ""))
            tag.setChecked(True)
            tag.setMinimumWidth(72)
            tag.setToolTip(
                f"使能开关：勾选后 M{m}" + (f"（拉 {cable} 缆）" if cable else "") +
                "才会被使能并接收命令。\n"
                "未勾选：使能时不纳入活动域/归零/在线检查，点动、Go、回零、闭环\n"
                "一律跳过它、不下发任何命令（扭矩保持现状，复位/急停后断扭）。\n"
                "一根都没勾 → 拒绝使能；闭环运行中改勾选 → 先停闭环。")
            tag.toggled.connect(lambda checked, mm=m: self._on_cable_enable_toggled(mm, checked))
            self.cable_enable_checks[m] = tag
            right.addWidget(tag, row0, 0, Qt.AlignVCenter)
            minus = QPushButton(f"−{self._step()}")
            plus = QPushButton(f"＋{self._step()}")
            self.jog_buttons_by_motor[m] = [minus, plus]
            for b, d, col in ((minus, -1, 1), (plus, 1, 2)):
                b.setMinimumWidth(50)
                b.setAutoRepeat(True)
                b.setAutoRepeatDelay(280)
                b.setAutoRepeatInterval(90)
                b.clicked.connect(lambda _=False, mm=m, dd=d: self._jog(mm, dd * self._step()))
                b.setEnabled(False)
                self.jog_buttons.append(b)
                right.addWidget(b, row0, col)
            # 手动目标行：相对上次目标输入 + Go（回车同效）
            edit = QLineEdit()
            edit.setPlaceholderText(f"M{m} 增量")
            edit.setToolTip(f"M{m} 手动目标：填相对上次目标的 counts 增量，回车或点 Go 发送")
            edit.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhLatinOnly)
            edit.setMinimumWidth(86)
            go = QPushButton("Go")
            go.setFixedWidth(40)
            edit.returnPressed.connect(lambda mm=m, ed=edit: self._send_manual_target(mm, ed))
            go.clicked.connect(lambda _=False, mm=m, ed=edit: self._send_manual_target(mm, ed))
            right.addWidget(edit, row0, 3)
            right.addWidget(go, row0, 4)
            self.target_edits[m] = edit
            self.go_buttons[m] = go
            info = QLabel("未使能")
            info.setStyleSheet(
                f"color: {AT.T('muted')}; font-size: 11px; padding-left: 4px;")
            info.setWordWrap(True)   # 长状态行允许换行，不撑宽右列
            right.addWidget(info, row0 + 1, 0, 1, 5)
            self.motor_info[m] = info
        right.setRowStretch(len(SERVO_TARGETS) * 2, 1)

        def _refresh_jog_labels():
            for b in self.jog_buttons:
                step = self._step()
                b.setText(f"−{step}" if "−" in b.text() else f"＋{step}")
        self.step_combo.currentIndexChanged.connect(lambda _=0: _refresh_jog_labels())
        self.step_combo.currentTextChanged.connect(lambda _=0: self._sync_step_presets())
        _refresh_jog_labels()

        speed_row = QHBoxLayout()
        self.ramp_check = QCheckBox("限速斜坡")
        self.ramp_check.setChecked(True)
        self.ramp_check.setToolTip("点动和 Go 按最大速率每 50 ms 分步发送；连按会累加到斜坡终点")
        speed_row.addWidget(self.ramp_check)
        speed_row.addWidget(QLabel("最大"))
        self.ramp_rate_spin = QSpinBox()
        self.ramp_rate_spin.setRange(100, 50000)
        self.ramp_rate_spin.setValue(3000)
        self.ramp_rate_spin.setSuffix(" c/s")
        self.ramp_rate_spin.setFixedWidth(120)
        speed_row.addWidget(self.ramp_rate_spin)
        speed_row.addStretch(1)
        lay.addLayout(speed_row)
        # 2026-11-20 删掉原来那段「已烧录 2000 steps/s / 与每拍限幅配套」的说明：
        # 舵机速度是**固件常量**（SERVO_TARGET_SPEED_DEFAULT，现 3400），
        # 上位机不发也不读；实测值直接看电机行/舵机信息窗的「速度」列即可。
        lay.addWidget(self._build_closed_loop_panel())

        self.ctrl_status = QLabel("未使能")
        self.ctrl_status.setWordWrap(True)
        self.ctrl_status.setObjectName("muted")
        lay.addWidget(self.ctrl_status)
        self.ctrl_log = QPlainTextEdit()
        self.ctrl_log.setReadOnly(True)
        self.ctrl_log.setMaximumHeight(120)
        self.ctrl_log.setPlaceholderText("控制操作日志")
        lay.addWidget(self.ctrl_log)
        lay.addStretch(1)
        return box

    def _build_closed_loop_panel(self) -> QWidget:
        """负反馈闭环面板：ROLL/PITCH 目标角 -> 系数矩阵 -> M27-29（闭环 100Hz）。

        2026-11-24 重排：原来十几行各是一个独立 QHBoxLayout，标签宽度随文字长度
        变化、输入框被拉伸，每行第一个输入框的 x 坐标都不一样（用户截图里就是
        "对不齐"）。现在每行都是同一套列模板的 QGridLayout：标签列 62px 右对齐
        + 输入列 96px，3 组/行，所有行的列边界共用，纵向严格对齐。
        """
        box = QGroupBox("负反馈闭环 ROLL/PITCH")
        box.setObjectName("clPanel")
        cl = QVBoxLayout(box)
        cl.setContentsMargins(12, 8, 12, 10)
        cl.setSpacing(8)

        _LW, _FW, _GAP = 62, 96, 10
        _PAIRS = 3

        def _p(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setFixedWidth(_LW)
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lb

        def _row_grid() -> QGridLayout:
            """一行参数（≤3 组）：与其它行共用完全一样的列宽，因此纵向对齐。"""
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(_GAP)
            g.setVerticalSpacing(6)
            for c in range(_PAIRS):
                g.setColumnMinimumWidth(2 * c, _LW)
                g.setColumnMinimumWidth(2 * c + 1, _FW)
                g.setColumnStretch(2 * c + 1, 0)
            g.setColumnStretch(_PAIRS * 2, 1)
            return g

        def _add(g: QGridLayout, idx: int, label: str, w) -> QGridLayout:
            """第 idx 组（0..2）→ 标签 + 控件；label="" 时控件直接从标签列起排。"""
            col = 2 * idx
            if label:
                g.addWidget(_p(label), 0, col)
                g.addWidget(w, 0, col + 1)
            else:
                g.addWidget(w, 0, col, 1, 2)
            return g

        # 控制模式：位置（角度闭环）/ 张力·力控（张力闭环 PI → 位置 trim）
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("模式"))
        self.cl_mode_combo = QComboBox()
        for mode, label in (
            ("position", "位置模式（角度闭环）"),
            ("tension", "张力控制（每缆张力闭环）"),
            ("tight", "张紧控制（预紧度闭环）"),
            ("force", "力矩控制（τ 开环 → 张力闭环）"),
            ("impedance", "阻抗控制（位置→力矩，框架）"),
            ("c1_position", "混合控制（复位绳张力 + 双轴角度）"),
        ):
            self.cl_mode_combo.addItem(label, mode)
        self.cl_mode_combo.setToolTip(
            "位置模式：被控量=关节角度（前馈用解析模型绳长 + R·e 校正，需「模型前馈」）。\n"
            "张力控制：被控量=每根缆的张力 N（逐缆 PI→trim），最直观，台架起步用。\n"
            "张紧控制：被控量=预紧程度（沿零空间整体收紧/放松，力矩保持不变）。\n"
            "力矩控制：目标 τ 经分配算 f_d，**再由张力环追 f_d**。\n"
            "  闭合的是「三根绳的张力」；τ 另外有**慢积分修正**（面板「τ修正」，\n"
            "  默认 1.0/s）把 τ* 与实测 R·f 的稳态差补回去——只积分不带 P，\n"
            "  因为 τ 误差本身就是内环的响应，带 P 会和内环打架（2026-11-18 实测振荡）。\n"
            "  填 0 = 纯前馈；补不了 R 模型误差与导管摩擦。\n"
            "力控投入后腕停在当前位姿附近，手掰会顺从回力；角度目标被忽略。\n"
            "混合控制：所选复位绳闭环控张力，另外两根绳闭环控 ROLL/PITCH。\n"
            "切换模式会先停止正在运行的闭环。")
        self.cl_mode_combo.currentIndexChanged.connect(self._on_cl_mode_changed)
        mode_row.addWidget(self.cl_mode_combo, 1)
        cl.addLayout(mode_row)
        self._cl_mode = "position"
        self._force_state = WristForceV2State()     # 力矩模式（v2）
        self._tension_state = WristTensionState()   # 张力模式
        self._c1_position_state = C1TensionState()
        self._c1_angle_state = WristPidState()
        self._hybrid_return_index = 0
        self._c1_position_params = None
        # 混合模式：本拍**实际下发**的目标 (roll°, pitch°, C1 N)。
        # 控制线程每拍写、GUI 60Hz 读 —— 用来画「目标曲线」和更新大字标签。
        # 不用它的话，混控开正弦时屏幕上的目标线一动不动（2026-11-26 实报）。
        self._c1_cmd_tgt = None
        # 2026-11-19：张紧已改为「逐缆绝对目标 f_d=t*·n̂ + 同一个张力环」，
        # 原来的 _tight_state（单标量 PI 的状态）不再使用，删掉。
        self._pos_pid_state = WristPidState()       # 位置环 PID 状态（两种结构共用）
        # 诊断记录（2026-11-19）：20Hz × 25min，供「🔬 诊断 CSV」导出
        self._diag_rows = deque(maxlen=30000)          # 力控/张力：位姿+张力+τ+trim
        self._pos_diag_rows = deque(maxlen=30000)      # 位置：位姿+目标+目标counts+实测
        self._c1_diag_rows = deque(maxlen=30000)
        self._force_base = None             # 进入力控时刻的电机位置基准
        self._force_trim = [0.0, 0.0, 0.0]  # 上次发送的 trim（变更抑制用）
        self._tau_trim = [0.0, 0.0]         # 力矩修正（慢积分外环）的修正量 [N·m]
        # 阻抗 D 项（2026-11-25）：角度差分 + 一阶低通 → 角速度 [deg/s]。
        # 与张力环的 `Kd_f`（误差微分）同一设计口径：**D 作用在测量上**，
        # 目标角阶跃不产生微分kick。`_imp_omega`/`_imp_d_tau` 只供状态行显示。
        self._imp_rate = RateFilter(tau_s=0.03)
        self._imp_omega = (0.0, 0.0)
        self._imp_d_tau = (0.0, 0.0)
        self._auto_t0_pc = None             # 自动调参起点（perf_counter）
        self._force_need_send = False       # 重入首拍强制下发 base（防目标跳变）

        self.cl_roll_now = QLabel("ROLL  --.--°→--.--°")
        self.cl_roll_now.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #64b5f6; padding: 1px;")
        cl.addWidget(self.cl_roll_now)
        self.cl_pitch_now = QLabel("PITCH --.--°→--.--°")
        self.cl_pitch_now.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #81c784; padding: 1px;")
        cl.addWidget(self.cl_pitch_now)

        self._cl_tgt_row_w = QWidget()          # 容器：力控模式下整行隐藏
        tgt_box = QVBoxLayout(self._cl_tgt_row_w)
        tgt_box.setContentsMargins(0, 0, 0, 0)
        tgt_box.setSpacing(4)

        # 行1：目标角 + 分轴闭环开关
        self.cl_edits["roll_tgt"] = self._cl_edit("ROLL目标°")
        self.cl_edits["pitch_tgt"] = self._cl_edit("PITCH目标°")
        # 分轴闭环开关：取消勾选的轴其系数列整体置零（前馈+校正都不作用）
        self.cl_roll_check = QCheckBox("ROLL环")
        self.cl_roll_check.setChecked(True)
        self.cl_roll_check.setToolTip("只闭环 ROLL：kr 系数列置零，Roll 方向不控、随耦合自由漂移")
        self.cl_pitch_check = QCheckBox("PITCH环")
        self.cl_pitch_check.setChecked(True)
        self.cl_pitch_check.setToolTip("只闭环 PITCH：kp 系数列置零，Pitch 方向不控、随耦合自由漂移")
        r1 = _row_grid()
        _add(r1, 0, "ROLL目标", self.cl_edits["roll_tgt"])
        _add(r1, 1, "PITCH目标", self.cl_edits["pitch_tgt"])
        _axis_chk = QHBoxLayout()
        _axis_chk.setSpacing(10)
        _axis_chk.addWidget(self.cl_roll_check)
        _axis_chk.addWidget(self.cl_pitch_check)
        _axis_chk.addStretch(1)
        r1.addLayout(_axis_chk, 0, 4, 1, 3)
        tgt_box.addLayout(r1)

        # 行2：扫掠开关 + 轴 + 频率
        # 2026-11-26 用户要求：**去掉三角波**，扫掠只剩正弦。
        # 原来「三角波 / 正弦波」二选一且默认三角波，频率框因此被禁用，
        # 反复被误当成"频率锁死改不了"。现在没有波形选择，频率永远生效。
        self.sweep_check = QCheckBox("扫掠")
        self.sweep_check.setToolTip(
            "闭环运行中让目标按所选轴自动摆**正弦**（目标框被自动改写）。\n"
            "· 单轴：该轴目标 = 幅值·sin(2πft)\n"
            "· 双轴正弦：ROLL/PITCH 同时按各自幅值同相位摆（中心见「过零对称」）\n"
            "位置模式与**阻抗模式**都能用（阻抗的输入就是目标角 q*）。")
        self.sweep_check.toggled.connect(self._on_sweep_toggled)
        self.sweep_axis = QComboBox()
        self.sweep_axis.addItems(["ROLL", "PITCH", "双轴正弦"])
        self.sweep_axis.setMinimumWidth(92)
        self.sweep_axis.currentIndexChanged.connect(self._on_sweep_axis_changed)
        self.sweep_freq = QDoubleSpinBox()
        self.sweep_freq.setRange(0.01, 5.0)
        self.sweep_freq.setDecimals(2)
        self.sweep_freq.setValue(0.2)
        self.sweep_freq.setSuffix(" Hz")
        self.sweep_freq.setMinimumWidth(84)
        self.sweep_freq.setToolTip(
            "正弦频率 [Hz]，0.01~5。\n"
            "· 0.05~0.2 Hz 看低频跟随；\n"
            "· 0.5 Hz 以上逐步逼近带宽极限（幅度会缩、相位会滞后）。")
        r2 = _row_grid()
        _add(r2, 0, "", self.sweep_check)
        _add(r2, 1, "轴", self.sweep_axis)
        _add(r2, 2, "频率", self.sweep_freq)
        tgt_box.addLayout(r2)

        # 行3：两轴幅值 + 过零对称
        self.sweep_amp = QDoubleSpinBox()
        self.sweep_amp.setRange(0.5, 90.0)
        self.sweep_amp.setDecimals(1)
        self.sweep_amp.setValue(10.0)
        self.sweep_amp.setSuffix("°")
        self.sweep_amp.setMinimumWidth(76)
        self.sweep_amp.setToolTip(
            "ROLL 幅值（峰）°：单轴/双轴都用它。\n"
            "超过「限幅°」时按限幅截断；峰值角速度 = 幅值×2πf。")
        self.sweep_amp_p = QDoubleSpinBox()
        self.sweep_amp_p.setRange(0.5, 90.0)
        self.sweep_amp_p.setDecimals(1)
        self.sweep_amp_p.setValue(5.0)
        self.sweep_amp_p.setSuffix("°")
        self.sweep_amp_p.setMinimumWidth(76)
        self.sweep_amp_p.setToolTip(
            "PITCH 幅值（峰）°：只在「双轴正弦」时用；\n"
            "两轴同相位：roll = 中心 + A_r·sin(2πft)，pitch = 中心 + A_p·sin(2πft)。")
        # 2026-11-23 用户要求：现在扫掠大多只在正半轴（中心偏正），要能跑到正负。
        # 勾「过零」后双轴正弦的中心强制 (0,0)，目标 = ±幅值·sin。
        self.sweep_center0 = QCheckBox("过零对称")
        self.sweep_center0.setChecked(True)
        self.sweep_center0.setToolTip(
            "双轴正弦专用：勾上后中心强制为 (0,0)，目标在 ±幅值 之间往返（正负都到）。\n"
            "取消则用两个目标框里的值当中心（可做偏置扫掠，如中心 +5°）。")
        self.sweep_center0.toggled.connect(lambda _=False: self._sweep_seed())
        r3 = _row_grid()
        _add(r3, 0, "幅值 ROLL", self.sweep_amp)
        _add(r3, 1, "幅值 PITCH", self.sweep_amp_p)
        _add(r3, 2, "", self.sweep_center0)
        # 右侧「生效：…」实时提示（去掉波形选择后仍保留，方便一眼确认参数）
        self.sweep_active_label = QLabel("")
        self.sweep_active_label.setObjectName("muted")
        self.sweep_active_label.setWordWrap(False)
        r3.addWidget(self.sweep_active_label, 0, 6, 1, 4)
        self.sweep_freq.valueChanged.connect(lambda _=0: self._sync_sweep_widgets())
        self.sweep_amp.valueChanged.connect(lambda _=0: self._sync_sweep_widgets())
        self.sweep_amp_p.valueChanged.connect(lambda _=0: self._sync_sweep_widgets())
        tgt_box.addLayout(r3)
        cl.addWidget(self._cl_tgt_row_w)
        self._sync_sweep_widgets()
        self._sweep_phase = 0.0     # 正弦相位（勾选时刻起算）
        self._sweep_center = (0.0, 0.0)   # 双轴正弦的中心（勾选时的目标框）
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(50)   # 20Hz 推进波形
        self._sweep_timer.timeout.connect(self._sweep_tick)
        self._sweep_timer.start()

        # 位置模式只有"模型前馈"一条路：M27/M28/M29 手填系数行已删除
        # （2026-11-03 用户要求）。保留 0 值占位，避免控制律读不到增益。
        self._cl_gain_vals = {m: (0.0, 0.0) for m in SERVO_TARGETS}   # (ROLL系数, PITCH系数)

        self._cl_par_row_w = QWidget()          # 容器：力控模式下隐藏
        par_box = QVBoxLayout(self._cl_par_row_w)
        par_box.setContentsMargins(0, 0, 0, 0)
        par_box.setSpacing(4)
        self.cl_edits["kp"] = self._cl_edit("比例增益（关节角域，无量纲）", text="0.6")
        self.cl_edits["ki"] = self._cl_edit(
            "积分增益 1/s（关节角域）。0=纯PD。\n"
            "稳态误差（模型偏差/重力下垂）靠它吃掉；积分项被钳在「限幅°」×1 以内防 windup。",
            text="0")
        self.cl_edits["kd"] = self._cl_edit(
            "微分增益 s。微分作用在**反馈角速度**上（不是误差跳变），\n"
            "所以拖目标框不会砸出尖峰；反馈已过 76ms EMA，Kd 一般 0~0.05 就够。",
            text="0")
        self.cl_ff_check = QCheckBox("前馈")
        self.cl_ff_check.setChecked(True)
        self.cl_ff_check.setToolTip(
            "勾选 = 启用绳长前馈（按右边 k_ff 缩放）；\n"
            "取消 = 纯 PID（前馈整项不参与，k_ff 框失效）。")
        self.cl_edits["k_ff"] = self._cl_edit(
            "绳长前馈系数 0~1：\n"
            "  1   = 完全按模型给前馈（l(θ*)−l(θ_fb) 全量折 counts）\n"
            "  0.3 = 只借 30% 的模型量，模型偏差也只放大 30%\n"
            "  0   = 不用前馈（纯 PID）\n"
            "模型/标定可信就给 1；不确定先从 0.2~0.3 试，看同样 kp 下\n"
            "超调/静差是否变好，再逐步往上加。",
            text="0.3")
        p1 = _row_grid()
        _add(p1, 0, "Kp", self.cl_edits["kp"])
        _add(p1, 1, "Ki", self.cl_edits["ki"])
        _add(p1, 2, "Kd", self.cl_edits["kd"])
        par_box.addLayout(p1)

        self.cl_edits["deadband"] = self._cl_edit("死区°", text="0.3")
        self.cl_edits["limit"] = self._cl_edit("目标角限幅°", text="25")
        # 2026-11-23 方案 B：分轴每拍限幅（counts/拍）。0 = 不单独限，仍用「每拍限幅」兜底。
        self.cl_edits["max_step_r"] = self._cl_edit(
            "ROLL 轴每拍限幅 [counts/拍]：把 ROLL 的前馈+PI 贡献单独钳住。\n"
            "0 = 不用分轴限幅（仍受下面「每拍限幅」约束）。", text="0")
        self.cl_edits["max_step_p"] = self._cl_edit(
            "PITCH 轴每拍限幅 [counts/拍]：pitch 的 J 约为 roll 的 2.4 倍，\n"
            "同样 counts 下角度更小，可单独给大一点。0 = 不用分轴限幅。", text="0")
        p2 = _row_grid()
        _add(p2, 0, "", self.cl_ff_check)
        _add(p2, 1, "前馈系数", self.cl_edits["k_ff"])
        _add(p2, 2, "死区°", self.cl_edits["deadband"])
        par_box.addLayout(p2)
        p3 = _row_grid()
        _add(p3, 0, "限幅°", self.cl_edits["limit"])
        _add(p3, 1, "ROLL每拍", self.cl_edits["max_step_r"])
        _add(p3, 2, "PITCH每拍", self.cl_edits["max_step_p"])
        par_box.addLayout(p3)
        cl.addWidget(self._cl_par_row_w)

        # 每拍限幅（位置模式与力控三模式共用；所有模式都显示这一行）
        # 2026-11-20：tooltip 只留"这个框到底是什么"，删掉所有关于舵机速度的历史假设
        # （曾写"配舵机 2000 steps/s"，而固件常量已经变过 1000→2000→3400，那种说法必然过时）。
        self._cl_step_row_w = QWidget()
        _step_v = QVBoxLayout(self._cl_step_row_w)
        _step_v.setContentsMargins(0, 0, 0, 0)
        self.cl_edits["max_step_f"] = self._cl_edit(
            "每拍最大位置增量 [counts/拍]，位置模式与三个力控模式共用。\n"
            "命令速率 = 本值 × 控制频率（本机 100 Hz → 20×100 = 2000 c/s）。\n"
            "实际速度还受伺服跟踪与目标值（目标 − 实测）大小限制，不是本值直接决定；\n"
            "速度天花板在舵机固件里（SERVO_TARGET_SPEED_DEFAULT=3400 c/s），上位机不设。\n"
            "⚠ 本值是**位置领先量**，不是速度：舵机看到的误差恒等于它，速度 ≈ 13.35×本值\n"
            "（20→267 c/s，120→1600 c/s，≈255 才打满 3400）。所以\n"
            "· 想快 → **给大一点**（34 只有 454 c/s，是能力的 13%）\n"
            "· 过冲大 → 先降 Kp；降本值会同时变慢\n"
            "━━ 逐缆填写（2026-11-24）：可填 1 个数（三缆共用）或 3 个数"
            "（逗号分隔，按 C1,C2,C3），例如 `34,34,20`。\n"
            "原因：某根缆的导管更涩/更松时，允许它单独走快一点。",
            text="20")
        s1 = _row_grid()
        _add(s1, 0, "每拍限幅", self.cl_edits["max_step_f"])
        step_hint = QLabel("counts/拍（控制频率 100Hz）")
        step_hint.setObjectName("muted")
        s1.addWidget(step_hint, 0, 2, 1, 5)
        _step_v.addLayout(s1)
        cl.addWidget(self._cl_step_row_w)
        # 2026-11-20 定案：不设「速度上限」框 —— 速度天花板在**舵机固件内部**
        # （SERVO_TARGET_SPEED_DEFAULT），上位机不发也不该假装能设。
        # 这里只保留「每拍限幅」这一个旋钮；命令速率 = count/拍 × 频率 由启动自检
        # `_check_cmd_authority` 在状态行提示（只提示，不改值）。

        self._cl_model_row_w = QWidget()        # 容器：力控模式下隐藏
        model_row = QHBoxLayout(self._cl_model_row_w)
        model_row.setContentsMargins(0, 0, 0, 0)
        self.cl_load_btn = QPushButton("📥 重载标定（可选）")
        self.cl_load_btn.setToolTip(
            "默认已用内建标定（k=结构常数、符号=−trim方向、δ=0），**不需要按**。\n"
            "只有换卷筒/换线径，或要用识别脚本生成的 wrist_calib.json 覆盖时才按：\n"
            "读取 run_data/scope_exports/wrist_calib.json")
        self.cl_load_btn.clicked.connect(lambda: self._load_wrist_calib())
        model_row.addWidget(self.cl_load_btn)
        # 位置环结构（2026-11-23 定案：**绳长前馈 + PI，每拍限幅**）：
        #   ① 前馈 k·[l(θ*)−l(θ_now)]（绳长→counts）
        #   ② PI   J·δθ（关节角域）
        #   ③ out = 本拍实测 + (①+②)
        #   ④ 限幅：本拍步长（out − 实测）最多 ±max_step_f（实测不动目标也不动）
        pos_loop_label = QLabel("位置环：PID+前馈（绳长前馈 + PI，每拍限幅）")
        pos_loop_label.setObjectName("muted")
        pos_loop_label.setToolTip(
            "每拍：\n"
            "  ① 前馈：k_ff · k·[l(目标角) − l(当前角)]  → counts（k_ff=0~1，模型可信度）\n"
            "  ② PI  ：J·δθ，δθ = kp·e + ki∫e + kd·(−dθ_fb/dt)\n"
            "  ③ 目标 counts = 本拍实测 + ① + ②\n"
            "  ④ 限幅：每拍步长（目标 − 实测）最多 ±「每拍限幅」；\n"
            "     实测不动时目标也不动（不会一直累加）\n"
            "· 前馈当前关闭：等效位置增益 ≈ kp，kp 建议 0.2~0.5\n"
            "· e 进死区（0.3°）后 PI 不再修正 → 原地保持\n"
            "· 必须载入标定（k 与 R）")
        model_row.addWidget(pos_loop_label, 1)
        cl.addWidget(self._cl_model_row_w)
        self.cl_calib_label = QLabel("标定：未载入（模型前馈不可用）")
        self.cl_calib_label.setObjectName("muted")
        self.cl_calib_label.setWordWrap(True)
        cl.addWidget(self.cl_calib_label)

        # ---- 力控参数行 ×3 模式 + 公共行（三力控模式共享方向/限幅/下限）----
        # 力矩模式（v2 论文式：τ_d + 预紧 + 解耦校正 + TDA 分配）
        self._cl_force_row_w = QWidget()
        _force_v = QVBoxLayout(self._cl_force_row_w)
        _force_v.setContentsMargins(0, 0, 0, 0)
        _force_v.setSpacing(6)
        self.cl_edits["tau_roll"] = self._cl_edit(
            "期望 ROLL 力矩 N·m（正=收ROLL方向）", text="0.0")
        self.cl_edits["tau_pitch"] = self._cl_edit(
            "期望 PITCH 力矩 N·m", text="0.0")
        self.cl_edits["preload"] = self._cl_edit(
            "预紧**下限** N（不是设定值）：实际 t = max(该力矩所需最小值, 本值)。\n"
            "· 填 0 = 完全由力矩反解（等价论文口径）\n"
            "· 实测 1~2 N 不影响力矩能力；≥10 N 开始压低能力\n"
            "· 状态行 t=…N↑ 表示被抬起（说明本值不够大）", text="1.0")
        self.cl_edits["alpha_cap"] = self._cl_edit(
            "α 上限（安全系数）：力矩最多给「本方向的百分之几」。\n"
            "· 1.0 = 对齐论文（力矩能出多少就出多少，贴着张力边界跑）\n"
            "· 0.9 = 留 10% 余量（推荐日常用）\n"
            "状态行 α=… 是**算出来的**实现比例，本框只封顶。", text="1.0")
        # 2026-11-24：**力矩修正（慢积分外环）**增益。这是唯一稳定的"力矩闭环"形式。
        self.cl_edits["tau_ki"] = self._cl_edit(
            "力矩修正增益 [1/s]（**慢积分外环**，把「τ* − 实测τ」的稳态差补回去）。\n"
            "· 填 0 = 关闭（纯前馈，推荐先 0 验证，再开）\n"
            "· 1.0 = 约 1 s 补一个时间常数（推荐起步）\n"
            "· **不要填大**：τ 误差的响应就是张力内环的响应（10~30 ms），\n"
            "  外环带 P 或增益太大 → 和内环打架 → 2026-11-18 就是这么振的。\n"
            "修正量上限 ±" + f"{TAU_TRIM_MAX:g}" + " N·m（常量 TAU_TRIM_MAX）", text="0")
        f1 = _row_grid()
        _add(f1, 0, "τd ROLL", self.cl_edits["tau_roll"])
        _add(f1, 1, "τd PITCH", self.cl_edits["tau_pitch"])
        _add(f1, 2, "预紧N↓", self.cl_edits["preload"])
        _force_v.addLayout(f1)
        f2 = _row_grid()
        _add(f2, 0, "α上限", self.cl_edits["alpha_cap"])
        _add(f2, 1, "τ修正", self.cl_edits["tau_ki"])
        _force_v.addLayout(f2)
        # 2026-11-23 用户定案：删掉「αmin」框 —— 目标超能力时**始终给到可行最大**，
        # 只做 1 s 限频告警（状态行 + 安全事件 TORQUE_ALPHA_DERATED），不拒绝启动。
        # 2026-11-19 清理：Kp_τ / Ki_τ 两个框已删除（力矩 PI 外环不存在了，
        # τ_d 直接进 TDA）。内环增益统一用「Kp_f / Ki_f」。
        self._cl_force_row_w.setVisible(False)
        cl.addWidget(self._cl_force_row_w)

        # 阻抗模式（2026-11-22 框架）：位置误差 → 力矩 → 复用②整条链
        # τ* = K(q*−q) + D(q̇*−q̇) + τ_ff；τ_ff 暂为 0（待补重力前馈）。
        self._cl_imp_row_w = QWidget()
        _imp_v = QVBoxLayout(self._cl_imp_row_w)
        _imp_v.setContentsMargins(0, 0, 0, 0)
        _imp_v.setSpacing(6)
        self.cl_edits["k_roll"] = self._cl_edit(
            "ROLL 刚度 [N·m/rad]：偏离目标角就产生回中力矩。\n"
            "· K=0 → 退化成纯力矩控制（τ=τ_ff）\n"
            "· 本机力矩能力 ~0.43(roll)/0.50~1.44(pitch) N·m ⟹ K ≲ 1.5 较安全\n"
            "· 想要更硬请用「位置模式」（缆弹性刚度 4.3/20 N·m/rad）", text="0.5")
        self.cl_edits["k_pitch"] = self._cl_edit(
            "PITCH 刚度 [N·m/rad]（同上）", text="0.5")
        self.cl_edits["d_roll"] = self._cl_edit(
            "ROLL 阻尼 [N·m/(rad/s)]（2026-11-25 起**已接线**）：\n"
            "· 角速度由 J16/J17 磁编差分 + 一阶低通（τ=30 ms）得到，\n"
            "  状态行会显示 `ω=[…]°/s` 与 `D·ė=[…]N·m`，调 D 时看这两个数。\n"
            "· D 作用在**测量**上（目标角阶跃不产生微分 kick）。\n"
            "· 填 0 = 无阻尼（可能回中过冲）。起步建议先 K 后 D，D 从 0.01~0.05 试。\n"
            "· 若腕静止时 `ω` 读数在 ±1°/s 内抖动属正常；>±5°/s 说明编码器有跳变。",
            text="0.0")
        self.cl_edits["d_pitch"] = self._cl_edit(
            "PITCH 阻尼 [N·m/(rad/s)]（同上）", text="0.0")
        # 2026-11-23：**直接输入 τ_ff**（常量偏置）—— 你给参数就用这个，
        # 不用采点。实际 τ_ff = 标定表插值 + 这里两个常量。
        self.cl_edits["tau_ff_r"] = self._cl_edit(
            "ROLL 重力力矩幅值 A [N·m]（**90° 处的值**，自动取反）。\n"
            "模型（串列：roll 是外轴）：\n"
            "  τ_ff_roll  = −A_r·sin(roll)\n"
            "  τ_ff_pitch = −A_p·sin(pitch)·cos(roll)   ← roll 转动会削弱 pitch\n"
            "· roll=±90° 时 pitch 力矩为 0（pitch 轴与重力平行）\n"
            "· A 填负值 = 翻转方向\n"
            "例：90° 时实测量得 0.3 N·m → 本框填 0.3", text="0.3")
        self.cl_edits["tau_ff_p"] = self._cl_edit(
            "PITCH 重力力矩幅值 A [N·m]（90° 处；自动取反；会乘 cos(roll)）",
            text="0.3")
        i1 = _row_grid()
        _add(i1, 0, "K ROLL", self.cl_edits["k_roll"])
        _add(i1, 1, "K PITCH", self.cl_edits["k_pitch"])
        _add(i1, 2, "D ROLL", self.cl_edits["d_roll"])
        _imp_v.addLayout(i1)
        i2 = _row_grid()
        _add(i2, 0, "D PITCH", self.cl_edits["d_pitch"])
        _add(i2, 1, "τff ROLL", self.cl_edits["tau_ff_r"])
        _add(i2, 2, "τff PITCH", self.cl_edits["tau_ff_p"])
        _imp_v.addLayout(i2)
        # 2026-11-26：**阻抗自己的死区框**。
        # 原来阻抗的 `deadband_deg` 读的是位置模式那个 `deadband` 框，而那个框
        # 所在的「角度参数」行在阻抗模式下整行隐藏 → 阻抗的死区根本改不了。
        # 留空 = 沿用位置模式的 `deadband`（行为与旧版完全一致）。
        self.cl_edits["imp_deadband"] = self._cl_edit(
            "阻抗角度死区 °（**留空 = 沿用位置模式「角度参数」行的「死区」框**）。\n"
            "· |e| ≤ 死区 时该项力矩置 0，抑制编码器噪声/回中抖动；\n"
            "· 填 0 = 无死区；填值 = 只用这个值，不再看位置模式那个框。",
            text="")
        i3 = _row_grid()
        _add(i3, 0, "死区°", self.cl_edits["imp_deadband"])
        _imp_v.addLayout(i3)
        _imp_hint = QLabel("K 单位 N·m/rad，D 单位 N·m/(rad/s)，τff 为 90° 重力力矩幅值；目标角用上方「ROLL目标 / PITCH目标」")
        _imp_hint.setObjectName("muted")
        _imp_hint.setWordWrap(True)
        _imp_v.addWidget(_imp_hint)
        self._cl_imp_row_w.setVisible(False)
        cl.addWidget(self._cl_imp_row_w)

        # ---- 三力控模式共用的内环增益 + 积分上限（2026-11-24 从张力行里搬出来）----
        # 这三个框力矩模式**本来就在用**（`_force_params_v2` 读 kp_f / ki_f / i_term_lim），
        # 之前却被塞在「张力模式专用」行里：切到力矩模式整行隐藏 → 用户看不到、
        # 也改不了实际生效的积分上限。现在独立成行，张力/张紧/力矩/阻抗四个模式都显示。
        self._cl_loop_row_w = QWidget()
        _loop_v = QVBoxLayout(self._cl_loop_row_w)
        _loop_v.setContentsMargins(0, 0, 0, 0)
        _PER_CABLE_NOTE = ('\n━━ 逐缆填写（2026-11-24）：本框可填 **1 个数**（三缆共用）或 **3 个数**（逗号分隔，按 C1,C2,C3），例如 `15,15,8`。\n三根缆的摩擦/绳长/预紧不同，一套增益不可能同时最优；个数不是 1/3 或含非法值 → 拒绝开环（不会拿错增益去驱动电机）。')
        self.cl_edits["kp_f"] = self._cl_edit(
            "内环P增益 counts/N（三个力控模式共用）：1 N 误差 → Kp counts/拍。\n"
            "整定依据：Kp ≈ (0.2~0.5)/S，S 由标定 k 与绳刚度 K 换算。"
            + _PER_CABLE_NOTE, text="15")
        self.cl_edits["ki_f"] = self._cl_edit(
            "内环I增益 counts/(N·s)（三个力控模式共用）。积分**允许一直累积**"
            "（不再按饱和闸门冻结），累积量由右边「积分上限」封顶，"
            "所以 Ki 只决定攒多快：\n"
            "Ti=Kp/Ki 属常规区间；给小了反向回不来，给大了抖。"
            + _PER_CABLE_NOTE, text="20")
        # 2026-11-20 用户定案：积分**只留一个累积上限**，放界面可调。
        # 界面上这个数**就是输出上限**（counts），不是状态上限：
        #   输出上限 = 本值 [counts]
        #   状态上限 = 本值 / Ki [N·s]（由 _incr_step 自动换算，不需要另外设）
        # 填 0 = 关闭积分（退化成纯 P）。
        self.cl_edits["i_term_lim"] = self._cl_edit(
            "积分**输出**上限 [counts] —— 三个力控模式（力矩/张力/张紧）共用，\n"
            "阻抗模式走的也是这条内环，同样吃它：\n"
            "· 填 20 ⟹ 积分最多贡献 20 counts（≈0.93 N 等效偏置）\n"
            "· ⚠ 这里填的是**输出**，不是累积状态；Ki 不再乘一次\n"
            "· 内部状态上限自动 = 本值 ÷ Ki（例：20÷20 = 1.0 N·s）\n"
            "· 填 0 = 关闭积分（纯 P）\n"
            "积分允许一直累积（含饱和期），只有这个上限在封它。"
            "（2026-11-24 前它只在「张力控制」模式显示，力矩模式看不到。）"
            + _PER_CABLE_NOTE,
            text="20")
        l1 = _row_grid()
        _add(l1, 0, "Kp_f", self.cl_edits["kp_f"])
        _add(l1, 1, "Ki_f", self.cl_edits["ki_f"])
        _add(l1, 2, "积分上限", self.cl_edits["i_term_lim"])
        _loop_v.addLayout(l1)
        # 速度阻尼 D 项（2026-11-24）：原料 = 舵机回传的 Present Speed。
        # 2026-11-25 用户定案：**Kd_f 就是标准 PID 的 D（误差微分）**。
        # 原来的"速度阻尼"（用舵机 Present Speed）**已彻底删除**。
        self.cl_edits["kd_f"] = self._cl_edit(
            "**误差微分 D —— Kd_f [s]**（标准 PID 的 D 项，三个力控模式共用）：\n"
            "    u = Kp·e + Ki·∫e + Kd·d e/dt\n"
            "· e = 目标张力 − 实测张力 [N]，`de/dt` 先做一阶低通（α=0.3，τ≈30 ms）\n"
            "· **0 = 关闭**（默认）。误差在减小时 `de/dt<0` → D 为负 → **自动刹车**，\n"
            "  所以物理上它就是阻尼：抑制「到顶还在冲」的过冲。\n"
            "· 参考起点：`Kd ≈ 0.05~0.1 × Kp/15`，即 Kp=15 → 0.05；Kp=25 → 0.08。\n"
            "· 太大 → 对张力噪声敏感（曲线变毛、舵机嗡嗡）；先小步加，看超调是否单调下降。\n"
            "· D 内部限幅 ±" + f"{D_TERM_MAX_FRAC:g}" + "×每拍限幅，填错量级也不会失控。"
            + _PER_CABLE_NOTE,
            text="0")
        l1b = _row_grid()
        _add(l1b, 0, "Kd_f", self.cl_edits["kd_f"])
        _loop_v.addLayout(l1b)
        self._cl_loop_row_w.setVisible(False)
        cl.addWidget(self._cl_loop_row_w)

        # 张力模式（每缆独立张力目标；增益/积分上限已挪到上面的公共行）
        self._cl_tension_row_w = QWidget()
        _ten_v = QVBoxLayout(self._cl_tension_row_w)
        _ten_v.setContentsMargins(0, 0, 0, 0)
        _ten_v.setSpacing(6)
        self.cl_edits["f1_tgt"] = self._cl_edit(
            "C1 张力目标 N", text="2.0")
        self.cl_edits["f2_tgt"] = self._cl_edit(
            "C2 张力目标 N", text="2.0")
        self.cl_edits["f3_tgt"] = self._cl_edit(
            "C3 张力目标 N", text="2.0")
        t1 = _row_grid()
        _add(t1, 0, "C1目标N", self.cl_edits["f1_tgt"])
        _add(t1, 1, "C2目标N", self.cl_edits["f2_tgt"])
        _add(t1, 2, "C3目标N", self.cl_edits["f3_tgt"])
        _ten_v.addLayout(t1)
        # ---- 正弦跟随测试（2026-11-24 用户要求）：张力模式下目标 = 基值 + A·sin(2πft+φ)
        # 用来测**张力内环的动态响应**（幅频/相频/跟随误差）。
        t2 = _row_grid()
        self.cl_tension_sine_check = QCheckBox("正弦跟随")
        self.cl_tension_sine_check.setToolTip(
            "张力模式专用：把三缆目标改成\n"
            "    f_target_i = 基值_i + sign_i · A · sin(2π·f·t + φ)\n"
            "其中 基值 = 上面三个「C目标N」，A/频率/相位/符号见右侧。\n"
            "· t 从**勾上的那一刻**算起，所以起点在 sin(0)=0，不会跳变\n"
            "· 共模（sign=1,1,1）测张力环本身；差动（1,−1,−1）测 roll 差分\n"
            "· 只影响目标，安全闸门（过载/过期/病态）全部照常生效\n"
            "· 取消勾选立刻回到常数目标（同样不跳变，因为积分状态连续）")
        self.cl_edits["sine_amp"] = self._cl_edit(
            "正弦幅度 A [N]：目标在「基值 ±A」之间摆。\n"
            "注意 A ≤ min(基值−f_min, f_max−基值)，否则会撞界（程序会夹住并提示）。",
            text="1.0")
        self.cl_edits["sine_hz"] = self._cl_edit(
            "正弦频率 f [Hz]：0.05~5。\n"
            "· 0.1~0.5 Hz 看跟随精度（准静态）\n"
            "· 1~2 Hz 看相位滞后/幅值衰减（内环带宽）\n"
            "· >3 Hz 基本只能看趋势（舵机 3400 counts/s 上限）",
            text="0.5")
        self.cl_edits["sine_phase"] = self._cl_edit(
            "相位 φ [deg]：三缆共用的初相。0 = 从 0 开始涨。", text="0")
        self.cl_edits["sine_sign"] = self._cl_edit(
            "每缆符号（±1，逗号分隔）——决定共模还是差动：\n"
            "  1,1,1   = 共模（三缆一起摆，纯张力环测试）\n"
            "  1,-1,-1 = 差动（C2/C3 反向，产生 roll 力矩摆动）\n"
            "  1,1,-1  = 部分差动（观察耦合）",
            text="1,1,1")
        _add(t2, 0, "幅度N", self.cl_edits["sine_amp"])
        _add(t2, 1, "频率Hz", self.cl_edits["sine_hz"])
        _add(t2, 2, "相位°", self.cl_edits["sine_phase"])
        self.cl_tension_sine_check.toggled.connect(self._on_tension_sine_toggled)
        t2.addWidget(self.cl_tension_sine_check, 0, 7, 1, 2)
        # 2026-11-24：**自动调参**——一次起环跑完全部工况（阶跃 + 5 个正弦频率），
        # 数据自动落盘成 run_data/sine/*.csv，事后离线算 PID 指标。
        self.cl_auto_tune_check = QCheckBox("自动调参")
        self.cl_auto_tune_check.setToolTip(
            "🤖 自动调参序列（张力模式）：起环后自动跑完，无需手动改目标。\n"
            + wrist_autotune.summary_text() + "\n"
            "· 阶跃：1.5 → 5.5 N 保持 8 s，再 5.5 → 1.5 N 保持 8 s\n"
            "· 正弦：A=4 N、基值 5 N（范围 1~9，**最低 1 N**）、"
            "f=0.1/0.2/0.3/0.4/0.5 Hz\n"
            "· 三缆给同一目标（共模）→ 三套 PID 在完全相同激励下比较\n"
            "· 数据写 run_data/sine/，带 stage/kind 两列，便于分档分析\n"
            "· 与「正弦跟随」互斥：勾这个就不用勾那个\n"
            "· 全程受安全闸门保护（过载/传感器异常/病态位姿照常停环）")
        self.cl_auto_tune_check.toggled.connect(self._on_auto_tune_toggled)
        t2.addWidget(self.cl_auto_tune_check, 0, 9, 1, 2)
        # 2026-11-25：**自动迭代轮数** —— 每轮跑 110 s，结束后自动按指标改增益并再跑，
        # 直到轮数用完或指标收敛（每缆 kp 变化 <4%、itl <8%、kd <0.008）。
        self.cl_edits["auto_rounds"] = self._cl_edit(
            "🤖 自动调参**循环轮数**（1~6，默认 3）。\n"
            "每轮 110 s（预紧 12s + 阶跃 2×8s + 正弦 5 档 82s），结束后\n"
            "程序**自己**根据本轮指标改 kp/ki/i_term_lim/kd，然后立刻再跑一轮：\n"
            "· 超调 >50% → 该缆 kp×0.80、kd+0.04\n"
            "· 超调 30~50% → kp×0.88、kd+0.02\n"
            "· 超调 <12% 且 0.3Hz 幅值比 <0.92 → kp×1.10\n"
            "· 稳态差 >6% → i_term_lim×1.4（超 10% 再 ki×1.15）\n"
            "· 收敛（kp<4%、itl<8%、kd<0.008 变化）→ 提前结束\n"
            "⚠ 全程受安全闸门保护；随时按「停止闭环」即中止，数据已存。",
            text="3")
        t2.addWidget(QLabel("轮数"))
        t2.addWidget(self.cl_edits["auto_rounds"])
        _ten_v.addLayout(t2)
        t3 = _row_grid()
        _add(t3, 0, "符号", self.cl_edits["sine_sign"])
        _ten_v.addLayout(t3)
        self._cl_tension_row_w.setVisible(False)
        cl.addWidget(self._cl_tension_row_w)

        self._cl_c1_position_row_w = QWidget()
        hybrid_layout = QVBoxLayout(self._cl_c1_position_row_w)
        hybrid_layout.setContentsMargins(0, 0, 0, 0)
        hybrid_layout.setSpacing(8)
        self._c1_position_edits = {}
        self._hybrid_tension_labels = {}

        return_group = QGroupBox("复位绳张力控制")
        angle_group = QGroupBox("角度绳位置控制")
        sine_group = QGroupBox("混合正弦设置")
        return_grid = QGridLayout(return_group)
        angle_grid = QGridLayout(angle_group)
        sine_grid = QGridLayout(sine_group)
        for group, grid in ((return_group, return_grid), (angle_group, angle_grid),
                            (sine_group, sine_grid)):
            grid.setContentsMargins(10, 10, 10, 10)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(6)
            for column in range(3):
                grid.setColumnMinimumWidth(2 * column, 76)
                grid.setColumnMinimumWidth(2 * column + 1, 96)
            grid.setColumnStretch(6, 1)
            hybrid_layout.addWidget(group)

        def _add_hybrid_fields(grid, fields, offset=0):
            for i, (key, label, default, tooltip) in enumerate(fields, offset):
                row, column = divmod(i, 3)
                lb = QLabel(label)
                lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                grid.addWidget(lb, row, 2 * column)
                edit = self._cl_edit(tooltip, text=default)
                self._c1_position_edits[key] = edit
                grid.addWidget(edit, row, 2 * column + 1)
                if key.startswith("c1_pos_"):
                    self._hybrid_tension_labels[key] = (lb, label)
            return (offset + len(fields) + 2) // 3

        self.cl_return_cable_combo = QComboBox()
        for i, motor in enumerate(MOTOR_FOR_CABLE, 1):
            self.cl_return_cable_combo.addItem(f"C{i} / M{motor}")
        self.cl_return_cable_combo.setToolTip("停环后选择复位绳。张力反馈取观测台映射到该绳的实测通道。")
        self.cl_return_cable_combo.currentIndexChanged.connect(self._on_hybrid_return_changed)
        return_grid.addWidget(QLabel("复位绳"), 0, 0, Qt.AlignRight)
        return_grid.addWidget(self.cl_return_cable_combo, 0, 1)
        _add_hybrid_fields(return_grid, (
            ("c1_pos_target", "C1 目标 N", "5", "复位绳张力目标，单位 N。"),
            ("c1_pos_max_n", "C1 上限 N", "25", "复位绳实测张力达到上限时停环。"),
            ("c1_pos_kp", "C1 Kp", "5", "复位绳张力比例增益，单位 counts/N。"),
            ("c1_pos_ki", "C1 Ki", "0", "复位绳张力积分增益，单位 counts/(N·s)。"),
            ("c1_pos_kd", "C1 Kd", "0", "复位绳张力反馈微分增益，单位 counts·s/N。"),
            ("c1_pos_ff", "C1 前馈", "0", "按实测姿态补偿复位绳的绳路变化，系数 0~1。"),
            ("c1_pos_step", "C1 步长", "5", "复位绳距实测位置的单拍增量上限，单位 counts。"),
            ("c1_pos_travel", "C1 行程 ±c", "3000", "复位绳相对启动实测位置的行程，单位 counts。"),
            ("c1_pos_i_limit", "C1 积分上限", "5", "复位绳积分项最大贡献，单位 counts。"),
            ("c1_pos_min_n", "C1 下限 N", "0.2", "用于校验复位绳张力目标。"),
        ), offset=1)
        defaults = self._hybrid_tension_fields()
        self._hybrid_tension_profiles = [dict(defaults) for _ in MOTOR_FOR_CABLE]

        ff_row = _add_hybrid_fields(angle_grid, (
            ("roll_tgt", "Roll 目标 °", "", "留空启动时用该轴实测角度。"),
            ("pitch_tgt", "Pitch 目标 °", "", "留空启动时用该轴实测角度。"),
            ("pos_limit", "目标限幅 °", "25", "混合模式两轴目标角限幅。"),
            ("pos_kp", "默认角 Kp", "0.2", "下方留空的逐绳角度 Kp 使用该值。"),
            ("pos_ki", "默认角 Ki", "0", "下方留空的逐绳角度 Ki 使用该值，单位 1/s。"),
            ("pos_kd", "角度 Kd", "0", "角度微分增益，单位 s。"),
            ("pos_step", "角度绳步长", "5", "角度绳距实测位置的单拍增量上限，单位 counts。"),
            ("pos_deadband", "角度死区 °", "0.3", "混合模式角度误差死区。"),
        ))
        self._hybrid_ff_checks = (QCheckBox("Roll 前馈"), QCheckBox("Pitch 前馈"))
        for axis, (check, key) in enumerate(zip(self._hybrid_ff_checks, ("pos_ff", "pos_ff_pitch"))):
            check.setChecked(True)
            check.setToolTip("只切换该轴的绳长前馈，角度 PI 继续工作。")
            check.toggled.connect(self._save_layout)
            angle_grid.addWidget(check, ff_row, axis * 2, Qt.AlignRight)
            coefficient = self._cl_edit("该轴的绳长前馈系数 0~1。填 0 时该轴无前馈补偿。")
            coefficient.editingFinished.connect(self._save_layout)
            self._c1_position_edits[key] = coefficient
            angle_grid.addWidget(coefficient, ff_row, axis * 2 + 1)

        pi_grid = QGridLayout()
        for column, title in enumerate(("逐绳角度 PI", "Roll Kp", "Roll Ki", "Pitch Kp", "Pitch Ki")):
            pi_grid.addWidget(QLabel(title), 0, column)
        self._hybrid_pi_edits = []
        self._hybrid_pi_labels = []
        for i, motor in enumerate(MOTOR_FOR_CABLE):
            name = QLabel(f"C{i + 1} / M{motor}")
            self._hybrid_pi_labels.append(name)
            pi_grid.addWidget(name, i + 1, 0)
            row = []
            for column in range(1, 5):
                edit = self._cl_edit("此绳在该轴上的角度增益。留空使用上方对应默认增益。",
                                     text="")
                edit.setPlaceholderText("默认")
                edit.editingFinished.connect(self._save_layout)
                pi_grid.addWidget(edit, i + 1, column)
                row.append(edit)
            self._hybrid_pi_edits.append(row)
        angle_grid.addLayout(pi_grid, ff_row + 1, 0, 1, 6)
        self._show_hybrid_return_selection()

        self.cl_c1_sine_check = QCheckBox("混合正弦")
        self.cl_c1_sine_check.setToolTip(
            "复位绳张力和关节角度使用下方的正弦参数。幅值为 0 时保持该目标。\n"
            "两路共用一个时间零点，数据保存到 run_data/sine/。")
        self.cl_c1_sine_check.toggled.connect(
            lambda on: self._on_c1_test_toggled(on, self.cl_c1_auto_check))
        sine_grid.addWidget(self.cl_c1_sine_check, 0, 0, 1, 4, Qt.AlignLeft)
        _add_hybrid_fields(sine_grid, (
            ("c1_sine_sign", "张力符号", "1", "复位绳张力正弦符号，+1 或 −1。"),
            ("c1_sine_amp", "张力幅度 N", "3", "复位绳张力正弦幅度，填 0 保持恒张力。"),
            ("c1_sine_hz", "张力频率 Hz", "0.25", "复位绳张力正弦频率。"),
            ("c1_sine_phase", "张力相位 °", "0", "复位绳张力正弦相位，−360~360°。"),
            ("ang_sine_roll", "Roll 幅值 °", "0", "Roll 正弦幅值，填 0 保持 Roll 目标。"),
            ("ang_sine_pitch", "Pitch 幅值 °", "0", "Pitch 正弦幅值，填 0 保持 Pitch 目标。"),
            ("ang_sine_hz", "角度频率 Hz", "0.2", "Roll 与 Pitch 共用的角度正弦频率。"),
        ), offset=2)
        self.cl_c1_auto_check = QCheckBox("混合自动调参")
        self.cl_c1_auto_check.setToolTip(
            "一次起环跑完整序列，并把每档数据落盘。\n"
            + hybrid_autotune.summary_text().replace("C1", "复位绳")
            + "\n自动调参更新所选绳的张力参数和默认角度 Kp/Ki。逐绳填写的增益由你调节。")
        self.cl_c1_auto_check.toggled.connect(
            lambda on: self._on_c1_test_toggled(on, self.cl_c1_sine_check))
        hybrid_test_row = QHBoxLayout()
        auto_rounds = self._cl_edit("混合自动调参轮数，1~6。", text="3")
        self._c1_position_edits["c1_auto_rounds"] = auto_rounds
        for widget in (self.cl_c1_auto_check, QLabel("调参轮数"), auto_rounds):
            hybrid_test_row.addWidget(widget)
        hybrid_test_row.addStretch(1)
        hybrid_layout.addLayout(hybrid_test_row)
        self._cl_c1_position_row_w.setVisible(False)
        cl.addWidget(self._cl_c1_position_row_w)

        # 张紧模式（零空间预紧单旋钮，τ 守恒）
        self._cl_tight_row_w = QWidget()
        _tight_v = QVBoxLayout(self._cl_tight_row_w)
        _tight_v.setContentsMargins(0, 0, 0, 0)
        # 2026-11-18 合并：与力矩模式的「预紧N」是同一个量（n̂·f）。
        # 这里只做只读镜像，真正读的是 cl_edits["preload"]。
        self.cl_edits["t_tgt"] = self._cl_edit(
            "【只读镜像】= 力控行的「预紧N」（n̂·f）。\n"
            "2026-11-18 合并：张紧的 t* 与力矩的 preload_n 是同一个物理量，\n"
            "现在统一在「预紧N」里改，这里只显示。", text="5.0")
        self.cl_edits["t_tgt"].setReadOnly(True)
        # 镜像联动：改「预紧N」→ 立刻反映到「张紧N」（单向，避免回环）
        self.cl_edits["preload"].textChanged.connect(
            lambda txt: self.cl_edits["t_tgt"].setText(txt))
        self.cl_edits["t_tgt"].setText(self.cl_edits["preload"].text())
        # 2026-11-19 清理：Kp_t / Ki_t 两个框已删除（三个力控模式共用
        # 「Kp_f / Ki_f」，同一根绳、同一个执行器、同一个 S）。
        _t1 = _row_grid()
        _add(_t1, 0, "张紧N", self.cl_edits["t_tgt"])
        _tight_v.addLayout(_t1)
        self._cl_tight_row_w.setVisible(False)
        cl.addWidget(self._cl_tight_row_w)

        # 公共行（三力控模式共享：方向符号 / trim 限幅）
        self._cl_force_common_row_w = QWidget()
        _fc_v = QVBoxLayout(self._cl_force_common_row_w)
        _fc_v.setContentsMargins(0, 0, 0, 0)
        self.cl_edits["trim_sign"] = self._cl_edit(
            "trim→张力方向，逐电机逗号分隔（+1=counts增大⇒该缆张力增大，−1=反向）。\n"
            "修正口径（2026-10-29 更正）：三台 counts↑=收绳 → 全 +1。\n"
            "三种力控模式共用；换接线后请点动复核（+100c 看该缆张力升/降）；\n"
            "错填=正反馈飞车（上电前务必核对）",
            text="1,1,1")
        self.cl_edits["max_trim"] = self._cl_edit(
            "位置微调限幅 counts", text="3000")
        _fc = _row_grid()
        _add(_fc, 0, "trim方向", self.cl_edits["trim_sign"])
        _add(_fc, 1, "trim限幅", self.cl_edits["max_trim"])
        _fc_v.addLayout(_fc)
        self._cl_force_common_row_w.setVisible(False)
        cl.addWidget(self._cl_force_common_row_w)

        # 边界行（三力控模式共用）：逐缆 f 界 + 张紧 t 界 + 双向力矩 τ 界。
        # 留空=0=不启用（t_min/t_max/τr/τp）；fmax 为力控 f_max 唯一来源
        # （观测台守卫框独立服务位置模式观测，互不干扰）。
        # 2026-11-26：**fmin/fmax 单独一行，位置模式也显示**。
        # 原因：位置模式每拍都跑 `_tension_guard`（张力过载 → 停环），阈值就是
        # 这两个框；它们原来在「边界」行里、位置模式下整行隐藏 → 过载阈值改不了。
        self._cl_flim_row_w = QWidget()
        _fl_v = QHBoxLayout(self._cl_flim_row_w)
        _fl_v.setContentsMargins(0, 0, 0, 0)
        self._fl_v = _fl_v
        self.cl_edits["f_min"] = self._cl_edit(
            "逐缆张力下限 N（TDA 分配下界；松绳告警仍由观测台守卫负责）", text="0.5")
        self.cl_edits["fmax_f"] = self._cl_edit(
            "逐缆张力上限 N（**位置模式也用它做过载停环阈值**；唯一来源，"
            "观测台守卫框只管观测）", text="30")
        _fl = _row_grid()
        _add(_fl, 0, "fmin", self.cl_edits["f_min"])
        _add(_fl, 1, "fmax", self.cl_edits["fmax_f"])
        _fl_hint = QLabel("张力界 —— 不只是力控用，**位置模式也靠它做过载停环**")
        _fl_hint.setObjectName("muted")
        _fl.addWidget(_fl_hint, 0, 2, 1, 5)
        _fl_v.addLayout(_fl)
        self._cl_flim_row_w.setVisible(False)
        cl.addWidget(self._cl_flim_row_w)

        # 边界行（2026-11-26 起只剩张紧/力矩相关，fmin/fmax 已移到上面那行）
        self._cl_bound_row_w = QWidget()
        _bd_v = QVBoxLayout(self._cl_bound_row_w)
        _bd_v.setContentsMargins(0, 0, 0, 0)
        _bd_v.setSpacing(6)
        self.cl_edits["t_min"] = self._cl_edit(
            "张紧 t 下限 N，低于则⚠预紧丢失（留空=不启用）", text="")
        self.cl_edits["t_max"] = self._cl_edit(
            "张紧 t 上限 N：超出⚠预紧超限，且张紧目标被钳到此值（留空=不启用）", text="")
        self.cl_edits["tau_r_max"] = self._cl_edit(
            "τ ROLL 目标钳制 ±N·m（**留空=不启用，推荐留空**）。\n"
            "⚠ 这是**按轴独立剪制**：剪的是某一个轴 → 会**改变力矩方向**\n"
            "  （例：请求 (0.3,−1.5) 方向 −78.7°，若本框填 0.2 → 变成 −82.4°）。\n"
            "「做不做得到」由分配层的 α 统一处理（按比例缩、方向不变），\n"
            "所以这里**只在你确实要单向硬限幅时才填**。", text="")
        self.cl_edits["tau_p_max"] = self._cl_edit(
            "τ PITCH 目标钳制 ±N·m（同上；**留空=不启用**）", text="")
        self.cl_edits["roll_tau_sign"] = self._cl_edit(
            "**力矩链的 roll 方向开关**：填 1（默认，按模型）或 −1（整条链翻一次）。\n"
            "作用范围：下发的 τ_roll 与显示的实测 τ_roll **同时**翻转，两者永远同号。\n"
            "什么时候要翻：力控里给正 roll 力矩、腕却往反方向走 → 填 −1。\n"
            "⚠ 只翻力矩，不动角度链路（角度符号由 MODEL_AXIS_SIGN 固定）。",
            text="1")
        b1 = _row_grid()
        _add(b1, 0, "tmin", self.cl_edits["t_min"])
        _add(b1, 1, "tmax", self.cl_edits["t_max"])
        _bd_v.addLayout(b1)
        b2 = _row_grid()
        _add(b2, 0, "τr上限", self.cl_edits["tau_r_max"])
        _add(b2, 1, "τp上限", self.cl_edits["tau_p_max"])
        _add(b2, 2, "τ方向", self.cl_edits["roll_tau_sign"])
        _bd_v.addLayout(b2)
        self._cl_bound_row_w.setVisible(False)
        cl.addWidget(self._cl_bound_row_w)

        # 张力串口/守卫 UI 在张力·R 观测台（RTensionWindow）内。
        self.cl_record_check = QCheckBox("⏺ 记录标定数据")
        self.cl_record_check.setToolTip(
            "闭环运行时按 100Hz 记录 t/角度/M27-29 ABS/张力 + R/τ/trim/ω/flags 到 CSV；\n"
            "取消勾选或停止闭环时落盘（run_data/scope_exports/），\n"
            "随后离线识别：python -m tools.identify_wrist_calib <csv>")
        self.cl_record_check.toggled.connect(self._on_record_toggled)
        cl.addWidget(self.cl_record_check)

        self.cl_btn = QPushButton("▶ 启动闭环")
        self.cl_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        self.cl_btn.clicked.connect(self._toggle_closed_loop)
        cl.addWidget(self.cl_btn)
        self.cl_status = QLabel("未启动（先「载入标定」并勾选「模型前馈」）")
        self.cl_status.setObjectName("muted")
        self.cl_status.setWordWrap(True)
        cl.addWidget(self.cl_status)
        # 2026-11-26：构建完立刻按当前模式刷一次可见性。
        # 否则「布局里没有 cl_mode」（首次启动/存档损坏）时，各行的初始可见状态
        # 就停在构造时的默认值 —— 表现是"某个框该显示却不显示"（fmin 就踩过）。
        try:
            self._apply_cl_mode_visibility()
        except Exception:
            pass
        return box

    @staticmethod
    def _cl_edit(tooltip: str, text: str = "0") -> QLineEdit:
        e = QLineEdit(text)
        e.setToolTip(tooltip)
        e.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhLatinOnly)
        # 2026-11-23：框太小把字裁掉了（数字上下/左右被切）。统一放大到
        # 能完整显示「-10.00」这类值，并居中显示。
        # 2026-11-24：宽度也统一（96px），否则每行第一个框的 x 坐标都不一样。
        e.setFixedWidth(96)
        e.setAlignment(Qt.AlignCenter)
        return e

    def _cl_fval(self, key: str, default: float, lo: float, hi: float):
        """读闭环参数框 → float（钳到 [lo, hi]）。

        2026-11-20：控制线程独立后，**工作线程不再碰控件** —— 它读 GUI 侧
        每 50 ms 生成的文本快照 `_cl_snap`；GUI 线程仍直接读控件（测试同路径）。
        """
        snap = getattr(self, "_cl_snap", None)
        text = None
        if snap is not None and not self._in_gui_thread():
            text = snap.get(key)
        if text is None:
            try:
                text = self.cl_edits[key].text()
            except (KeyError, AttributeError):
                return default
        try:
            v = float(text.strip().replace("−", "-"))
        except (ValueError, AttributeError):
            return default
        return max(lo, min(hi, v))

    def _cl_fval3(self, key: str, default, lo: float, hi: float):
        """读闭环参数框 → **逐缆 3 值**列表（2026-11-24）。

        支持两种填法（同一框，不用多开三个框）：

            "15"       → [15, 15, 15]
            "15,15,8"  → [15, 15, 8]      # C1/C2=15, C3=8

        非法（个数不对/非数字/超界）→ 返回 `None`，由调用方拒绝启动
        （宁可不开环，也不拿错增益去驱动电机）。

        与 `_cl_fval` 同一条"工作线程读快照、GUI 线程读控件"的通道。
        """
        snap = getattr(self, "_cl_snap", None)
        text = None
        if snap is not None and not self._in_gui_thread():
            text = snap.get(key)
        if text is None:
            try:
                text = self.cl_edits[key].text()
            except (KeyError, AttributeError):
                text = None
        return parse_per_cable(text, default, lo, hi, name=key)

    def _step(self) -> int:
        return int(self.step_combo.currentText())

    def _sync_step_presets(self) -> None:
        cur = self.step_combo.currentText()
        for b in getattr(self, "step_preset_btns", []):
            b.setChecked(b.text() == cur)
            b.setStyleSheet("font-weight: bold;" if b.text() == cur else "")

    def _ctrl_status(self, text: str, log: bool = True) -> None:
        self.ctrl_status.setText(text)
        if log:
            stamp = time.strftime("%H:%M:%S")
            self.ctrl_log.appendPlainText(f"[{stamp}] {text}")
            # 日志上限，防止无限增长
            doc = self.ctrl_log.document()
            if doc.blockCount() > 200:
                self.ctrl_log.setPlainText("\n".join(
                    self.ctrl_log.toPlainText().splitlines()[-150:]))

    def _reject(self, gate: str, reason: str, recheck=None) -> None:
        """门禁拒绝统一出口（2026-11-09）：状态行(持久) + GATE_REJECT 取证 + 居中弹窗。

        - 文案保持各门禁原文（测试断言/习惯不变）；
        - recheck：零参纯读 callable，返回 None=条件已满足 / str=仍不满足的
          原因；供弹窗 1Hz 复查（用户定案做①）。必须无副作用。
        - 弹窗语义见 RejectDialog docstring：不锁主窗、不自动消失、合并防风暴。
        """
        self._ctrl_status(reason, log=True)
        self._safety("GATE_REJECT", gate=gate, reason=reason)
        dlg = self._reject_dlg
        if dlg is None:
            dlg = self._reject_dlg = RejectDialog(self)
        dlg.push(gate, reason, recheck)

    def _send_bytes(self, data: bytes) -> bool:
        if self.rx_thread is None:
            self._ctrl_status("未连接")
            return False
        ok = self.rx_thread.send(data)
        if not ok:
            self._ctrl_status("串口发送失败")
        return ok

    PRESETS = {
        "腕部调试": ["enc_raw_16", "enc_raw_17", "m27_abs", "m28_abs", "m29_abs",
                     "m27_tgt", "m28_tgt", "m29_tgt",
                     "tension_f1", "tension_f2", "tension_f3", "tension_preload",
                     # 2026-11-24：三缆目标张力（与实测成对显示）
                     "tension_f1_tgt", "tension_f2_tgt", "tension_f3_tgt",
                     "force_tau_roll_tgt", "force_tau_pitch_tgt",
                     "force_tau_roll_meas", "force_tau_pitch_meas", "force_alpha",
                     "force_trim_1", "force_trim_2", "force_trim_3"],
        # 2026-11-26：混合模式专用预设 —— 位姿四线 + C1 张力（目标/实测）+ 三电机目标。
        # 原来默认预设里**没有** pose_*，混合模式要看「角度目标 vs 实测」时
        # 得自己去树里翻，很容易漏（用户实报：混控下看不到 ROLL/PITCH 曲线）。
        "混合调试": ["pose_roll", "pose_roll_tgt", "pose_pitch", "pose_pitch_tgt",
                     "tension_f1", "tension_f1_tgt",
                     "m27_tgt", "m28_tgt", "m29_tgt",
                     "force_trim_1", "force_trim_2", "force_trim_3"],
        "全磁编raw": [f"enc_raw_{j}" for j in range(ENCODER_COUNT)],
        "M27-29遥测": [f"m{m}_{f}" for m in SERVO_TARGETS for f in ("temp", "volt", "load")],
        "全清": [],
    }

    def _apply_preset(self, index: int) -> None:
        name = self.preset_combo.currentText()
        keys = self.PRESETS.get(name)
        if keys is None:
            return
        if name == "混合调试":
            role = f"tension_f{self._hybrid_return_index + 1}"
            keys = [role if key == "tension_f1" else
                    f"{role}_tgt" if key == "tension_f1_tgt" else key for key in keys]
        for ch in self.channels.values():
            ch.tree_item.setCheckState(0, Qt.Checked if ch.key in keys else Qt.Unchecked)

    def _filter_tree(self, text: str) -> None:
        text = text.strip().lower()
        for ch in self.channels.values():
            hide = bool(text) and text not in ch.name.lower() and text not in ch.group.lower()
            ch.tree_item.setHidden(hide)
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            has_visible = any(not group.child(j).isHidden() for j in range(group.childCount()))
            group.setHidden(bool(text) and not has_visible)
            group.setExpanded(not text or has_visible)

    @staticmethod
    def _list_ports():
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports() if not p.description.startswith("Bluetooth")]
        except Exception:
            return []

    def _build_timers(self) -> None:
        self.drain_timer = QTimer(self)
        self.drain_timer.setTimerType(Qt.PreciseTimer)
        self.drain_timer.timeout.connect(self._timed_slot("drain", self._drain_queue))
        self.drain_timer.start(10)  # 100 FPS
        # 绘图与排空解耦：排空只管喂数据，绘图按自己的节拍取最新缓冲。
        # 绘图帧率（工具栏「帧率」下拉可改；PLOT_HZ 只是启动默认值）
        self._plot_hz = float(PLOT_HZ)
        self._plot_interval_ms = int(PLOT_INTERVAL_MS)
        self.plot_timer = QTimer(self)
        self.plot_timer.setTimerType(Qt.PreciseTimer)
        self.plot_timer.timeout.connect(self._timed_slot("plot", self._plot_tick))
        self.plot_timer.start(self._plot_interval_ms)
        self.table_timer = QTimer(self)
        self.table_timer.setTimerType(Qt.PreciseTimer)
        self.table_timer.timeout.connect(self._timed_slot("table", self._update_tables))
        self.table_timer.start(16)  # 60 Hz（差分刷新，实测 0.15ms/拍，拉满不心疼）
        self.rate_timer = QTimer(self)
        self.rate_timer.timeout.connect(self._update_status)
        self.rate_timer.start(1000)
        # 遥测心跳（仅 MMHAND_TELEMETRY 生效）：50ms 一拍，量事件循环最大停顿。
        if TELEMETRY_PATH:
            self._tele_timer = QTimer(self)
            self._tele_timer.setTimerType(Qt.PreciseTimer)
            self._tele_timer.timeout.connect(self._tele_beat)
            self._tele_timer.start(50)
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._send_heartbeat)
        self.heartbeat_timer.start(500)
        # 归零轮询：等待 SYSTEM_STATUS 清多圈未知位。
        self._zero_timer = QTimer(self)
        self._zero_timer.timeout.connect(self._on_zero_poll)
        # 限速斜坡：分步逼近目标。
        self._ramp_timer = QTimer(self)
        self._ramp_timer.setTimerType(Qt.PreciseTimer)
        self._ramp_timer.timeout.connect(self._on_ramp_tick)
        # 使能准入确认轮询。
        self._admit_timer = QTimer(self)
        self._admit_timer.timeout.connect(self._on_admit_poll)
        self._enable_delay = QTimer(self)
        self._enable_delay.setSingleShot(True)
        self._enable_delay.timeout.connect(self._finish_enable_start)
        # 负反馈闭环 100Hz。
        self._cl_timer = QTimer(self)
        self._cl_timer.timeout.connect(self._cl_tick)
        # 2026-11-19：控制环改由独立线程驱动（见 _ClLoopThread）。
        # `_cl_timer` 保留但**不再启动**（外部/测试仍可引用与 .stop()）。
        self._gui_thread_id = threading.get_ident()
        self._ui_queue = deque()          # 工作线程 → GUI 线程的 UI 动作队列
        self._cl_stop_request = None      # 工作线程自停标志（非 None 即停）
        self._cl_loop = None              # 当前 _ClLoopThread 实例
        self._cl_tick_count = 0           # 控制拍计数（各模式分支共用，__init__ 就给初值）
        self._ui_drain_timer = QTimer(self)
        self._ui_drain_timer.timeout.connect(self._drain_ui_queue)
        self._ui_drain_timer.start(20)    # GUI 侧每 20ms 执行一次投递动作
        # 闭环参数快照：GUI 线程 50 ms 一次，工作线程只读（不在工作线程碰控件）
        self._cl_param_ts = 0.0
        self._cl_snap = None              # GUI 侧文本/勾选快照（工作线程只读）
        self._cl_snapshot_timer = QTimer(self)
        self._cl_snapshot_timer.timeout.connect(self._refresh_cl_param_cache)
        self._cl_snapshot_timer.start(50)

    def _send_heartbeat(self) -> None:
        if self.connected and self.rx_thread is not None:
            self.rx_thread.send(build_host_heartbeat_cmd())

    # ---------- 串口 ----------
    def _toggle_connect(self) -> None:
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        port = self.port_combo.currentText().strip()
        self.rx_queue = queue.Queue()
        self.rx_thread = SerialRxThread(port, self.rx_queue)
        self.rx_thread.start()
        self._connect_port = port
        self._connect_deadline = time.monotonic() + 2.0
        self.connect_btn.setEnabled(False)
        self.status_label.setText(f"正在连接 {port} …")
        QTimer.singleShot(20, self._connect_poll)

    def _connect_poll(self) -> None:
        """非阻塞连接轮询：串口打开/失败/超时都在定时器里处理，不卡 GUI。"""
        t = self.rx_thread
        if t is None:
            self.connect_btn.setEnabled(True)
            return
        if t.error is not None:
            self.status_label.setText(f"连接失败: {t.error}")
            self.rx_thread = None
            self.connect_btn.setEnabled(True)
            return
        if t.serial is None:
            if time.monotonic() < self._connect_deadline:
                QTimer.singleShot(20, self._connect_poll)
            else:
                self.status_label.setText("连接超时")
                t.stop_event.set()
                self.rx_thread = None
                self.connect_btn.setEnabled(True)
            return
        self.connected = True
        self.status_info.clear()
        self._overload_motors.clear()
        self._status_rx_at = 0.0
        self.last_servo_abs_all = None
        self._set_arm_light()
        self.t0 = None
        # 新会话从空白开始：清曲线缓冲与频率统计，避免跨会话残留。
        for ch in self.channels.values():
            ch.buf.clear()
        for dq in self.rate_counters.values():
            dq.clear()
        self._latest_t = None
        self._update_plot()
        self.connect_btn.setText("断开")
        self.connect_btn.setEnabled(True)
        self.status_label.setText(f"已连接 {self._connect_port} @ {BAUDRATE}")
        self.bw_label.setText("带宽: 精简(+遥测+单圈)")
        # 只保留示波器需要的上行流，腾出带宽（P4 重启后自动恢复全开）。
        mask_cmd = (bytes([PROTOCOL_HEADER, 1 + 1 + 4, CMD_UPLINK_MASK]) +
                    struct.pack(">I", SCOPE_UPLINK_MASK) + bytes([0xFF]))
        if self.rx_thread is not None:
            self.rx_thread.send(mask_cmd)

    def _disconnect(self) -> None:
        was_armed = self.armed or self._admit_timer.isActive() or self._enable_delay.isActive()
        self._cancel_direct_motion("断开连接")
        if self.rx_thread is not None:
            if was_armed:
                self.rx_thread.send(build_stop_cmd())
            # 恢复全开，避免官方上位机后续连接时缺遥测流。
            restore = (bytes([PROTOCOL_HEADER, 1 + 1 + 4, CMD_UPLINK_MASK]) +
                       struct.pack(">I", UPLINK_MASK_ALL_PERIODIC) + bytes([0xFF]))
            self.rx_thread.send(restore)
            self.rx_thread.stop_event.set()
            # 不再同步等 2 s：串口写阻塞时会把 GUI 一起拖死。
            self.rx_thread.join(timeout=0.3)
            self.rx_thread = None
        self.connected = False
        self.status_info.clear()
        self._overload_motors.clear()
        self._set_arm_light()
        self.connect_btn.setText("连接")
        self.connect_btn.setEnabled(True)
        self.bw_label.setText("带宽: 全开")

    # ---------- 数据入缓冲 ----------
    def _drain_queue(self) -> None:
        had_data = False
        for _ in range(4000):
            try:
                item = self.rx_queue.get_nowait()
            except queue.Empty:
                break
            had_data = True
            kind = item[0]
            if kind == "error":
                self.status_label.setText(f"串口错误: {item[1]}")
                self._disconnect()
                return
            t, payload = item[1], item[2]
            if self.t0 is None:
                self.t0 = t
                global SCOPE_WINDOW_T0
                SCOPE_WINDOW_T0 = time.time()
            rel = t - self.t0
            self._latest_t = rel
            if kind in self.rate_counters:
                self.rate_counters[kind].append(rel)
            if kind == "enc_raw":
                for j, v in enumerate(payload):
                    self.channels[f"enc_raw_{j}"].buf.append(rel, v)
                    if j in (16, 17):
                        self._encoder_filter_update(j, v)
            elif kind == "servo_abs":
                for i, m in enumerate(SERVO_TARGETS):
                    self.channels[f"m{m}_abs"].buf.append(rel, payload[i])
            elif kind == "servo_raw":
                for i, m in enumerate(SERVO_TARGETS):
                    self.channels[f"m{m}_raw"].buf.append(rel, payload[i])
            elif kind == "servo_telem":
                for field in ("speed", "load", "current", "volt", "temp"):
                    for i, m in enumerate(SERVO_TARGETS):
                        self.channels[f"m{m}_{field}"].buf.append(rel, payload[field][i])
            elif kind == "status":
                previous = self._p4_overload_reason()
                self.status_info = payload
                self._status_rx_at = t
                self._handle_p4_status(previous)
            elif kind == "overload":
                previous = self._p4_overload_reason()
                self._overload_motors = payload
                self._handle_p4_status(previous)
            elif kind == "ack":
                # ACK 节流（2026-11-02 张力模式卡死根修）：力控高频命令每条招回
                # 一帧 ACK，逐条刷状态+写日志会把 GUI 线程刷死（日志一过上限，
                # 每条 ACK 触发整篇文档重写 ×600/s）。改为：OK 不进日志、1s 最多
                # 提示 1 条；拒绝（status≠0）立即提示但同样 1s 限 1 条。
                cmd, status, _state = payload
                if rel - getattr(self, "_ack_last_rel", -1.0) < 1.0:
                    continue
                self._ack_last_rel = rel
                if status == 0:
                    self._ctrl_status(f"ACK 0x{cmd:02X}: OK（高频节流显示）", log=False)
                else:
                    status_txt = {1: "状态拒绝", 2: "已入队", 3: "缺Manual",
                                  4: "数据非法", 6: "Manual CRC不符",
                                  7: "缺标定"}.get(status, str(status))
                    self._ctrl_status(f"⚠ ACK 0x{cmd:02X}: {status_txt}")
            elif kind == "route":
                self.route_info = payload
            elif kind == "servo_range":
                # 2026-11-20：30 路会话逻辑行程（响应 CMD_STATE_SYNC_REQUEST bit2）
                self.servo_range = payload
            elif kind == "servo_abs_all":
                self.last_servo_abs_all = payload
        # 数据已进缓冲：只置脏标记，由 plot_timer 按 PLOT_HZ 取最新数据重绘。
        if had_data:
            self._plot_dirty = True

    # ---------- 绘图 ----------
    def _on_tree_changed(self, item, col):
        if col != 0:
            return
        key = item.data(0, Qt.UserRole)
        if key is None:
            return
        ch = self.channels.get(key)
        if ch is None:
            return
        checked = item.checkState(0) == Qt.Checked
        if checked and ch.curve is None:
            ch.curve = self.plot.plot(
                # 1.2px：150% 缩放下 1px 线会有一半像素被插值糊掉，1.2 更清楚；
                # antialias 走全局 pg 配置（见文件头 setConfigOptions）。
                pen=pg.mkPen(ch.color, width=1.2),
                name=ch.name,
                # 点数由 _update_plot 自己保峰抽稀控制（见 peak_decimate）；
                # 再让 pyqtgraph 自动降采样只会多一遍 O(n) 处理，白花时间。
                downsample=1,
                autoDownsample=False,
            )
        elif not checked and ch.curve is not None:
            self.plot.removeItem(ch.curve)
            ch.curve = None
        # 勾/取消通道后立刻重算 Y 范围（否则要等下一个 0.25s 节流窗口，
        # 刚勾上的第二条曲线会短暂落在量程外）
        self._y_follow_at = 0.0
        self._update_plot()

    def _on_tree_double_click(self, item, col) -> None:
        """双击通道项弹出取色器；已有曲线立即换色并刷新图例。"""
        key = item.data(0, Qt.UserRole)
        ch = self.channels.get(key) if key else None
        if ch is None:
            return
        color = QColorDialog.getColor(QColor(ch.color), self, f"选择 {ch.name} 曲线颜色")
        if not color.isValid():
            return
        ch.color = color.name()
        if ch.curve is not None:
            self.plot.removeItem(ch.curve)
            ch.curve = None
            if ch.tree_item.checkState(0) == Qt.Checked:
                ch.curve = self.plot.plot(
                    pen=pg.mkPen(ch.color, width=1),
                    name=ch.name,
                    downsample=1,
                    autoDownsample=False,
                )
                self._update_plot()

    def _set_plot_hz(self, hz) -> None:
        """主图帧率上限：60/75/90（数据源 100Hz，超过 100 没有意义）。

        实测（offscreen，4 条 100Hz 曲线）：17ms→57FPS、13ms→≈70FPS、
        11ms→73FPS；再压到 8ms/5ms 反而掉回 57FPS（和 drain/表格定时器
        抢线程）。所以默认 75，90 只在本机 GUI 线程空闲时才吃得下。
        """
        try:
            hz = int(float(hz))
        except (TypeError, ValueError):
            return
        hz = max(5, min(120, hz))
        self._plot_hz = float(hz)
        self._plot_interval_ms = max(1, int(round(1000.0 / hz)))
        timer = getattr(self, "plot_timer", None)
        if timer is not None:
            timer.setInterval(self._plot_interval_ms)
        self._plot_gate = 0
        if hasattr(self, "_ctrl_status"):
            self._ctrl_status(f"主图帧率上限 → {hz} FPS（{self._plot_interval_ms} ms/帧）",
                              log=False)

    def _set_plot_aa(self, on: bool) -> None:
        """曲线抗锯齿开关（默认关）。

        代价实测（4 条 100Hz 曲线、原生窗口）：paint 7.5ms → 12.9ms（+72%），
        75FPS 预算 13.3ms 基本被吃光，会掉帧；机器余量大时勾上明显更顺滑。
        pyqtgraph 的抗锯齿是**建曲线项时**从全局配置取的，所以这里必须重建
        曲线项（顺带 pyqtgraph 会自动维护图例），不能只改视图开关。
        """
        on = bool(on)
        pg.setConfigOptions(antialias=on)
        plot = getattr(self, "plot", None)
        if plot is None:
            return
        plot.setAntialiasing(on)
        for ch in self.channels.values():
            if ch.curve is None:
                continue
            plot.removeItem(ch.curve)
            ch.curve = plot.plot(
                pen=pg.mkPen(ch.color, width=1.2),
                name=ch.name, downsample=1, autoDownsample=False)
        self._update_plot()
        if hasattr(self, "_ctrl_status"):
            self._ctrl_status(f"曲线抗锯齿：{'开（更顺滑，paint +70%）' if on else '关（省 CPU）'}",
                              log=False)

    def _plot_tick(self) -> None:
        """绘图节拍：只在有新数据且未暂停时重绘，空闲时零绘制。

        🔒运行优先（可选，默认关）：闭环运行期间隔拍画（60→30FPS），把 GUI
        线程让给控制环。注意这里是"降帧"，所以默认不勾——靠 _adapt_density
        调点数就能同时守住 60FPS 和控制环，不必牺牲帧率。"""
        if self.plot_frozen or not getattr(self, "_plot_dirty", False):
            return
        if self._run_prio():
            self._plot_gate = getattr(self, "_plot_gate", 0) + 1
            if self._plot_gate % 2:
                return
        self._plot_dirty = False
        self._update_plot()
        self._adapt_density()

    def _target_points(self) -> int:
        """每帧每条曲线最多画多少点（约 N 点/像素，N 由 paint 实测自适应）。"""
        try:
            px = int(self.plot.getViewBox().width()) or self.plot.width()
        except Exception:
            px = 800
        if px <= 0:
            px = 800
        return max(200, int(px * getattr(self, "_pts_per_px", 2.0)))

    def _adapt_density(self) -> None:
        """保帧率、调点数：paint 超预算就降密度，富余就慢慢加回来。

        目标是把帧率"钉"在 PLOT_HZ（默认 60），代价只是曲线精度（每像素
        2→0.25 点），而不是把帧率降到个位数那种肉眼可见的卡。
        """
        ema = getattr(self.plot, "paint_ema_ms", 0.0)
        if ema <= 0.0:
            return
        budget = 1000.0 / max(5.0, getattr(self, "_plot_hz", PLOT_HZ))
        cur = getattr(self, "_pts_per_px", 2.0)
        # 2026-11-24：下限从 0.25 提到 1.0。每像素少于 1 个点时曲线会明显"缺峰"、
        # 看着稀疏发假（0.25 相当于 1000px 只画 250 点）。宁可少降帧也不降到
        # 看不出原始波形；真正的减压交给帧率上限与峰值抽稀。
        if ema > budget * 0.55 and cur > 1.0:
            cur = max(1.0, cur * 0.85)      # 超预算：更快地降
        elif ema < budget * 0.30 and cur < 3.0:
            cur = min(3.0, cur * 1.05)       # 富余：慢慢加回去
        self._pts_per_px = cur

    def _update_plot(self) -> None:
        self._plot_frames = getattr(self, "_plot_frames", 0) + 1
        tail = float(self.window_combo.currentText().rstrip("s"))
        self._visible_series = {}
        self._series_color = {}
        normalize = self.norm_check.isChecked()
        # 先保峰抽稀再 setData：见 peak_decimate 的说明，这是 paint 从 27ms
        # 降到 13ms 的关键（pyqtgraph 自己降采样发生在收数之后的 O(n) 处理）。
        target = self._target_points()
        for ch in self.channels.values():
            if ch.curve is None:
                continue
            t, v = ch.buf.series(tail)
            if normalize and v.size:
                vmin, vmax = float(np.nanmin(v)), float(np.nanmax(v))
                span = vmax - vmin
                v = (v - vmin) / span if span > 1e-9 else np.zeros_like(v)
            if t.size > target:
                t, v = peak_decimate(t, v, target)
            # skipFiniteCheck：窗口内无 NaN 时省掉 pyqtgraph 的逐点扫描。
            ch.curve.setData(t, v, skipFiniteCheck=True)
            self._visible_series[ch.name] = (t, v)
            self._series_color[ch.name] = ch.color
        self.empty_plot_text.setVisible(not self._visible_series)
        # Y 自适应：走自己的带迟滞慢跟随，**不用** pyqtgraph 的 autoRange
        # （它每帧重算 + 0.02s 动画 → 曲线上下"呼吸"，见 _y_auto_follow 注释）。
        if self.yauto_check.isChecked():
            self._yauto_on = True
            self._y_auto_follow()
        if self.xauto_check.isChecked() and self._latest_t is not None:
            # 示波器滚动：X 锁定为 [最新-窗口, 最新]
            vb = self.plot.getViewBox()
            vb.disableAutoRange(axis=ViewBox.XAxis)
            vb.setXRange(max(0.0, self._latest_t - tail), self._latest_t, padding=0)

    def _on_plot_mouse_moved(self, pos) -> None:
        """鼠标在图上：十字线 + 每条曲线"最近采样点"高亮 + 贴鼠标的数值浮层。

        2026-11-24 重做：原来只把 5 行文字丢在图区左下角，既看不出是哪个点，
        也和鼠标位置对不上。现在：
          · 按 x 二分找最近采样点，画出该点（颜色同曲线）；
          · 浮层跟着鼠标走（右下 14px，靠近边缘自动翻到另一侧）；
          · 列出当前所有可见曲线在该 x 上的采样值。
        """
        if not hasattr(self, "_visible_series") or not hasattr(self, "_hover_tip"):
            return
        vb = self.plot.getPlotItem().vb
        if not self.plot.sceneBoundingRect().contains(pos):
            self._hide_hover()
            return
        mouse_pt = vb.mapSceneToView(pos)
        self.vLine.setPos(mouse_pt.x())
        self.hLine.setPos(mouse_pt.y())
        rows = []
        spots = []
        for name, (t, v) in self._visible_series.items():
            if t is None or t.size == 0:
                continue
            # t 已按时间升序：二分定位比 nanargmin 全量扫描快两个数量级。
            idx = int(np.searchsorted(t, mouse_pt.x()))
            if idx >= t.size:
                idx = t.size - 1
            elif idx > 0 and abs(t[idx - 1] - mouse_pt.x()) < abs(t[idx] - mouse_pt.x()):
                idx -= 1
            val = float(v[idx])
            if not math.isfinite(val):
                continue
            color = self._series_color.get(name, "#cccccc")
            rows.append((name, float(t[idx]), val, color))
            spots.append({"pos": (float(t[idx]), val), "brush": pg.mkBrush(color)})
        if spots:
            self._hover_dots.setData(spots)
        else:
            self._hover_dots.clear()
        if not rows:
            self._hide_hover()
            return
        head = f"t = {rows[0][1]:.3f} s"
        body = "\n".join(f"{name}  {val:,.2f}" for name, _t, val, _c in rows[:10])
        if len(rows) > 10:
            body += f"\n… 还有 {len(rows) - 10} 条"
        self._hover_tip.setText(head + "\n" + body)
        self._hover_tip.adjustSize()
        # 贴鼠标：默认右下，靠边就翻到另一侧
        try:
            at = self.plot.mapFromScene(pos)
            cx, cy = int(at.x()), int(at.y())
        except Exception:
            return
        tw, th = self._hover_tip.width(), self._hover_tip.height()
        x = cx + 14
        y = cy + 14
        if x + tw > self.plot.width() - 4:
            x = cx - tw - 14
        if y + th > self.plot.height() - 4:
            y = cy - th - 14
        self._hover_tip.move(max(2, x), max(2, y))
        self._hover_tip.raise_()
        self._hover_tip.show()

    def _hide_hover(self) -> None:
        """鼠标离开图区：收起浮层与高亮点（十字线留着也行，这里一并复位）。"""
        tip = getattr(self, "_hover_tip", None)
        if tip is not None:
            tip.hide()
        dots = getattr(self, "_hover_dots", None)
        if dots is not None:
            dots.clear()

    def _on_plot_double_click(self, ev) -> bool:
        """双击图区：加一条水平标记线；双击已有标记线（±6px）= 删除它。

        返回 True 表示事件已处理（_TimedPlotWidget 会 accept，不再往下传）。
        """
        vb = self.plot.getPlotItem().vb
        p = ev.position() if hasattr(ev, "position") else ev.pos()
        try:
            scene = self.plot.mapToScene(p.toPoint() if hasattr(p, "toPoint") else p)
        except Exception:
            return False
        if not vb.sceneBoundingRect().contains(scene):
            return False
        view = vb.mapSceneToView(scene)
        for ln in list(getattr(self, "_h_markers", [])):
            try:
                y_scene = vb.mapViewToScene(QPointF(view.x(), ln.value())).y()
            except Exception:
                continue
            if abs(y_scene - scene.y()) <= 6:
                self._remove_h_marker(ln)
                self._ctrl_status(f"标记线已删除（y={ln.value():,.1f}）", log=False)
                return True
        self._add_h_marker(view.y())
        return True

    def _add_h_marker(self, y: float, quiet: bool = False) -> None:
        """在 y 处加一条水平标记线（虚线 + 左侧数值标签）。

        quiet=True 用于从布局存档恢复（不刷控制日志）。
        """
        if len(getattr(self, "_h_markers", [])) >= self._H_MARKER_MAX:
            if not quiet:
                self._ctrl_status(
                    f"标记线最多 {self._H_MARKER_MAX} 条，先双击删掉几条", log=False)
            return
        colors = (AT.T("warn"), AT.T("accent2"), AT.T("good"), AT.T("accent"), AT.T("bad"))
        color = colors[len(self._h_markers) % len(colors)]
        ln = pg.InfiniteLine(
            angle=0, pos=float(y), movable=False,
            pen=pg.mkPen(color, width=1, style=Qt.DashLine),
            label="{value:,.0f}",
            # 标签放右侧（左端被图例占了），留出文字宽度别被边界裁掉。
            labelOpts={"position": 0.90, "color": color,
                       "fill": pg.mkBrush(30, 30, 30, 170), "movable": False},
        )
        ln.setZValue(90)
        self.plot.addItem(ln, ignoreBounds=True)
        self._h_markers.append(ln)
        if not quiet:
            self._ctrl_status(f"已加标记线 y={y:,.1f}（双击它可删除）", log=False)

    def _remove_h_marker(self, ln) -> None:
        try:
            self._h_markers.remove(ln)
        except ValueError:
            pass
        try:
            self.plot.removeItem(ln)
        except Exception:
            pass

    def _clear_h_markers(self) -> None:
        """清掉所有标记线（「清空」按钮与布局恢复前共用）。"""
        for ln in list(getattr(self, "_h_markers", [])):
            self._remove_h_marker(ln)
        self._h_markers = []

    def _on_abstime_toggled(self, checked: bool) -> None:
        RelativeTimeAxis.absolute = checked
        self.plot.getPlotItem().update()

    def _apply_y_limits(self) -> None:
        if self._loading_layout:
            return
        lo, hi = self.ymin_spin.value(), self.ymax_spin.value()
        if hi <= lo:
            self._ctrl_status(f"Y 限值无效：上限 {hi} 需大于下限 {lo}", log=False)
            return
        self.yauto_check.setChecked(False)
        self.plot.getViewBox().setYRange(lo, hi, padding=0)

    def _on_yauto_toggled(self, checked: bool) -> None:
        vb = self.plot.getViewBox()
        # 2026-11-24：不再把 Y 轴交给 pyqtgraph 的 autoRange（逐帧重算 + 动画 =
        # 曲线上下呼吸）。关掉它，自己在 _y_auto_follow 里带迟滞地跟。
        vb.disableAutoRange(axis=ViewBox.YAxis)
        self._yauto_on = bool(checked)
        self._y_applied = None
        self._y_follow_at = 0.0
        if checked:
            self._y_auto_follow()

    def _y_auto_follow(self) -> None:
        """Y 自适应：带迟滞的慢跟随（≤4Hz），替代 pyqtgraph 的逐帧 autoRange。

        为什么换（2026-11-24 实测）：autoRange 每帧按可见数据重算，并在 0.02s
        内插值动画到新目标；目标每帧都在变 → 动画永远追不上，整条曲线上下
        "呼吸"。同一段正弦 + 1‰ 噪声的 4 s 里，可见 Y 跨度在 **294~1098**
        之间来回跳（273%，48 个不同值），肉眼就是"一直在抖、很难看"。

        新策略：
          · 目标 = 可见曲线 min/max + 8% 余量；
          · 数据出界 → 立刻扩；当前跨度 > 目标 1.4 倍 → 才收（防抖）；
          · 最多 4Hz 更新一次，且不做动画（padding=0）。
        """
        if not getattr(self, "_visible_series", None):
            return
        applied = getattr(self, "_y_applied", None)
        now = time.monotonic()
        # 首次（还没有应用过范围）不受节流限制，否则刚勾上通道时量程会停在旧值
        if applied is not None and now - getattr(self, "_y_follow_at", 0.0) < 0.25:
            return
        vmin, vmax = math.inf, -math.inf
        for _t, v in self._visible_series.values():
            if v is None or not len(v):
                continue
            try:
                lo = float(np.nanmin(v))
                hi = float(np.nanmax(v))
            except (ValueError, TypeError):
                continue
            if math.isfinite(lo) and math.isfinite(hi):
                vmin = min(vmin, lo)
                vmax = max(vmax, hi)
        if not (math.isfinite(vmin) and math.isfinite(vmax)) or vmax <= vmin:
            return
        pad = (vmax - vmin) * 0.08
        tgt = (vmin - pad, vmax + pad)
        applied = getattr(self, "_y_applied", None)
        if applied is not None:
            cur_lo, cur_hi = applied
            outside = tgt[0] < cur_lo or tgt[1] > cur_hi
            too_wide = (cur_hi - cur_lo) > (tgt[1] - tgt[0]) * 1.4
            if not (outside or too_wide):
                return
        self._y_applied = tgt
        self._y_follow_at = now
        self.plot.getViewBox().setYRange(tgt[0], tgt[1], padding=0)

    def _set_baseline_from_current(self, j: int) -> None:
        """基准取滤波值（解绕+中值5+EMA），不取 raw 单帧。

        10-29 诊断遗留①：raw 单帧噪声 ±1~3°，且使能确认自动归零恰逢上电
        噪声峰值——偏差直接烙进闭环 e。滤波值不可用（未预热/无数据）回退
        raw 通道。归一化 %16384 存档（_axis_deg 对圈表示 mod 不变）。"""
        v = self._enc_filt_raw.get(j)
        if v is None:
            v = self.channels[f"enc_raw_{j}"].buf.last()
        if not math.isfinite(v):
            self.angle_baseline[j] = None
            self._angle_baseline_raw[j] = None
        else:
            self._angle_baseline_raw[j] = int(round(v)) % 16384
            self.angle_baseline[j] = self._axis_deg(j, self._angle_baseline_raw[j])

    def _set_angle_baseline_now(self, axis=None) -> None:
        """axis: 16=仅ROLL, 17=仅PITCH, None=双轴。落盘：重启后自动恢复零位。"""
        if self.cl_enabled and self._cl_mode == "c1_position":
            self._stop_closed_loop("混合模式角度基准已更改", popup=False)
        for j in ((axis,) if axis in (16, 17) else (16, 17)):
            self._set_baseline_from_current(j)
        if self.cl_enabled and self._cl_mode == "position":
            # 运行中重新归零：读数平移了，origin 必须跟着走（软限幅的基准）。
            # 位置环本身是"每拍从实测出发"的增量式，不需要额外的参考位姿。
            for m in SERVO_TARGETS:
                v = self.channels[f"m{m}_abs"].buf.last()
                if v is not None and not math.isnan(v):
                    self._motor_origin[m] = int(v)
        self._save_layout()   # BUG1 修复：基准随布局持久化，重启免重标
        self._ctrl_status("📐 基准已更新为当前 ROLL/PITCH 角度（已保存，重启自动恢复）", log=False)

    # ---------- 逐绳使能开关（勾选门禁：未勾选的电机不使能、不下发） ----------
    def _cable_label(self, motor: int) -> str:
        """电机号 → 缆名（MOTOR_FOR_CABLE 换序时标签跟着换）；不在缆序表返回空。"""
        try:
            return f"C{MOTOR_FOR_CABLE.index(motor) + 1}"
        except ValueError:
            return ""

    def _motor_enabled(self, motor: int) -> bool:
        """该电机的绳是否勾选使能（复选框缺失时按勾选处理，防御旧布局）。"""
        cb = self.cable_enable_checks.get(motor)
        return True if cb is None else cb.isChecked()

    def _enabled_motors(self) -> list[int]:
        return [m for m in SERVO_TARGETS if self._motor_enabled(m)]

    def _enabled_motor_mask(self) -> int:
        return sum(1 << m for m in self._enabled_motors())

    def _motor_list_text(self, motors) -> str:
        return " ".join(
            f"M{m}·{c}" if (c := self._cable_label(m)) else f"M{m}"
            for m in motors)

    def _refresh_motor_rows(self) -> None:
        """按 勾选×使能×闭环 三态刷新 M27-29 行的点动/输入框/Go 可用性。"""
        for m in SERVO_TARGETS:
            on = self._motor_enabled(m)
            for b in self.jog_buttons_by_motor.get(m, ()):
                b.setEnabled(self.armed and on and not self.cl_enabled)
            if m in self.target_edits:
                self.target_edits[m].setEnabled(on and not self.cl_enabled)
            go = self.go_buttons.get(m)
            if go is not None:
                go.setEnabled(on and not self.cl_enabled)

    def _on_cable_enable_toggled(self, motor: int, checked: bool) -> None:
        cable = self._cable_label(motor)
        name = f"M{motor}" + (f"（{cable}）" if cable else "")
        if self.cl_enabled:
            # 闭环运行中改使能范围 = 改变控制结构：与切控制模式同款，先停再改。
            self._stop_closed_loop("使能范围变更", popup=False)
        if (self.armed or self._admit_timer.isActive() or self._enable_delay.isActive()
                or self._zero_timer.isActive()):
            # REVIEW P0-5：P4 的 active scope 是使能时快照——armed 下改勾选
            # 不解除武装，P4 活动域与 UI 永久错位。强制解除，重新使能时重建。
            self._on_stop()
            self._ctrl_status(f"M{motor} 勾选变更：已解除武装，请重新使能"
                              "（P4 活动域按新勾选重建）", log=False)
        if not checked:
            self._ramp_state.pop(motor, None)   # 进行中的斜坡分步目标一并作废
        self._refresh_motor_rows()
        self._update_motor_info(motor)
        if checked:
            self._ctrl_status(f"☑ {name} 已勾选：使能/点动/闭环将包含它")
        else:
            self._ctrl_status(f"☐ {name} 已取消：不下发任何命令；重新使能后活动域不含它")
        self._save_layout()

    def _enable_gate_check(self):
        """使能直控门禁（纯读，供按钮与拒绝弹窗 1Hz 复查共用）。

        返回 (reason|None, clear_pending)。clear_pending=True 对应
        「未勾选任何绳」：拒绝时需清预埋意图（防稍后补勾选时突然回零/起环）。
        多圈未知不算拒绝（走自动归零分支），不在此列。"""
        if not self.connected:
            return "未连接", False
        motors = self._enabled_motors()
        if not motors:
            return "⛔ 未勾选任何绳：先在右侧 M27-M29 行勾选要使能的绳", True
        online = self.status_info.get("servo_online", 0)
        missing = [m for m in motors if not online >> m & 1]
        if missing:
            return f"{self._motor_list_text(missing)} 离线，检查供电/接线", False
        if self.route_info.get("scan_state") == 1:
            return "舵机路由全扫中，稍候再试", False
        if not self.last_servo_abs_all:
            return "等待 ABS 快照…", False
        return None, False

    def _p4_overload_reason(self) -> str:
        if not (self.status_info.get("faults", 0) & SYSTEM_FAULT_OVERLOAD
                or self._overload_motors):
            return ""
        motors = "、".join(f"M{m}" if load is None else f"M{m}({load:+d})"
                          for m, load in self._overload_motors.items())
        return f"P4 舵机过载{(' ' + motors) if motors else ''}，检查负载后重新使能"

    def _cancel_direct_motion(self, reason: str, *, discard_tx: bool = True) -> None:
        self.armed = False
        self._stop_closed_loop(reason, hold=False, popup=False)
        self._ramp_timer.stop()
        self._ramp_state.clear()
        self._release_plan = None
        self._enable_delay.stop()
        self._admit_timer.stop()
        self._zero_timer.stop()
        self._want_closed_loop = self._want_goto_zero = False
        self._pending_target = None
        self.targets = dict.fromkeys(SERVO_TARGETS)
        drop = getattr(self.rx_thread, "drop_pending_tx", None)
        if discard_tx and drop:
            drop()

    def _handle_p4_status(self, previous_overload: str) -> None:
        reason = self._p4_overload_reason()
        lost_control = self.armed and self.status_info.get("state") == SYSTEM_STATE_UNCONTROLLABLE
        enabling = self._admit_timer.isActive() or self._enable_delay.isActive() or self._zero_timer.isActive()
        if lost_control or (reason and (self.armed or (enabling and not previous_overload))):
            reason = reason or f"P4 不可控，故障位 0x{self.status_info.get('faults', 0):X}"
            self._cancel_direct_motion(reason)
        elif reason == previous_overload:
            return
        self._set_arm_light()
        if reason:
            self._ctrl_status(reason)
            self._safety("P4_FAULT", reason=reason, **self.status_info)

    def _on_enable_direct(self) -> None:
        # Go / 回零 / 启动闭环都可请求自动使能。保护停机后只能由显式使能恢复。
        overload = self._p4_overload_reason()
        if overload and (self._pending_target is not None or self._want_closed_loop
                         or self._want_goto_zero):
            self._pending_target = None
            self._want_closed_loop = self._want_goto_zero = False
            self._reject("使能直控", overload)
            return
        reason, clear_pending = self._enable_gate_check()
        if reason:
            if clear_pending:
                # 拒绝时清预埋意图，防止稍后补勾使能时突然回零/起闭环
                self._want_closed_loop = False
                self._want_goto_zero = False
                self._pending_target = None
            self._reject("使能直控", reason,
                         recheck=lambda: self._enable_gate_check()[0])
            return
        motors = self._enabled_motors()
        mask = self._enabled_motor_mask()
        unknown = self.status_info.get("multiturn_unknown", 0) & mask
        if unknown:
            self._ctrl_status(f"多圈未知 → 正在归零 {self._motor_list_text(motors)}…")
            if self._send_bytes(build_servo_reset_zero_cmd(mask)):
                self._zero_poll_count = 0
                self._zero_timer.start(300)
            return
        self._finish_enable()

    def _on_reset(self) -> None:
        if not self.connected:
            self._ctrl_status("未连接")
            return
        self._cancel_direct_motion("复位")
        if self._send_bytes(build_reset_cmd()):
            self.estop_latched = False
            self._set_arm_light()
            self._ctrl_status("已发送 RESET（清 E-STOP 锁存/可恢复故障，舵机断扭）")

    def _on_admit_poll(self) -> None:
        """使能后确认 P4 真正进入 RUN_DIRECT，否则显示拒绝原因。"""
        self._admit_poll += 1
        info = self.status_info
        # 到位后固件可释放 owner；保护停机也会保留 direct 模式位。
        applied = info.get("applied_generation")
        new_command = (applied is None or
                       (applied == info.get("pending_generation") and
                        applied != self._prior_applied_generation))
        direct_state = info.get("state") in (SYSTEM_STATE_RUN_DIRECT, SYSTEM_STATE_IDLE,
                                             SYSTEM_STATE_READY, SYSTEM_STATE_RECOVERY_REQUIRED)
        if (self._status_rx_at > self._admit_sent_at and new_command and direct_state
                and info.get("control_mode") == 1 and not info.get("direct_reject")
                and not self._p4_overload_reason()):
            # 使能确认前先核对活动域：0xD3 批量帧按它收窄，若只含部分电机，
            # 一键紧绳/松绳/力控会"只有一台动"。不符就重写一次活动域再等。
            missing = self._scope_missing(self._enabled_motors())
            if missing and getattr(self, "_scope_retry", 0) < 2:
                self._scope_retry = getattr(self, "_scope_retry", 0) + 1
                self._ctrl_status(
                    f"⚠ 活动域缺少 {self._motor_list_text(missing)}："
                    f"正在重写活动域（第 {self._scope_retry} 次）")
                self._send_bytes(build_stop_cmd())
                self._send_bytes(build_reset_cmd())
                self._send_bytes(build_active_scope_cmd(
                    self._enabled_motor_mask(), 0, False))
                self._admit_timer.stop()
                self._enable_delay.start(150)
                return
            if missing:
                self._cancel_direct_motion("使能活动域不完整")
                self._reject("使能直控", f"P4 活动域仍缺少 {self._motor_list_text(missing)}")
                return
            self._scope_retry = 0
            self._admit_timer.stop()
            self.armed = True
            self.estop_latched = False
            self._set_arm_light()
            # 使能不再重标零位（2026-11-02 用户 BUG 报告；10-29 诊断亦指出使能
            # 确认恰逢上电噪声峰值、是最糟的归零时机）：已有基准（📐 设置或
            # 布局恢复）保持不动；仅基准缺失时自动零一次并落盘防重启丢失。
            auto_zeroed = self._auto_zero_baselines()
            if auto_zeroed:
                self._save_layout()
            for m in SERVO_TARGETS:
                v = self.channels[f"m{m}_abs"].buf.last()
                self.targets[m] = 0 if math.isnan(v) else int(v)
                self._update_motor_info(m)
            self._record_motor_origins()
            if self._want_closed_loop:
                self._want_closed_loop = False
                self._start_closed_loop()
            if getattr(self, "_want_goto_zero", False):
                self._want_goto_zero = False
                data = load_named_json("wrist_zero.json")
                if data and "motors" in data:
                    self._do_goto_zero(data)
            if self._pending_target is not None:
                motor, rel = self._pending_target
                self._pending_target = None
                base = self.targets.get(motor)
                if base is None:
                    base = self._motor_pos_now(motor)
                self._send_motor_target(motor, base + rel)
                self._ctrl_status(f"自动使能完成，M{motor} 相对 {rel:+d} → 绝对 {base + rel:+d}")
            motors = self._enabled_motors()
            off = [m for m in SERVO_TARGETS if m not in motors]
            self._ctrl_status(
                f"✅ RUN_DIRECT 已确认（使能 {self._motor_list_text(motors)}"
                + (f"；未勾选 {self._motor_list_text(off)} 不下发）" if off else "）")
                + "：小步长点动测方向")
            return
        if self._admit_poll >= 12:
            self._admit_timer.stop()
            self._want_closed_loop = self._want_goto_zero = False
            self._pending_target = None
            reason = info.get("direct_reject", 0)
            state = info.get("state")
            if self._p4_overload_reason():
                self._reject("使能直控", self._p4_overload_reason())
            elif state == 0 and self.estop_latched:
                self._reject("使能直控",
                             "⛔ 使能被拒：E-STOP 锁存（点「复位」后重试）")
            else:
                self._reject(
                    "使能直控",
                    f"⛔ 使能未确认 state={state} "
                    f"reject={DIRECT_REJECT_NAMES.get(reason, reason)}")
            return
        self._ctrl_status(f"等待 RUN_DIRECT 确认 {self._admit_poll * 0.2:.1f}s…")

    def _on_zero_poll(self) -> None:
        self._zero_poll_count += 1
        unknown = self.status_info.get("multiturn_unknown", 0) & self._enabled_motor_mask()
        if unknown == 0:
            self._zero_timer.stop()
            self._ctrl_status("归零完成")
            self._finish_enable()
            return
        if self._zero_poll_count >= 20:
            self._zero_timer.stop()
            self._ctrl_status("归零超时（6s），多圈仍未知；检查舵机在线后重试")
        else:
            self._ctrl_status(f"等待归零 {self._zero_poll_count * 0.3:.1f}s…")

    def _scope_missing(self, motors) -> list[int]:
        """返回**不在** P4 当前活动域里的电机（活动域=0/未知时返回空，视为未知）。

        0xD3 批量帧在固件里是 `active_motor_mask & validMotorChannelMask()`，
        活动域外的电机即使帧里带了目标也不会执行；0xDE 单电机不查这个掩码，
        所以会出现"点动能动、一键紧绳只有一台动"的怪现象。
        """
        active = int(self.status_info.get("active_motor_mask", 0) or 0)
        if active == 0:
            return []                     # 还没收到状态帧：不做判断
        return [m for m in motors if not (active >> m & 1)]

    def _finish_enable(self) -> None:
        mask = self._enabled_motor_mask()
        if not mask:
            self._ctrl_status("⛔ 未勾选任何绳：先在右侧 M27-M29 行勾选要使能的绳")
            return
        if self.armed:
            self._cancel_direct_motion("重新使能")
            self._set_arm_light()
        self._scope_retry = 0
        self._admit_timer.stop()
        self._enable_mask = mask
        # P4 语义：CMD_STOP 是锁存式 E-STOP，只有 CMD_RESET 能解锁；使能前一律先
        # STOP+RESET —— 不只为了解锁，更是为了**把 owner/control_enabled 清回 NONE**：
        # 固件的 ACTIVE_SCOPE 只在 owner=NONE、未使能时接受，否则静默拒绝。急停后
        # 立刻重新使能时状态机可能还没收敛，活动域就会停在上一次的单电机掩码上，
        # 表现为"点动能动、一键紧绳只有一台动"（2026-11-03 实机）。
        self._send_bytes(build_stop_cmd())
        self._send_bytes(build_reset_cmd())
        self.estop_latched = False
        # 活动域只含勾选的绳：固件就绪检查/离线故障/0xD3 命令都按此掩码收窄
        # （0xDE 单电机命令不走此掩码，故门禁另落在上位机各发送路径）。
        ok = self._send_bytes(build_active_scope_cmd(mask, 0, False))
        if not ok:
            self._ctrl_status("使能发送失败：活动域写入未被受理")
            return
        # 活动域要等状态机清空 owner 后才落地：给一拍时间再 START，否则会沿用旧掩码
        self._enable_delay.start(150)

    def _finish_enable_start(self) -> None:
        if not self.connected or self.estop_latched or self._enable_mask != self._enabled_motor_mask():
            return
        if not self.last_servo_abs_all:
            return
        online = self.status_info.get("servo_online", 0)
        targets = [v if online & (1 << i) else 0 for i, v in enumerate(self.last_servo_abs_all)]
        self._admit_sent_at = time.monotonic()
        self._prior_applied_generation = self.status_info.get("applied_generation")
        ok = self._send_bytes(build_start_cmd())
        ok = self._send_bytes(build_motor_pos_abs_cmd(targets)) and ok
        if not ok:
            self._ctrl_status("使能发送失败")
            return
        self._admit_poll = 0
        self._admit_timer.start(200)

    def _set_arm_light(self) -> None:
        self._refresh_motor_rows()
        if not self.armed:
            self._pending_target = None
        if self.armed:
            self.arm_light.setText("● 已使能 直控中")
            self.arm_light.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {AT.T('good')}; padding: 2px;")
        elif self._p4_overload_reason():
            self.arm_light.setText("⛔ " + self._p4_overload_reason())
            self.arm_light.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {AT.T('bad')}; padding: 2px;")
        elif self.estop_latched:
            self.arm_light.setText("⛔ E-STOP 锁存（点「复位」后重新使能）")
            self.arm_light.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {AT.T('bad')}; padding: 2px;")
        else:
            self.arm_light.setText("● 未使能（点「使能直控」后按钮才可用）")
            self.arm_light.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {AT.T('warn')}; padding: 2px;")

    def _record_motor_origins(self) -> None:
        for m in SERVO_TARGETS:
            v = self.channels[f"m{m}_abs"].buf.last()
            self._motor_origin[m] = None if math.isnan(v) else int(v)

    def _update_motor_info(self, motor: int) -> None:
        if motor not in getattr(self, "motor_info", {}):
            return
        base = self._soft_limit_base(motor)
        cur = self.channels[f"m{motor}_abs"].buf.last()
        cur_txt = "--" if math.isnan(cur) else f"{int(cur):+d}"
        tgt = self.targets.get(motor)
        tgt_txt = "--" if tgt is None else f"{tgt:+d}"
        origin = self._motor_origin.get(motor)
        origin_txt = "--" if origin is None else f"{origin:+d}"
        off_txt = "--"
        if origin is not None and not math.isnan(cur):
            off_txt = f"{int(cur) - origin:+d}"
        # 2026-11-20：显示舵机自报的实时速度（遥测通道，单位 counts/s）
        ch_spd = self.channels.get(f"m{motor}_speed")
        spd = ch_spd.buf.last() if ch_spd is not None else None
        spd_txt = ""
        if spd is not None and not math.isnan(spd):
            spd_txt = f"  速度 {spd:+.0f}c/s"
        if not self._motor_enabled(motor):
            text = f"实际 {cur_txt}（☐ 未勾选，不下发命令）"
        elif self.armed:
            text = (f"起点 {origin_txt}  实际 {cur_txt}  目标 {tgt_txt}"
                    f"  累计 {off_txt}{spd_txt}")
        else:
            text = f"实际 {cur_txt}（未使能）{spd_txt}"
        cache = getattr(self, "_motor_info_cache", None)
        if cache is None:
            cache = self._motor_info_cache = {}
        if cache.get(motor) != text:
            cache[motor] = text
            self.motor_info[motor].setText(text)

    def _soft_limit_base(self, motor: int) -> int:
        origin = self._motor_origin.get(motor)
        if origin is not None:
            return origin
        v = self.channels[f"m{motor}_abs"].buf.last()
        return 0 if math.isnan(v) else int(v)

    def _clamp_to_soft_limit(self, motor: int, tgt: int) -> int:
        base = self._soft_limit_base(motor)
        return max(base - MOTOR_SOFT_LIMIT, min(base + MOTOR_SOFT_LIMIT, tgt))

    def _motor_pos_now(self, motor: int) -> int:
        """电机当前实际位置（无数据时回退到上一目标/起点）。"""
        v = self.channels[f"m{motor}_abs"].buf.last()
        if v is None or math.isnan(v):
            t = self.targets.get(motor)
            return t if t is not None else self._soft_limit_base(motor)
        return int(v)

    def _send_motor_target(self, motor: int, tgt: int) -> None:
        """直控统一入口：无位置限位，仅限速斜坡（软限位只属于闭环律）。

        2026-11-03 用户定案：**直控不做张力检测**（点动/Go/斜坡/回零/一键松绳
        都不看张力），张力保护只在闭环里生效（力控启动的新鲜度检查 + 逐拍
        过载守卫）。理由：直控是人工小步操作，接线/校准期常常没连传感器。
        """
        if not self._motor_enabled(motor):   # 逐绳开关门禁：未勾选一律不下发
            self._reject(
                "直控目标", f"M{motor} 未勾选使能开关，跳过目标 {tgt:+d}",
                recheck=lambda: (None if self._motor_enabled(motor)
                                 else f"M{motor} 未勾选使能开关"))
            return
        cur = self.targets.get(motor)
        start = cur if cur is not None else self._soft_limit_base(motor)
        if not self.ramp_check.isChecked():
            self._ramp_state.pop(motor, None)
            # 2026-11-23：单电机也走 0xD3 批量帧。
            # 固件提升直控命令时会把 active_motor_mask 覆盖成本帧的
            # pending_direct_motor_mask；0xDE 的 mask 只有这一台，于是"直控一次，
            # 活动域只剩一台"，闭环/一键操作随后被门禁拒并要求重新使能。
            # 批量帧的 mask = 当前活动域∩有效，不收缩。
            #
            # 批量帧会带上 30 路目标，所以**其余两缆必须显式写成"原地保持"**：
            # 在跑的斜坡沿用它的当前步，其余用实测位置——不能沿用 self.targets，
            # 否则手推过之后的下一次点动会把别的绳拽回旧目标。
            outs = {m: self._motor_pos_now(m) for m in SERVO_TARGETS}
            for m in list(self._ramp_state):
                v = self.targets.get(m)
                if v is not None:
                    outs[m] = v
            outs[motor] = tgt
            self._send_direct_targets(
                outs, "DIRECT",
                motor=motor, target=tgt, delta=tgt - start,
                # 记下发送瞬间的实测，便于区分"发了没执行"还是"目标没变"
                meas={m: self._motor_pos_now(m) for m in SERVO_TARGETS})
            return
        self._ramp_state[motor] = {"target": tgt}
        if not self._ramp_timer.isActive():
            self._ramp_first_tick = True
            self._ramp_timer.start(50)

    # ---------- 多电机直控统一出口 ----------
    def _send_direct_targets(self, outs: dict[int, int], why: str, **detail) -> bool:
        """直控统一出口：**一帧 0xD3 批量下发**。0xDE 已在 2026-11-23 从协议删除。

        历史根因（2026-11-03 实机"松绳只有一根动"）：旧的单电机帧每帧都
        pending_direct_generation+1 并把 pending_direct_motor_mask 覆盖成单机位；
        状态机按代际过滤，同一毫秒连发 3 帧只有最后一帧被接受。批量帧一帧含全部
        目标，天然原子。
        """
        clean = {int(m): int(v) for m, v in outs.items() if self._motor_enabled(m)}
        if not clean:
            return False
        if not self._send_motor_batch(clean):
            self._warn_batch_skip(f"{why}：批量下发失败")
            return False
        for m, out in clean.items():
            self.targets[m] = out
        self._safety(why, outs=clean, **detail)
        return True

    # ---------- 安全保护总开关（只剩闭环相关项） ----------
    def _safety_on(self) -> bool:
        """安全保护总开关。未构建控件时按 True（fail-safe）。"""
        chk = getattr(self, "safety_check", None)
        return True if chk is None else bool(chk.isChecked())

    def _on_safety_toggled(self, checked: bool) -> None:
        """关闭安全保护需确认一次；之后状态栏持续告警并记 safety 日志。"""
        if not checked:
            if not (os.environ.get("MMHAND_NO_CONFIRM") == "1" or not self.isVisible()):
                ret = QMessageBox.question(
                    self, "关闭安全保护",
                    "关闭后：闭环守卫不再 fail-closed（阈值非法也照跑）、\n"
                    "位置模式不再做每拍限幅（目标一跳几千 counts 也照发）。\n"
                    "（直控与一键松绳本来就不做张力检测，不受此开关影响。）\n\n"
                    "确定关闭？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ret != QMessageBox.Yes:
                    self.safety_check.blockSignals(True)
                    self.safety_check.setChecked(True)
                    self.safety_check.blockSignals(False)
                    self._ctrl_status("安全保护保持开启", log=False)
                    return
            self._ctrl_status("⚠ 安全保护已关闭：闭环守卫不再 fail-closed（风险自负）")
            self._safety("SAFETY_OFF")
        else:
            self._ctrl_status("🛡 安全保护已开启：闭环按张力守卫与斜率限制执行")
            self._safety("SAFETY_ON")

    def _safety(self, action: str, **fields) -> None:
        """写一行安全取证日志（连上设备时才写；测试/离线不产生垃圾）。"""
        if not self.connected:
            return
        info = {"mode": self._cl_mode, "armed": int(self.armed), "cl": int(self.cl_enabled)}
        last = self._tension_last
        if last is not None:
            info["f"] = "/".join(f"{v:.2f}" for v in last[1])
            info["age_ms"] = int((time.monotonic() - last[0]) * 1000)
        else:
            info["f"] = "-"
        info.update(fields)
        safety_log(action, **info)

    def _auto_zero_baselines(self) -> bool:
        """角度基准缺失时以当前角自动归零（已有基准不动），返回是否归零过。

        两处调用：使能确认、启动闭环。归零后由调用方决定是否立即落盘
        （使能处落盘防重启丢失；启动处也落盘）。
        """
        zeroed = False
        for j in (16, 17):
            if self.angle_baseline[j] is None:
                self._set_baseline_from_current(j)
                zeroed = True
        return zeroed

    def _on_ramp_tick(self) -> None:
        """50ms 一拍推进斜坡：**一拍一帧批量**（多电机逐帧 0xDE 会被固件
        代际合并，只有最后一台生效——"只有一根绳动"的另一个来源）。

        2026-11-03 用户定案：直控斜坡**不做张力检测**（张力保护只在闭环）。
        """
        step = max(1, int(self.ramp_rate_spin.value() * 0.05))
        outs = {}
        done = []
        for motor, st in list(self._ramp_state.items()):
            if not self._motor_enabled(motor):   # 中途取消勾选：剩余分步作废
                del self._ramp_state[motor]
                continue
            cur = self.targets.get(motor)
            pos = cur if cur is not None else self._soft_limit_base(motor)
            delta = st["target"] - pos
            move = max(-step, min(step, delta))
            nxt = pos + move
            outs[motor] = nxt
            if st["target"] == nxt:
                done.append(motor)
        if outs:
            if self._ramp_first_tick:
                # 批量帧也带其余绳：启动斜坡时按实测保持，之后沿用已发目标。
                for m in SERVO_TARGETS:
                    if m not in outs:
                        outs[m] = self._motor_pos_now(m)
                self._ramp_first_tick = False
            if not self._send_direct_targets(outs, "RAMP"):
                self._ramp_state.clear()
                self._ramp_timer.stop()
                return
            for motor in outs:
                self._update_motor_info(motor)
        for motor in done:
            self._ramp_state.pop(motor, None)
        if not self._ramp_state:
            self._ramp_timer.stop()

    def _relative_target_base(self, motor: int) -> int:
        if motor in self._ramp_state:
            return self._ramp_state[motor]["target"]
        sent = self.targets.get(motor)
        return sent if sent is not None else self._motor_pos_now(motor)

    def _jog(self, motor: int, delta: int) -> None:
        if self.cl_enabled:
            self._reject("点动", "闭环运行中：先停止闭环再手动",
                         recheck=lambda: ("闭环运行中：先停止闭环再手动"
                                          if self.cl_enabled else None))
            return
        if not self._motor_enabled(motor):
            self._reject("点动", f"M{motor} 未勾选使能开关，点动被忽略",
                         recheck=lambda: (None if self._motor_enabled(motor)
                                          else f"M{motor} 未勾选使能开关"))
            return
        if not self.armed:
            self._reject("点动", "先点上方「使能直控」",
                         recheck=lambda: (None if self.armed
                                          else "先点上方「使能直控」"))
            return
        tgt = self._relative_target_base(motor) + delta
        self._send_motor_target(motor, tgt)
        self._ctrl_status(f"M{motor} → {tgt:+d} (Δ{delta:+d})", log=False)

    def _send_manual_target(self, motor: int, edit) -> None:
        """输入语义：整数 N = 从【上次下发的目标】相对走 N。

        首次（还没下发过目标）用当前实测位置做基准。这样连按同一次序会累加，
        与 ± 点动的语义一致；否则第一次还没走完时，第二次按"实测位置"算出来的
        目标可能还是同一个，看起来"没反应"。
        """
        if self.cl_enabled:
            self._reject("手动目标", "闭环运行中：先停止闭环再手动",
                         recheck=lambda: ("闭环运行中：先停止闭环再手动"
                                          if self.cl_enabled else None))
            return
        text = edit.text().strip().replace("−", "-").replace("＋", "+")
        if not text:
            self._reject("手动目标",
                         f"M{motor}：请输入相对位移（基准=上次目标，首次=当前位置；"
                         f"如 500 或 -300）")
            return
        if text.startswith("+"):
            text = text[1:]
        try:
            rel = int(text)
        except ValueError:
            self._reject("手动目标",
                         f"M{motor}：无法识别 [{edit.text().strip()}]，只接受整数")
            return
        if not -2000000 <= rel <= 2000000:
            self._reject("手动目标",
                         f"M{motor}：位移 {rel:+d} 超出 int32 安全范围")
            return
        if not self._motor_enabled(motor):
            self._reject("手动目标", f"M{motor} 未勾选使能开关，目标被忽略",
                         recheck=lambda: (None if self._motor_enabled(motor)
                                          else f"M{motor} 未勾选使能开关"))
            return
        if not self.armed:
            # 未使能：暂存相对量，使能完成（记录起点）后再换算发送。
            self._pending_target = (motor, rel)
            self._ctrl_status(f"未使能 → 自动使能中，随后 M{motor} 相对 {rel:+d}")
            self._on_enable_direct()
            return
        base = self._relative_target_base(motor)
        self._send_motor_target(motor, base + rel)
        self._ctrl_status(f"M{motor} 基准 {base:+d} 相对 {rel:+d} → {base + rel:+d}")

    # ---------- 张力链（ZNSV 变送器直连：观测台 = 唯一 UI，驱动直持串口） ----------
    def _toggle_tension_port(self) -> None:
        """观测台「连接」：直连变送器并按 TENSION_POLL_HZ 轮询；已连则断开。

        COM23 同一时刻只能被一个程序打开：连接失败「拒绝访问」时先关掉
        ZNSV Studio 独立实例（znsv_app/启动ZNSV上位机.cmd 或原工程）再试。
        """
        if self._tension_sensor is not None:
            self._tension_disconnect()
            return
        port = self.tension_port_combo.currentText().strip()
        if not port:
            self.tension_status.setText("张力：请先选择串口")
            return
        baud = int(self.tension_baud_combo.currentText())
        sensor = ZnsvTransmitter(address=TENSION_MODBUS_ADDRESS, hz=TENSION_POLL_HZ)
        try:
            sensor.connect(port, baud)
        except Exception as exc:
            safety_log("TENSION_LINK", port=port, baud=baud, state="open_failed", error=repr(exc))
            self.tension_status.setText(f"张力：连接失败（{exc}）")
            return
        self._tension_sensor = sensor
        # 2026-11-25：波特率过低会**直接决定**张力更新率，必须说清楚。
        # 一帧事务 = 45 字节 × 10 bit：
        #   9600 → 46.9 ms/帧 ⟹ 最多 ~21 Hz（控制环 100 Hz 会 5 拍才拿到新值）
        #   115200 → 3.9 ms ⟹ ~250 Hz； 600000 → 0.75 ms ⟹ 轮询上限由 FTDI 决定
        try:
            _b = int(baud)
        except (TypeError, ValueError):
            _b = 9600
        if _b < 115200:
            _hz = 1.0 / max(1e-6, (8 + 37) * 10.0 / _b + 0.001)
            self.tension_status.setText(
                f"⚠ {_b} 波特率太慢：一帧 45B 要 {(8+37)*10.0/_b*1000:.0f} ms "
                f"→ 张力最多 ~{_hz:.0f} Hz（控制环 100 Hz 会拿旧值）"
                f"；建议 rate_upgrade.py 升到 600000")
        self._tension_port_name = f"{port}@{baud}"
        # 2026-11-25：轮询交给独立线程（GUI-QTimer 方案实测只有 ~15 Hz）
        self._tension_feed_count = 0
        self._tension_arrivals.clear()
        self._tension_thread = _TensionPollThread(self, sensor, port, baud)
        self._tension_thread.finished.connect(self._tension_worker_finished)
        self._refresh_cl_param_cache()  # 首帧就能读取 GUI 侧参数快照
        self._tension_thread.start()
        self._tension_status_refresh()

    def _tension_poll(self) -> None:
        """【已停用，保留仅作参考】旧 GUI-QTimer 轮询路径。

        2026-11-25 起张力轮询改由 `_TensionPollThread` 独立线程执行：
        裸串口实测 249.9 Hz，而这条 QTimer 路径在 GUI 里只有 ~15 Hz
        （被 60 Hz 绘图 + 100 Hz CSV 写盘拖住）。本函数不再被启动，
        留着是因为 `tools/perf/probe_tension_poll_rate.py` 复刻了这套排程逻辑。
        """
        sensor = self._tension_sensor
        if sensor is None:
            return
        try:
            raws = sensor.poll()
        except Exception as exc:
            self._tension_disconnect(f"采集异常：{exc}")
            return
        delay = sensor.next_poll_delay()
        interval = (1 if delay <= 0.0005
                    else max(1, min(20, int(math.ceil(delay * 1000.0)))))
        if self._tension_poll_timer.interval() != interval:
            self._tension_poll_timer.setInterval(interval)
        if raws is None:
            return
        self._tension_feed(raws)

    def _tension_disconnect(self, reason: str = "") -> None:
        self._tension_poll_timer.stop()
        th = self._tension_thread
        if th is not None:
            th.stop_reason = reason or "手动断开"
            th.link_status = "正在关闭串口"
            th.stop()
            if not th.wait(150):
                self._tension_status_refresh()
                return  # 驱动还在返回，保留所有者；finished 到达后完成断开
        elif self._tension_sensor is not None:
            self._tension_sensor.disconnect()
        self._finish_tension_disconnect(reason)

    def _tension_worker_finished(self) -> None:
        th = self.sender()
        if th is not None and th is self._tension_thread:
            self._finish_tension_disconnect(th.stop_reason)

    def _finish_tension_disconnect(self, reason: str) -> None:
        th, self._tension_thread = self._tension_thread, None
        if th is not None:
            th.deleteLater()
        self._tension_sensor = None
        if self.rt_window is not None:
            self.rt_window.estimate_panel.invalidate_reference()
        if self._cl_mode == "c1_position":
            self._tension_last = None
        safety_log("TENSION_LINK", port=self._tension_port_name, state="closed",
                   reason=reason or "手动断开")
        if self.tension_btn is not None:
            self.tension_btn.setText("连接")
        if self.tension_status is not None:
            note = f"（{reason}）" if reason else ""
            self.tension_status.setText(f"张力：已断开{note}")
        if getattr(self, "_close_after_tension", False):
            self._close_after_tension = False
            QTimer.singleShot(0, self.close)

    def _tension_feed(self, raws) -> None:
        """每帧回调：按当前通道映射 × 系数 → _on_tension_sample（守卫/τ/CSV 自动接上）；
        同时记 8 通道原始帧与三缆张力历史（观测台走势图用）。"""
        try:
            fvals = [raws[ch - 1] * TENSION_N_PER_RAW[i]
                     for i, ch in enumerate(self._tension_ch_map)]
        except IndexError:
            return   # 映射越界：丢帧保运行（映射来自 UI 下拉，1..8 恒合法，防御性保留）
        # 2026-11-23 晚**撤销**"混合模式把 C2/C3 置 NaN"（原为本地未提交改动）。
        # 初衷是"C2/C3 不参与该模式控制，别显示假数"，但代价是：
        #   · τ=R·f 与张紧 t 是三缆加权和 → 两路 NaN 把 C1 的好数据一起毒成 NaN；
        #   · 缆卡 / 力状态曲线 / calib 记录 / 诊断 CSV 只能看到 C1；
        #   · 用户要求"所有模式都能看到三缆张力"。
        # 控制侧并不使用 C2/C3：混合模式在 `_cl_tick` 提前 return、`_tension_guard`
        # 不参与，`_c1_position_feedback` 只读 f1。故显示真值不改任何控制/安全行为。
        self._tension_raws_last = tuple(raws)
        zero = self._tension_zero
        self._tension_feed_count += 1
        self._tension_arrivals.append(time.perf_counter())
        dec = self._tension_feed_count % 5 == 0
        for i, (series, disp, v) in enumerate(zip(self._tension_hist,
                                                  self._tension_hist_disp, fvals)):
            rel_v = v - (zero[i] if zero is not None else 0.0)   # 走势画相对值
            series.append(rel_v)
            if dec:
                disp.append(rel_v)      # 1/5 抽稀进显示缓冲（1500 点=30s）
        self._on_tension_sample(*fvals)

    def _tension_set_zero(self) -> None:
        """本地零位：把最新一帧绝对张力记为零点（只影响观测台显示与走势；
        守卫/τ=R·f 仍用绝对张力——安全判定不吃零位）。重启或清除后失效。"""
        if self._tension_last is None:
            self.tension_status.setText("张力：还没有数据，无法设零位")
            return
        if time.monotonic() - self._tension_last[0] > 1.0:
            self.tension_status.setText("张力：最新一帧已过期，等新数据再设零位")
            return
        self._tension_zero = list(self._tension_last[1])
        for series, disp in zip(self._tension_hist, self._tension_hist_disp):
            series.clear()   # 曲线从新基线重画
            disp.clear()
        self.tension_status.setText(
            "张力：本地零位已设（显示/走势为相对值；τ 与守卫仍用绝对值）")

    def _tension_clear_zero(self) -> None:
        if self._tension_zero is None:
            return
        self._tension_zero = None
        for series, disp in zip(self._tension_hist, self._tension_hist_disp):
            series.clear()
            disp.clear()
        self.tension_status.setText("张力：本地零位已清除，恢复绝对显示")

    def _set_tension_ch_map(self, cable_idx: int, ch: int) -> None:
        """观测台缆卡 CH 下拉回调：改 C_{cable+1} 的来源通道并持久化。"""
        ch = int(ch)
        if not 1 <= ch <= 8 or not 0 <= cable_idx < 3:
            return
        if self._tension_ch_map[cable_idx] == ch:
            return
        if cable_idx == self._hybrid_return_index and self._cl_mode == "c1_position":
            if self.cl_enabled:
                self._stop_closed_loop(f"C{cable_idx + 1} 复位绳的张力通道已更改")
            self._tension_last = None
        self._tension_ch_map[cable_idx] = ch
        if self.rt_window is not None:
            self.rt_window.estimate_panel.channel_changed(cable_idx)
        self._save_layout()
        if self.tension_status is not None:
            chs = "/".join(f"CH{c}" for c in self._tension_ch_map)
            self.tension_status.setText(f"张力：通道映射改为 {chs}→C1/C2/C3")

    # ---------- 零点校准 / 去皮（写命令排队，在重量帧间隙发送） ----------
    def _tension_zero_ch(self, ch: int) -> None:
        sensor = self._tension_sensor
        if sensor is None or not sensor.connected:
            self.tension_status.setText("张力：请先连接变送器")
            return
        if QMessageBox.question(
                self, "零点校准",
                f"CH{ch} 已空载（无负载）吗？\n校准会覆盖该路传感器零点标定。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        sensor.submit_channel_command(ch, 1, f"CH{ch} 零点校准")
        self._tension_observer_zero_changed(ch)
        self.tension_status.setText(f"张力：已排队 CH{ch} 零点校准（须空载，帧间隙发送）")

    def _tension_tare_ch(self, ch: int) -> None:
        sensor = self._tension_sensor
        if sensor is None or not sensor.connected:
            self.tension_status.setText("张力：请先连接变送器")
            return
        sensor.submit_channel_command(ch, 2, f"CH{ch} 去皮")
        self._tension_observer_zero_changed(ch)
        self.tension_status.setText(f"张力：已排队 CH{ch} 去皮")

    def _tension_all_tare(self) -> None:
        sensor = self._tension_sensor
        if sensor is None or not sensor.connected:
            self.tension_status.setText("张力：请先连接变送器")
            return
        if QMessageBox.question(
                self, "全部去皮归零",
                "对八路同时去皮归零（寄存器 0x0026 写 1）吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        sensor.submit_all_tare()
        self._tension_observer_zero_changed()
        self.tension_status.setText("张力：已排队 全部去皮归零")

    def _tension_observer_zero_changed(self, channel: int | None = None) -> None:
        selected = self._hybrid_return_index
        if self._cl_mode == "c1_position" and (channel is None or channel == self._tension_ch_map[selected]):
            if self.cl_enabled:
                self._stop_closed_loop(f"C{selected + 1} 复位绳的张力零点已更改")
            self._tension_last = None
        if self.rt_window is not None and (channel is None or channel == self._tension_ch_map[0]):
            self.rt_window.estimate_panel.invalidate_reference()

    def _tension_status_refresh(self) -> None:
        """链路状态 ~1Hz + 连接按钮文字同步；含最近一条写命令回执。"""
        s = self._tension_sensor
        if self.tension_btn is not None:
            self.tension_btn.setText("断开" if s is not None else "连接")
        if self.tension_status is None:
            return
        if s is None:
            self.tension_status.setText("张力：未连接")
            return
        received = s.received_at  # 本次串口会话最近一帧，由驱动的 perf_counter 打戳
        age_s = time.perf_counter() - received if received is not None else None
        age = f"{age_s * 1000:.0f}ms" if age_s is not None else "—"
        temp = s.temp_c
        chs = "/".join(f"CH{c}" for c in self._tension_ch_map)
        extra = f"  ⚠{s.error}" if s.error else ""
        last_write = s.last_write
        write = f"  写:{last_write[0]}→{last_write[1]}" if last_write else ""
        cutoff = time.perf_counter() - 1.0
        rate = sum(t > cutoff for t in tuple(self._tension_arrivals))
        rate_txt = f" 实收{rate}Hz"
        thread = self._tension_thread
        state = thread.link_status if thread is not None else ""
        if age_s is not None and age_s >= 1.0 and not state:
            state = "数据中断"
        self.tension_status.setText(
            f"张力：{self._tension_port_name} {chs}→C1/C2/C3"
            f"  {state} 龄{age}{rate_txt} 本次{s.sequence}帧 超时{s.timeouts} 错帧{s.protocol_errors}"
            + (f"  {temp:.1f}°C" if temp is not None else "") + write + extra)

    def _session_rel(self, now: float) -> float:
        """会话相对秒：张力链与 P4 链的曲线缓冲共用同一时间零点 t0。
        t0 缺失（张力先于 P4 连接）时由本帧锚定；P4 后连会清缓冲并重置
        t0（_connect_poll），基准始终一致。P1 修复（2026-11-04）：张力类
        通道原先直接存开机绝对秒，与其它通道的相对秒混画时整体跑出视野。"""
        if self.t0 is None:
            self.t0 = now
            global SCOPE_WINDOW_T0
            SCOPE_WINDOW_T0 = time.time()
        return now - self.t0

    def _on_tension_sample(self, f1: float, f2: float, f3: float) -> None:
        """张力样本落点（ZNSV 驱动经通道映射×系数换算后调用）：推通道缓冲并记录
        最新样本（时间戳供年龄计算与守卫的 300ms 过期判定）。"""
        now = time.monotonic()
        rel = self._session_rel(now)
        for i, v in enumerate((f1, f2, f3), start=1):
            ch = self.channels.get(f"tension_f{i}")
            if ch is not None:
                ch.buf.append(rel, v)
        self._tension_last = (now, [f1, f2, f3])
        self._push_force_obs_curves(rel)
        self._update_recovery_flag([f1, f2, f3])

    def _update_recovery_flag(self, fvals) -> None:
        """恢复态 300ms 自动清（PLAN D1）：三缆连续进界 300ms → 清标志。

        挂在张力样本入口（250Hz 数据驱动，闭环未跑也判定——启动前标志
        本就是 False，无害）。"""
        if not getattr(self, "_force_recovery", False):
            self._recovery_ok_since = None
            return
        fmin, fmax, _ok = self._effective_flimits()
        if not _ok:
            return
        if all(fmin <= v <= fmax for v in fvals):
            since = self._recovery_ok_since
            if since is None:
                self._recovery_ok_since = time.monotonic()
            elif time.monotonic() - since >= 0.3:
                self._force_recovery = False
                self._recovery_ok_since = None
                self._ui_call(self._ctrl_status, "🪢 恢复完成：三缆进界并稳定 300ms，"
                              "闭环继续持有预紧（手动停止请按停止闭环）", log=False)
        else:
            self._recovery_ok_since = None

    def _push_force_obs_curves(self, rel: float) -> None:
        """τ 双向 + 张紧 t 常驻曲线（数据驱动：连着张力串口+有位姿就画，
        不依赖闭环运行——观测者视角，与控制解耦）。rel=会话相对秒。

        τ 用与控制律同一条 θ_model 链（含 δ、0.1° 缓存）；无 n̂ 的位姿
        t 记 NaN（曲线断口=该位姿张紧在几何上不可定义）。"""
        pose = self._wrist_pose_now()
        if pose is None:
            return
        fvals = self._tension_last[1]
        tau = self._tau_meas(pose[0], pose[1], fvals)
        if tau is not None:
            ch_r = self.channels.get("force_tau_roll_meas")
            ch_p = self.channels.get("force_tau_pitch_meas")
            if ch_r is not None:
                ch_r.buf.append(rel, tau[0])
            if ch_p is not None:
                ch_p.buf.append(rel, tau[1])
        ch_t = self.channels.get("tension_preload")
        if ch_t is not None:
            geo = self._force_geo(pose[0], pose[1])
            if geo is None:
                return
            _, nd = geo
            t_val = (sum(fvals[i] * nd[i] for i in range(3))
                     if nd is not None else math.nan)
            ch_t.buf.append(rel, t_val)

    def _set_tension_guard_saved(self, key: str, text: str) -> None:
        """守卫阈值文本实时镜像进持久存档（textChanged 驱动，无感同步）。"""
        self._tension_guard_saved[key] = text

    def _set_tension_link_saved(self, key: str, text: str) -> None:
        """观测台串口号/波特率选择实时镜像进持久存档。"""
        self._tension_link_saved[key] = text

    def _tension_guard(self, roll_deg: float, pitch_deg: float):
        """闭环内每拍调用：过载→停闭环；返回 (ev | None, 提示文本 | None)。

        阈值来自 _effective_flimits（PLAN v8.2 D5 单源：边界行与守卫框取严）
        ——守卫框留空时边界行兜底，位置模式始终有过载停环。"""
        fmin_eff, fmax_eff, ok = self._effective_flimits()
        if not ok:
            if self._safety_on():
                # fail-closed：阈值不合法时"守卫未启用"等于没有保护，必须停环。
                self._stop_closed_loop("张力阈值非法（需 fmin<fmax）：守卫无法生效")
                return None, "⚠阈值非法 → 已停环（不放行无保护的闭环）"
            return None, "⚠阈值非法（安全保护已关）→ 守卫未启用"
        if self._tension_last is None:
            return None, None
        ts, fvals = self._tension_last
        age_ms = (time.monotonic() - ts) * 1000.0
        dr, dp = (self.wrist_calib.zero_offset_deg
                  if self.wrist_calib is not None else (0.0, 0.0))
        try:
            cfg = TensionConfig(f_min_n=fmin_eff, f_max_n=fmax_eff)
        except ValueError:
            return None, "⚠阈值非法（需 fmin<fmax）→ 守卫未启用"
        ev = tension_evaluate(fvals, age_ms, cfg,
                              # 2026-11-23：和 `_force_geo` 用同一套模型角换算
                              # （原来漏了 roll 换号 → 守卫算 R 用的是镜像位姿，
                              #  与力控实际 R 不同号，τ 显示跟着乱）
                              math.radians(MODEL_AXIS_SIGN[0] * roll_deg + dr),
                              math.radians(pitch_model_deg(pitch_deg) + dp))
        if ev.flags & TENSION_OVERLOAD:
            # 过载去抖（2026-11-23）：目标贴着 f_max 时，内环一次正常超调
            # （实测 25.06~26.05）就会把环停掉，表现为"跑一会就自动停"。
            # 连续 OVERLOAD_STOP_TICKS 拍（30 ms）都超限才真停，单拍毛刺放过。
            self._overload_streak = getattr(self, "_overload_streak", 0) + 1
            if self._overload_streak >= OVERLOAD_STOP_TICKS:
                cables = "+".join(f"C{i+1}" for i, v in enumerate(ev.overload) if v)
                self._stop_closed_loop(f"张力过载 {cables} ≥ {cfg.f_max_n:g}N")
        else:
            self._overload_streak = 0
        return ev, f"f=[{fvals[0]:.1f},{fvals[1]:.1f},{fvals[2]:.1f}]N"

    # ---------- 标定数据记录（被动，不驱动电机） ----------
    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            if not self.cl_enabled:
                self._ctrl_status("记录就绪：闭环启动后按 100Hz 记录（先做慢速单轴扫掠）")
            return
        self._finalize_calib_rec()

    def _record_calib_row(self, roll: float, pitch: float) -> None:
        """_cl_tick 每拍调用：累积一行（角度/电机/张力 + R/n/τ/trim/ω/flags）。"""
        now = time.monotonic()
        if self._calib_rec is None:
            self._calib_rec = {
                "t0": now, "t": [], "roll": [], "pitch": [],
                "m27": [], "m28": [], "m29": [],
                "f1": [], "f2": [], "f3": [],
                "rr1": [], "rr2": [], "rr3": [],
                "rp1": [], "rp2": [], "rp3": [],
                "n1": [], "n2": [], "n3": [],
                "tau_r": [], "tau_p": [],
                "trim1": [], "trim2": [], "trim3": [],
                "omega_r": [], "omega_p": [],
                "mode": [], "flags": [],
            }
            self._rec_prev = None
        rec = self._calib_rec
        rec["t"].append(now - rec["t0"])
        rec["roll"].append(roll)
        rec["pitch"].append(pitch)
        for m, key in zip(SERVO_TARGETS, ("m27", "m28", "m29")):
            rec[key].append(self.channels[f"m{m}_abs"].buf.last())
        f_stale = (self._tension_last is None
                   or (now - self._tension_last[0]) * 1000.0 > 300.0)
        if f_stale:
            fvals = (math.nan,) * 3
        else:
            fvals = self._tension_last[1]
        for i, key in enumerate(("f1", "f2", "f3")):
            rec[key].append(fvals[i])

        geo = self._force_geo(roll, pitch)
        if geo is not None:
            out, nd = geo
            for i in range(3):
                rec[f"rr{i + 1}"].append(out.r_m[ROLL][i] * 1000.0)
                rec[f"rp{i + 1}"].append(out.r_m[PITCH][i] * 1000.0)
                rec[f"n{i + 1}"].append(
                    nd[i] if nd is not None else math.nan)
            if not any(math.isnan(v) for v in fvals):
                rec["tau_r"].append(sum(out.r_m[ROLL][i] * fvals[i]
                                        for i in range(3)))
                rec["tau_p"].append(sum(out.r_m[PITCH][i] * fvals[i]
                                        for i in range(3)))
            else:
                rec["tau_r"].append(math.nan)
                rec["tau_p"].append(math.nan)
            flags = ((1 if out.low_pitch_zone else 0)
                     | (2 if not out.angle_in_range else 0)
                     | (4 if f_stale else 0))
        else:
            for i in range(3):
                rec[f"rr{i + 1}"].append(math.nan)
                rec[f"rp{i + 1}"].append(math.nan)
                rec[f"n{i + 1}"].append(math.nan)
            rec["tau_r"].append(math.nan)
            rec["tau_p"].append(math.nan)
            flags = 8 | (4 if f_stale else 0)

        for i in range(3):
            rec[f"trim{i + 1}"].append(self._force_trim[i])
        prev = getattr(self, "_rec_prev", None)
        if prev is not None and now - prev[0] > 1e-6:
            dt = now - prev[0]
            rec["omega_r"].append((roll - prev[1]) / dt)
            rec["omega_p"].append((pitch - prev[2]) / dt)
        else:
            rec["omega_r"].append(math.nan)
            rec["omega_p"].append(math.nan)
        self._rec_prev = (now, roll, pitch)
        rec["mode"].append({"position": 0, "tension": 1,
                            "tight": 2, "force": 3, "c1_position": 5}.get(self._cl_mode, -1))
        rec["flags"].append(flags)

    def _finalize_calib_rec(self) -> None:
        rec = self._calib_rec
        self._calib_rec = None
        if rec is None or len(rec["t"]) < 10:
            if rec is not None:
                self._ctrl_status("标定记录已取消（不足 10 行）")
            return
        name = "wrist_calib_capture_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        path = dump_csv(
            name,
            header=["roll_deg", "pitch_deg", "m27_abs", "m28_abs", "m29_abs",
                    "f1_n", "f2_n", "f3_n",
                    "rr_c1_mm", "rr_c2_mm", "rr_c3_mm",
                    "rp_c1_mm", "rp_c2_mm", "rp_c3_mm",
                    "n1", "n2", "n3",
                    "tau_roll_nm", "tau_pitch_nm",
                    "trim1_c", "trim2_c", "trim3_c",
                    "omega_roll_dps", "omega_pitch_dps",
                    "mode_code", "flags"],
            t=rec["t"],
            columns=[rec["roll"], rec["pitch"], rec["m27"], rec["m28"],
                     rec["m29"], rec["f1"], rec["f2"], rec["f3"],
                     rec["rr1"], rec["rr2"], rec["rr3"],
                     rec["rp1"], rec["rp2"], rec["rp3"],
                     rec["n1"], rec["n2"], rec["n3"],
                     rec["tau_r"], rec["tau_p"],
                     rec["trim1"], rec["trim2"], rec["trim3"],
                     rec["omega_r"], rec["omega_p"],
                     rec["mode"], rec["flags"]])
        if path is None:
            self._ctrl_status("标定记录落盘失败（路径校验不过）")
            return
        self._ctrl_status(
            f"💾 标定记录 {len(rec['t'])} 行 → {name}；"
            f"识别：python -m tools.identify_wrist_calib run_data/scope_exports/{name}")

    def _default_wrist_calib(self) -> WristCalib:
        """内建默认标定：k 幅值 = 结构常数，符号 = −trim方向；δ = 0。

        k 的**幅值**不是拟合结果：`4096 counts/圈 ÷ (2π·绕线半径)`，逐路不同
        （M27 r=6.0mm、M28/M29 r=5.5mm，见 `K_NOMINAL_ABS`）。
        k 的**符号**是硬件方向，与力控共用同一条约定：

            sign(k_i) = −sign(trim_sign_i)

        这样只需要维护「trim方向」一处；trim方向非法时退回三路收绳（当前台架结论）。
        """
        ts = self._force_trim_sign()
        if ts and len(ts) == 3 and all(s in (-1, 1) for s in ts):
            signs = [-float(s) for s in ts]
        else:
            signs = [-1.0, -1.0, -1.0]
        return WristCalib([s * n for s, n in zip(signs, K_NOMINAL_ABS)],
                          [0.0, 0.0])

    def _load_wrist_calib(self, quiet: bool = False) -> None:
        """载入 wrist_calib.json；文件不存在/无效时用**内建默认**（不再要求手点）。

        `wrist_calib.json` 现在是**可选覆盖**：k 的幅值是结构常数、符号由
        「trim方向」反推、δ 默认 0 —— 正常机器不需要任何文件。
        quiet=True 供启动自动载入：不写状态行，免得盖掉开机提示。
        """
        data = load_named_json("wrist_calib.json")
        if not data:
            self.wrist_calib = self._default_wrist_calib()
            k = self.wrist_calib.k_counts_per_m
            self.cl_calib_label.setText(
                f"标定：内建默认 k=[{k[0]:+.6g},{k[1]:+.6g},{k[2]:+.6g}] c/m"
                f"  δ=[+0.00,+0.00]°（结构常数，无需载入文件）")
            return
        calib, err = parse_wrist_calib(data)
        if calib is None:
            self.wrist_calib = self._default_wrist_calib()
            self.cl_calib_label.setText(
                f"标定：文件无效（{err}）→ 用内建默认（结构常数 + trim方向反号）")
            return
        self.wrist_calib = calib
        k = calib.k_counts_per_m
        d = calib.zero_offset_deg
        # k 是**结构常数** = 4096 counts/圈 ÷ (2π·绕线半径)，**逐路不同**
        # （2026-11-11 用户实测：M27 r=6.0mm、M28/M29 r=5.5mm → 见 K_NOMINAL_ABS）。
        # 不是拟合结果；旧文案一律标"草稿/未识别"，把正确值说成没标定，已改正。
        # 符号另属方向约定（k>0 ⇒ counts↑=放绳），用 ±|k| 判定。
        nominal = all(abs(abs(v) - n) <= max(1.0, n * 1e-4)
                      for v, n in zip(k, K_NOMINAL_ABS))
        # 符号只做"翻译"，不下结论（k 的定义是 Δcounts = k·Δl ⇒ k>0 该路 counts↑=放绳）。
        # 符号是**逐路**的：同一台架也可能某一路电机反向安装，所以不搞"三路必须同号"。
        dirs = ["收绳" if v < 0 else "放绳" for v in k]
        if dirs[0] == dirs[1] == dirs[2]:
            sign_txt = f"按 k 符号：counts↑={dirs[0]}"
        else:
            sign_txt = "按 k 符号：" + " ".join(
                f"C{i + 1}↑={dirs[i]}" for i in range(3))
        warn = self._sign_invariant_note()
        self.cl_calib_label.setText(
            f"标定 k=[{k[0]:+.6g},{k[1]:+.6g},{k[2]:+.6g}] c/m  δ=[{d[0]:+.2f},{d[1]:+.2f}]°"
            + (f"（标称 k：绕线半径 {SPOOL_RADIUS_M[0]*1000:.1f}/"
               f"{SPOOL_RADIUS_M[1]*1000:.1f}/{SPOOL_RADIUS_M[2]*1000:.1f}mm"
               f" + 4096 c/圈，固定值）" if nominal
               else "（已识别）") + f"  {sign_txt}"
            + (f"<br><b style='color:#f87171'>{warn}</b>" if warn else ""))
        if warn and not quiet:
            self._ctrl_status(f"⚠ 符号自检：{warn}")
        if not quiet:
            self._ctrl_status(
                "📥 已载入腕部标定（%s）；需与「trim方向」满足 "
                "sign(trim_sign)=−sign(k)" % sign_txt)

    def _wrist_pose_now(self):
        """当前腕部反馈位姿 (roll_deg, pitch_deg) | None（J16/J17 缺数据或未归零）。"""
        vals = []
        for j in (16, 17):
            raw = self._enc_filt_raw.get(j)
            base = self.angle_baseline.get(j)
            if raw is None or base is None:
                return None
            vals.append(self._angle_delta(self._axis_deg(j, raw), base))
        return vals

    def _r_at_current(self):
        """当前位姿的几何 R 求值（**模型系**，与 `_force_geo` 同一套换算）。

        返回 (roll_deg, pitch_deg, WristModelOut, roll_rad, pitch_rad) | None——
        rad 为 θ_model（已加 δ），供 positive_null_direction 等复用。

        2026-11-23 修正：原来这里**漏了 `MODEL_AXIS_SIGN[0]`**（roll 换号），
        于是观测台的 R 矩阵表用的是"镜像 roll"的几何，和力控实际用的 R 不一致
        （同一时刻两处显示的 R 不同号 → 越看越乱）。现在与 `_force_geo` 对齐。
        """
        pose = self._wrist_pose_now()
        if pose is None:
            return None
        roll_deg, pitch_deg = pose
        dr, dp = (self.wrist_calib.zero_offset_deg
                  if self.wrist_calib is not None else (0.0, 0.0))
        rr = math.radians(MODEL_AXIS_SIGN[0] * roll_deg + dr)
        pr = math.radians(pitch_model_deg(pitch_deg) + dp)
        out = wrist_eval(rr, pr)
        if not out.math_valid:
            return None
        return roll_deg, pitch_deg, out, rr, pr

    # ---------- 目标扫掠（闭环目标正弦；跟随/带宽测试用） ----------
    def _sweep_key(self) -> str:
        idx = self.sweep_axis.currentIndex()
        return "roll_tgt" if idx == 0 else "pitch_tgt"

    def _sweep_seed(self) -> None:
        """按当前两个目标框播种：中心=当前目标，单轴也用它做起点。"""
        def _f(key: str) -> float:
            try:
                return float(self.cl_edits[key].text().strip().replace("−", "-"))
            except ValueError:
                return 0.0
        self._sweep_center = (_f("roll_tgt"), _f("pitch_tgt"))
        idx = self.sweep_axis.currentIndex()
        if idx == 2 and self.sweep_center0.isChecked():
            self._sweep_center = (0.0, 0.0)   # 过零对称：正负都扫到
        # 2026-11-26 去掉三角波后不再需要 _sweep_val/_sweep_dir（只有三角波用）
        self._sweep_phase = 0.0
        self._sweep_ts = None

    def _on_sweep_toggled(self, on: bool) -> None:
        if not on:
            self._ctrl_status("扫掠已停（目标保持当前值）")
            return
        self._sweep_seed()
        if not self.cl_enabled:
            self._ctrl_status("扫掠已就绪：启动闭环后开始走波形（三角=录标定 / 正弦=跟随测试）")
        else:
            self._ctrl_status("扫掠运行中：目标框被自动改写，取消勾选停止")

    def _on_sweep_axis_changed(self, _index: int) -> None:
        """扫掠中切轴：按新轴目标框重新播种 + 相位归零（2026-11-10 修复）。"""
        self._sweep_seed()
        self._sync_sweep_widgets()

    def _sync_sweep_widgets(self) -> None:
        """按「轴」禁用无关控件 + 刷新右侧「生效：…」提示。

        2026-11-26 去掉三角波后，这里只按轴开关 PITCH 幅值：
        · 单轴（ROLL/PITCH）：PITCH 幅值不生效；
        · 双轴正弦：PITCH 幅值生效。
        频率 / ROLL 幅值**永远生效**（不再有"被波形禁用"这一说）。
        """
        idx = self.sweep_axis.currentIndex()
        dual = idx == 2
        amp_p = getattr(self, "sweep_amp_p", None)
        if amp_p is not None:
            amp_p.setEnabled(dual)
        lbl = getattr(self, "sweep_active_label", None)
        if lbl is not None:
            try:
                axis = self.sweep_axis.currentText()
                txt = (f"生效：{axis} · {self.sweep_freq.value():g} Hz"
                       f" · 幅值 {self.sweep_amp.value():g}°")
                if dual:
                    txt += f"/{self.sweep_amp_p.value():g}°"
                lbl.setText(txt)
            except (AttributeError, RuntimeError):
                pass

    def _sweep_tick(self, dt: float | None = None) -> None:
        """20Hz：闭环运行且勾选扫掠时推进所选轴的**正弦**目标。

        2026-11-26 用户要求去掉三角波 —— 现在只有正弦：
          · 单轴：target = 幅值·sin(2πf·t)（中心 0，正负都到）
          · 双轴正弦：target = 中心 + 各自幅值·sin(2πf·t)
        峰值角速度需求 = 幅值×2πf —— 超过每拍限幅折算的速度上限
        （max_step_f×100Hz）就会削顶/滞后，正是带宽测试要观察的现象。

        dt：本拍步长（s）。缺省按真实墙钟算——旧版写死 0.05，主线程忙时
        定时器延迟会让实际频率低于设定值，带宽测试会系统性低估（2026-11-10 修复）。
        显式传 dt 供测试复现固定步长。
        """
        if not (self.cl_enabled and self.sweep_check.isChecked()):
            return
        now = time.monotonic()
        last = getattr(self, "_sweep_ts", None)
        self._sweep_ts = now
        if dt is None:
            # 首拍按标称 50ms；卡顿/挂起时钳到 0.2s，别让相位一次跳半圈
            dt = 0.05 if last is None else min(max(now - last, 0.001), 0.2)
        lim = self._cl_fval("limit", 25.0, 1.0, 90.0)
        self._sweep_phase = (self._sweep_phase
                             + 2.0 * math.pi * self.sweep_freq.value() * dt)
        self._sweep_phase %= 2.0 * math.pi
        s = math.sin(self._sweep_phase)
        amp = min(self.sweep_amp.value(), lim)
        if self.sweep_axis.currentIndex() == 2:          # 双轴正弦（同相位）
            ap = min(self.sweep_amp_p.value(), lim)
            r = max(-lim, min(lim, self._sweep_center[0] + amp * s))
            p = max(-lim, min(lim, self._sweep_center[1] + ap * s))
            self.cl_edits["roll_tgt"].setText(f"{r:+.2f}")
            self.cl_edits["pitch_tgt"].setText(f"{p:+.2f}")
            return
        v = max(-lim, min(lim, amp * s))
        self.cl_edits[self._sweep_key()].setText(f"{v:+.2f}")

    def _toggle_closed_loop(self) -> None:
        if self.cl_enabled:
            self._stop_closed_loop("手动停止", popup=False)
            return
        if not self.armed:
            self._want_closed_loop = True
            self._ctrl_status("闭环启动：先自动使能…")
            self._on_enable_direct()
            return
        self._start_closed_loop()

    def _start_cl_gate_reason(self):
        """启动闭环门禁（纯读，供按钮与拒绝弹窗 1Hz 复查共用）。

        覆盖：J16/17 数据 / 标定载入 / 力控张力新鲜度+参数快检 / 至少一绳 /
        P4 活动域。顺序与旧内联版一致；抽取后门禁先于一切副作用（拒绝时
        不再停斜坡/自动归零——失败不留痕，下次成功启动照常补做）。"""
        for j in (16, 17):
            if self.angle_baseline[j] is None:
                v = self.channels[f"enc_raw_{j}"].buf.last()
                if math.isnan(v):
                    return "闭环启动失败：J16/J17 无数据"
        if self._cl_mode in ("position", "c1_position") and self.wrist_calib is None:
            # 防御：正常情况下 `_default_wrist_calib()` 保证不为 None
            # （k 幅值=结构常数、符号=−trim方向）。这里只兜住人为清空的路径。
            return ("位置模式缺少 k/R 换算参数：标定对象被清空 → "
                    "点「📥 重载标定（可选）」或重启上位机恢复内建默认")
        if self._cl_mode in ("force", "tension", "tight", "impedance"):
            last = self._tension_last
            if last is None or (time.monotonic() - last[0]) > 0.5:
                return "力控启动失败：无新鲜张力数据（先在观测台连接张力串口）"
            # 参数合法性按模式各自校验（(0,0) 占位快检；逐拍还有真位姿检查）
            pre = {"force": lambda: self._force_params_v2(0.0, 0.0),
                   "tension": lambda: self._tension_params(),
                   "impedance": lambda: self._impedance_params(0.0, 0.0),
                   "tight": lambda: self._tight_params(0.0, 0.0, quiet=True)}[
                self._cl_mode]()
            if pre is None:
                return "力控启动失败：力控参数非法（含 trim方向格式）"
        if self._cl_mode == "c1_position":
            params = self._read_c1_position_params()
            if params is None:
                return "混合模式：专用参数无效，请检查目标、增益和限幅"
            _, _, reason = self._c1_position_feedback(params.c1.max_n, params.return_cable)
            if reason is not None:
                return f"混合模式：{reason}"
            pose = self._wrist_pose_now()
            if pose is not None and self._c1_position_geometry(*pose, params.return_cable) is None:
                return "混合模式：姿态无效或两根角度绳无法独立控制双轴"
        motors = self._enabled_motors()
        if self._cl_mode == "c1_position" and not set(MOTOR_FOR_CABLE).issubset(motors):
            return "混合模式：C1、C2、C3 对应的电机都需勾选"
        if not motors:
            return "闭环启动失败：未勾选任何绳"
        # 0xD3 批量帧在固件里按 active_motor_mask 收窄：活动域缺电机时启动闭环，
        # 会出现"只有一台动"（点动走 0xDE 不查掩码，所以看起来点动正常）。
        missing = self._scope_missing(motors)
        if missing:
            return (f"⛔ 闭环启动失败：P4 活动域不含 {self._motor_list_text(missing)}"
                    f"（批量目标会被固件按活动域收窄）——先停止，再重新「使能直控」重建活动域")
        return None

    def _start_closed_loop(self) -> None:
        reason = self._start_cl_gate_reason()
        if reason:
            self._reject("启动闭环", reason,
                         recheck=self._start_cl_gate_reason)
            return
        # ramp/闭环互斥（PLAN v8.2 D9，存量 bug 修复）：斜坡还在改 targets 时
        # 启动闭环会互相覆盖——启动即停斜坡并清状态。
        self._ramp_timer.stop()
        self._ramp_state.clear()
        # 角度基准未设时以当前角为零点，避免相对基准为 None。
        # （数据可用性已在门禁确认：无基准且无数据早被拒，此处必能设上。）
        # 这次启动做了自动归零 → 立即落盘，保证重启可恢复（BUG1）；
        # 已有基准（含 _load_layout 恢复的）不动、不覆盖。
        if self._auto_zero_baselines():
            self._save_layout()
        if self._cl_mode in ("position", "c1_position"):
            # 2026-11-10 修复①：origin 记的是「使能那一刻」的位置。使能后点动过
            # （或重力下沉），启动闭环会先朝旧起点跳一段。位置模式的起点改用
            # 启动时的实测位置；无数据的电机保留原值。
            for m in SERVO_TARGETS:
                v = self.channels[f"m{m}_abs"].buf.last()
                if v is not None and not math.isnan(v):
                    self._motor_origin[m] = int(v)
                    # 同时把"上一帧指令"对齐到实测：否则首拍 _clamp_per_tick 会从
                    # 旧指令（点动目标/使能位置）向实测 slews 追，纯PID 尤其明显
                    # （它的输出基准就是实测，会被旧 targets 往回拽 100+ counts）。
                    self.targets[m] = int(v)
            if self._cl_mode == "c1_position":
                pose = self._wrist_pose_now()
                if pose is not None:
                    for key, value in zip(("roll_tgt", "pitch_tgt"), pose):
                        edit = self._c1_position_edits[key]
                        if not edit.text().strip():
                            edit.setText(f"{value:.2f}")
                self._c1_position_state.reset()
                self._c1_angle_state.reset()
                self._c1_diag_rows.clear()
            else:
                for key, default in (("kp", 0.2), ("ki", 0.05), ("kd", 0.05),
                                     ("k_ff", 0.3), ("deadband", 0.3),
                                     ("limit", 25.0), ("max_step_f", 20.0)):
                    e = self.cl_edits.get(key)
                    if e is not None and not e.text().strip():
                        e.setText(f"{default:g}")
                self._pos_pid_state.reset()
        # 2026-11-23 修复：**impedance 也要走这段初始化**。原来只列了
        # force/tension/tight，阻抗模式启动时 `_force_base` 保持 None，
        # `_apply_force_step` 里 `base - max_trim` 直接 TypeError →
        # 工作线程每拍抛异常 → 现象就是"点了启动，完全没反应"。
        if self._cl_mode in ("force", "tension", "tight", "impedance"):
            # 位置基准 = 电机**实测**当前位置（不是上次指令）；按缆序映射
            # （与 _apply_force_step 同序，MOTOR_FOR_CABLE 换序时基准跟着换）。
            # 旧实现取 targets（上次指令），但力控下发不写 targets，重启会把
            # 基准退回力控前的旧目标 → 第一拍目标跳变（trim 被整段丢掉）。
            self._force_base = [self._motor_pos_now(m) for m in MOTOR_FOR_CABLE]
            self._force_state.reset()
            self._tension_state.reset()
            self._force_trim = [0.0, 0.0, 0.0]
            self._tau_trim = [0.0, 0.0]        # 力矩修正积分：每轮从零起
            # 阻抗 D 项：角速度基准与滤波状态每轮清零（否则首拍会拿上一轮残留
            # 的角度算出一个巨大速度 → D 给反方向尖峰）
            self._imp_rate.reset()
            self._imp_omega = (0.0, 0.0)
            self._imp_d_tau = (0.0, 0.0)
            self._auto_t0_pc = None             # 自动调参：每轮从第 1 档起
            self._auto_stage = -1
            self._auto_kind = ""
            self._force_need_send = True   # 首拍把 base+0 发下去，先按住当前位置
            # 正弦跟随：起环就等于重新开始一次测试（相位归零 + 新记录文件）。
            # 必须放在这里：`_stop_closed_loop_now` 会关闭记录文件，若只在勾选时
            # 开文件，用户"先勾再启动"就会得到一个立刻被关掉的文件。
            # 正弦 / 自动调参：起环 = 一次新测试（相位归零 + 新记录文件）。
            # ⚠ 2026-11-25 现场事故：只勾了「自动调参」而**没有重新点勾选**
            # （复选框保持在上次的状态），起环时这里只判了「正弦跟随」→
            # 整轮 98 s 没有开记录文件，日志却报"数据已保存"。
            # 现在两个开关任一为真都开文件。
            _auto_on = (getattr(self, "cl_auto_tune_check", None) is not None
                        and self.cl_auto_tune_check.isChecked())
            _sine_on = (getattr(self, "cl_tension_sine_check", None) is not None
                        and self.cl_tension_sine_check.isChecked())
            # 2026-11-26：混合模式的测试开关也要在这里归零/开文件，
            # 否则「先勾选再起环」时计时基准会带着上一轮的残留。
            _mix_auto = (getattr(self, "cl_c1_auto_check", None) is not None
                         and self.cl_c1_auto_check.isChecked())
            _mix_sine = (getattr(self, "cl_c1_sine_check", None) is not None
                         and self.cl_c1_sine_check.isChecked())
            if _mix_auto:
                self._auto_round = 0
            if _sine_on or _auto_on or _mix_auto or _mix_sine:
                self._sine_t0 = None
                self._sine_t0_pc = None
                self._auto_t0_pc = None
                self._auto_stage = -1
                self._auto_kind = ""
                self._sine_log_open()
        # 本轮闭环实际驱动的电机快照（运行中改勾选会先停闭环，见 _on_cable_enable_toggled）
        motors = self._enabled_motors()
        self._cl_motor_on = frozenset(motors)
        self._overload_streak = 0        # 过载去抖计数每轮从零起
        self.cl_enabled = True
        self.cl_return_cable_combo.setEnabled(False)
        self.cl_btn.setText("■ 停止闭环")
        self.cl_btn.setStyleSheet(
            f"font-weight: bold; padding: 6px; color: white; background-color: {AT.T('good')};")
        self._refresh_motor_rows()   # 点动/输入框/Go 按勾选×使能×闭环统一收口
        # 起点可能刚被刷新 → 参数缓存（含 origin）必须立刻失效，否则首拍仍用旧起点，
        # 会先朝旧位置走几拍（≤5 拍 × max_step）再被拉回来。
        self._cl_param_cache = None
        # 2026-11-19：控制环改由**独立线程**驱动（不再用 GUI 线程的 QTimer）。
        # 100 Hz；与 P4 内环、舵机总线 10 ms 周期对齐（200 Hz 被总线卡住做不到）。
        self._cl_stop_request = None
        old = self._cl_loop
        if old is not None and old.isRunning():
            old.stop()
            old.wait(500)
        self._cl_loop = _ClLoopThread(self, CL_LOOP_PERIOD_S)
        # 先把参数快照生成好（GUI 线程），再放工作线程跑，避免首拍拿不到参数
        self._refresh_cl_param_cache()
        # 启动自检：命令能力 = max_step × 频率，超过伺服能力时有饱和/振荡风险
        self._check_cmd_authority()
        self._cl_tick_ts = None   # 首拍 dt 用默认 0.01
        self._cl_loop.start()
        # 诊断记录（2026-11-19）：每次启动都清空 → 「一次运行 = 一份 diag CSV」。
        # 这样导出时不会把上一次运行的残留混进来。
        if self._cl_mode != "c1_position":
            self._diag_rows.clear()
            self._pos_diag_rows.clear()
        self._apply_run_prio()    # 跑环即降档：主图 3:1、表格/观测台 15Hz
        self._cl_tick_count = 0   # 每轮从零起（diag 抽样相位、状态行刷新都靠它）
        if self._cl_mode == "force":
            mode = "力矩控制"
        elif self._cl_mode == "impedance":
            mode = "阻抗控制"
        elif self._cl_mode == "tension":
            mode = "张力控制"
        elif self._cl_mode == "tight":
            mode = "张紧控制"
        elif self._cl_mode == "c1_position":
            mode = f"C{self._hybrid_return_index + 1} 张力 + ROLL/PITCH 角度"
        else:
            # 位置模式只有一种结构：PID+前馈（绳长前馈 + PI，每拍限幅）
            mode = "位置·" + self._pos_loop_name()
        off = [m for m in SERVO_TARGETS if m not in self._cl_motor_on]
        scope_note = f"，驱动 {self._motor_list_text(motors)}"
        if off:
            scope_note += f"，未勾选 {self._motor_list_text(off)} 不下发"
            if self._cl_mode == "position":
                scope_note += "（缺绳纠偏不全，盯紧软限位）"
        if self._cl_mode == "position":
            # 前馈(k_ff) + PI(kp)：等效位置增益 ≈ k_ff+kp。
            # kp 沿用旧的"纯 P 增益"口径会偏大：只提示，不改用户的数。
            kp_now = self._cl_fval("kp", 0.3, 0.0, 5.0)
            k_ff_now = self._cl_fval("k_ff", 0.3, 0.0, 1.0)
            if kp_now > 0.5:
                scope_note += (f"（等效增益≈{k_ff_now + kp_now:.2f}，偏大时先降 kp 到 0.2~0.5）")
        sign_warn = "" if self._cl_mode == "c1_position" else self._sign_invariant_note()
        self._ctrl_status(f"✅ 闭环运行（{mode}{scope_note}）：改目标框实时跟踪，停止请按急停或停止闭环"
                          + (f"  ⚠ {sign_warn}" if sign_warn else ""))
        if self._cl_mode == "c1_position" and self._c1_position_params is not None:
            _fmn = self._c1_position_params.c1.min_n
            _fmx = self._c1_position_params.c1.max_n
        else:
            _fmn, _fmx, _ = self._effective_flimits()
        # origins 落进安全日志：位置环的绝对目标 = origin + k·Δl，出问题先查这三个起点
        _log = dict(mode=self._cl_mode, motors=list(motors),
                    origins={m: self._motor_origin.get(m) for m in SERVO_TARGETS},
                    fmin=_fmn, fmax=_fmx)
        if sign_warn:
            _log["sign_warn"] = sign_warn
        if self._cl_mode == "position":
            _log["pos_loop"] = "pid_incr"
        self._safety("CL_START", **_log)

    def _send_hold_now(self) -> bool:
        """把 27-29 目标**立即锁到实测位置**：一帧 0xD3 抢占下发。

        为什么需要：停环只是停掉 100Hz 定时器，但下行队列里可能还排着上百帧
        运动指令（最多 ~300ms 的执行量），P4 会照单执行——"按了停止闭环还在动"。
        这里先丢弃待发队列，再用优先通道发一帧"保持当前位"，让动作当场刹住。
        与急停的区别：急停发 0xCD（固件断力矩），这里只锁位置、力矩照旧。
        """
        if not self.last_servo_abs_all or len(self.last_servo_abs_all) < 30:
            return False
        if self.rx_thread is None:
            return False
        base = [int(v) for v in self.last_servo_abs_all[:30]]
        for m in SERVO_TARGETS:
            v = self.channels[f"m{m}_abs"].buf.last()
            base[m] = int(v) if v is not None and not math.isnan(v) else self._motor_pos_now(m)
        drop = getattr(self.rx_thread, "drop_pending_tx", None)
        if callable(drop):
            drop()           # 丢掉队列里尚未写出的运动指令，别让它们抢先跑
        frame = build_motor_pos_abs_cmd(base)
        try:
            ok = self.rx_thread.send(frame, priority=True)
        except TypeError:    # 兼容旧实现/测试替身
            ok = self.rx_thread.send(frame)
        if ok:
            for m in SERVO_TARGETS:
                self.targets[m] = base[m]
            self._safety("CL_HOLD", targets={m: base[m] for m in SERVO_TARGETS})
        return bool(ok)

    def _stop_closed_loop_now(self, reason: str, *, hold: bool = True,
                              popup: bool = True) -> None:
        """真正执行停环（必须在 GUI 线程）。外部一律用 `_stop_closed_loop`。"""
        """停止闭环。默认当场"刹住"（hold=True）：丢队列 + 抢占下发保持当前位。

        急停/断开时传 hold=False：那两条路径自己会发 0xCD（断力矩），
        若再发一帧"保持当前位"等于把刚断的力矩又按回去。
        popup=True 且停止的是一键紧绳会话（_tighten_cl_active）→ 弹窗告知
        停止原因（2026-11-09 用户需求：恢复中被过载/越界/丢数据打断要弹窗）。
        用户主动路径（手动停止/急停/切模式/勾选变更/断开/紧绳回滚）传
        popup=False——操作者已知原因，不再打扰；回滚有自己的专属弹窗。
        """
        self._cl_stop_request = reason or "停止"
        self._sine_log_close()               # 停环就把正弦记录收口（2026-11-24）
        # 2026-11-26：停环后目标曲线回到「界面框的值」，不再用上一拍的命令值
        self._c1_cmd_tgt = None
        loop = self._cl_loop
        self._cl_loop = None
        if loop is not None:
            loop.stop()
            if not loop.wait(500):
                self._ctrl_status("控制线程未在 0.5s 内退出（会自行停止）",
                                  log=False)
        self._cl_timer.stop()
        if hold and self.cl_enabled:
            self._send_hold_now()            # 先刹住，再做 UI/落盘记账
        was_sweep = self.sweep_check.isChecked()
        self.sweep_check.setChecked(False)   # 停闭环同时停扫掠
        if was_sweep and self._cl_mode == "position":
            # 扫掠把目标框推到过 ±幅值，停环后留在那儿，下次启动会先跳过去。
            # 用实测姿态收口：目标就停在你现在所在的角度（2026-11-10 修复）。
            pose = self._wrist_pose_now()
            if pose is not None:
                key = self._sweep_key()
                self.cl_edits[key].setText(
                    f"{pose[0] if key == 'roll_tgt' else pose[1]:+.2f}")
        self._force_recovery = False         # 恢复态随停环清除（PLAN D1）
        self._recovery_ok_since = None       # REVIEW P0-3：计时器一并清防秒清
        if not self.cl_enabled:
            self._tighten_cl_active = False
            self._apply_run_prio()   # 已是停止态：确保回到全速档
            return
        # 会话归属先判后清（弹窗放到记账最后：push 会立即跑首次复查，
        # 若在 cl_enabled=False 之前弹，紧绳门禁第 2 查还报"闭环运行中"，
        # 停止弹窗的复查行会自相矛盾——R2 自查 Finding A）。
        was_tighten = self._tighten_cl_active and popup
        self._tighten_cl_active = False
        self._overload_streak = 0        # 停环清去抖计数
        self.cl_enabled = False
        self.cl_return_cable_combo.setEnabled(True)
        self._apply_run_prio()       # 停环恢复全速（主图 33FPS、表格 30Hz、观测台 20Hz）
        self._want_closed_loop = False
        self.cl_btn.setText("▶ 启动闭环")
        self.cl_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._refresh_motor_rows()   # 输入框/Go/点动按勾选×使能恢复
        self._finalize_calib_rec()   # 闭环停止即收尾落盘（若在记录）
        self._cl_status_set(f"已停止（{reason}）")
        self._ctrl_status(f"闭环已停止：{reason}")
        self._safety("CL_STOP", reason=reason)
        if was_tighten:
            self._notify_cl_stop(reason)     # 记账完毕、状态已收敛，再弹窗

    def _stop_closed_loop(self, reason: str, *, hold: bool = True,
                          popup: bool = True) -> None:
        """停环入口（跨线程安全）。

        从工作线程调用时：只置 `_cl_stop_request`（工作线程下一拍自己退出循环），
        真正的 UI/落盘/弹窗投递到 GUI 线程执行（`_stop_closed_loop_now`）。
        从 GUI 线程调用时：当场执行，行为与旧版逐位一致。
        """
        if self._in_gui_thread():
            self._stop_closed_loop_now(reason, hold=hold, popup=popup)
            return
        self._cl_stop_request = reason
        self._ui_call(self._stop_closed_loop_now, reason, hold=hold, popup=popup)

    def _notify_cl_stop(self, reason: str) -> None:
        """一键紧绳会话的故障停环弹窗（复用 RejectDialog，动词=已停止）。

        日志/取证已由 _stop_closed_loop 完成（CL_STOP + 控制日志），这里只补
        弹窗、不写 GATE_REJECT；复查行复用紧绳门禁——故障清除（如张力回落
        fmax 内、腕回中行程内）后弹窗自动转 ✅可重试，什么时候能再按一目了然。"""
        dlg = self._reject_dlg
        if dlg is None:
            dlg = self._reject_dlg = RejectDialog(self)
        dlg.push("🪢 一键紧绳", f"闭环异常停止：{reason}",
                 recheck=lambda: self._tighten_gate_check()[0], verb="已停止")

    # ---------- 控制模式：位置 / 张力·力控 ----------
    def _on_cl_mode_changed(self, index: int) -> None:
        mode = self.cl_mode_combo.itemData(index) or "position"
        if mode == self._cl_mode:
            return
        if self.cl_enabled:
            self._stop_closed_loop("切换控制模式", popup=False)   # 运行中切模式 → 先停
        self._cl_mode = mode
        self._apply_cl_mode_visibility()
        self._save_layout()

    # 混合模式必须看得到的四条位姿曲线（当前角 + 目标角 × 两轴）
    HYBRID_CURVE_KEYS = ("pose_roll", "pose_roll_tgt",
                         "pose_pitch", "pose_pitch_tgt")

    def _ensure_hybrid_curves(self) -> None:
        """进入混合模式时**自动勾上**四条位姿曲线（只加不减，幂等）。

        为什么需要（2026-11-26 实报）：混合模式的核心是「C1 张力 + 双轴角度」，
        没有角度曲线等于瞎调；但默认预设「腕部调试」里**不含** `pose_*`，
        而通道树默认折叠 —— 现场表现就是"混控模式下看不到 ROLL/PITCH 曲线"。
        实测确认：四条 `pose_*` 通道在混合模式下**一直在正常写入**，
        纯粹是没勾选所以不画。

        只加不减：不会清掉用户已经选的其它通道；已经勾上的不动。
        """
        channels = getattr(self, "channels", None)
        if not channels:
            return
        added = []
        for key in self.HYBRID_CURVE_KEYS:
            ch = channels.get(key)
            item = getattr(ch, "tree_item", None) if ch is not None else None
            if item is None:
                continue
            if item.checkState(0) != Qt.Checked:
                # 置勾会触发 itemChanged → `_on_tree_changed` 自动建曲线
                item.setCheckState(0, Qt.Checked)
                added.append(ch.name)
        if added:
            try:
                self._ctrl_status("📈 混合模式：已自动勾选位姿曲线 —— "
                                  + "、".join(added)
                                  + "（不需要可在通道树里取消）", log=True)
            except AttributeError:
                pass

    def _apply_cl_mode_visibility(self) -> None:
        """分模式显示切换。力控三模式隐藏角度目标/参数/标定/手填行，
        各自显示专属参数行 + 共用 trim方向/限幅/fmin 行。

        2026-11-22：阻抗模式属"力控家族"（它输出力矩，走同一条②链），
        所以与三力控模式共用公共行，额外显示 K/D 行。

        2026-11-23 修复：**阻抗模式必须显示「目标角」行** —— 那一行就是 `q*`，
        是阻抗的输入。之前按"力控家族"整行隐藏，导致阻抗模式看不到、也改不了
        目标角，`_cl_fval("roll_tgt")` 只能读到看不见的旧值：
        现象就是"点了启动，腕完全没反应"（因为 q* 恰好≈当前角 → τ*=0）。
        """
        force = self._cl_mode in ("force", "tension", "tight", "impedance")
        c1_position = self._cl_mode == "c1_position"
        # 目标角行：张力/张紧/力矩不需要（目标就是 f_d / t / τ），阻抗需要。
        wants_tgt = self._cl_mode not in ("force", "tension", "tight")
        if getattr(self, "_cl_tgt_row_w", None) is None:
            return
        self._cl_tgt_row_w.setVisible(wants_tgt and not c1_position)
        self._cl_par_row_w.setVisible(not force and not c1_position)
        self._cl_step_row_w.setVisible(not c1_position)
        self._cl_model_row_w.setVisible(not force)
        self.cl_calib_label.setVisible(not force)
        self._cl_force_row_w.setVisible(self._cl_mode == "force")
        # 内环增益 Kp_f/Ki_f + 积分上限：四个力控模式都在用，就都显示
        # （2026-11-24 之前它们被藏在张力专用行里，力矩/阻抗模式看不到也改不了）
        loop_row = getattr(self, "_cl_loop_row_w", None)
        if loop_row is not None:
            loop_row.setVisible(force)
        imp_row = getattr(self, "_cl_imp_row_w", None)
        if imp_row is not None:
            imp_row.setVisible(self._cl_mode == "impedance")
        self._cl_tension_row_w.setVisible(self._cl_mode == "tension")
        self._cl_c1_position_row_w.setVisible(c1_position)
        self.cl_roll_check.setVisible(not c1_position)
        self.cl_pitch_check.setVisible(not c1_position)
        self._cl_tight_row_w.setVisible(self._cl_mode == "tight")
        self._cl_force_common_row_w.setVisible(force)
        self._cl_bound_row_w.setVisible(force)
        # 2026-11-26：fmin/fmax 单独一行，**位置模式也显示** —— 位置模式每拍跑
        # `_tension_guard`，过载停环阈值就是它们，之前藏在只有力控可见的边界行里。
        flim_row = getattr(self, "_cl_flim_row_w", None)
        if flim_row is not None:
            flim_row.setVisible(not c1_position)
        # 2026-11-26：扫掠允许 **位置模式 + 阻抗模式**。
        # 阻抗的输入就是目标角 q*，而扫掠改的正是 q* —— 这是测阻抗阶跃/频响
        # 最直接的手段。之前把 impedance 一并算进"力控家族"禁掉，
        # 表现就是"阻抗模式下扫掠那块看得见却是灰的"（用户实报）。
        sweep_ok = self._cl_mode in ("position", "impedance")
        if not sweep_ok:
            self.sweep_check.setChecked(False)
        self.sweep_check.setEnabled(sweep_ok)
        # 2026-11-26：混合模式自动补上位姿曲线（进入该模式时调用，只加不减）
        if c1_position:
            try:
                self._ensure_hybrid_curves()
            except (AttributeError, RuntimeError):
                pass
        # 2026-11-26：切完模式也把子控件状态刷一遍（否则从力控切回来时，
        # 「生效：…」那行会停在旧文字上，仍然让人以为频率锁死）
        try:
            self._sync_sweep_widgets()
        except (AttributeError, RuntimeError):
            pass

    # ---------- 位置环结构（2026-11-23 定案：绳长前馈 + PI，每拍限幅） ----------
    POS_LOOP_NAME = "PID+前馈"

    def _pos_loop_name(self) -> str:
        """状态行/日志里的位置环结构名（唯一结构，保留方法供调用点不变）。"""
        return self.POS_LOOP_NAME

    def _force_geo(self, roll, pitch):
        """当前位姿的 (wrist_eval, n̂)，带 0.1° 网格缓存（三力控模式共用）。

        角度加 δ（与张力守卫/τ 观测同一条 θ_model 链）。R 无效或**该位姿无全正
        零空间**时返回 None。

        2026-11-23 **改为"用真实位姿、不钳制"**：
          以前把角度钳进 `clamp_force_closure` 的可行域再算模型（为了不报
          "无可行预紧区间"）。但钳制等于**拿另一个姿态的 R/n̂ 去算真实机器**，
          现场后果是"某根绳被单独收到 f_max 还在收"（roll 实测 −18.2° 被钳到
          −15°，模型力矩与实际几何不对应）。
          现在如实返回：位姿真在可行域外就返回 None，调用方明确报"该位姿力封闭
          失败"，让操作者把腕摆回来 —— 而不是拿错模型继续控。
        """
        dr, dp = (self.wrist_calib.zero_offset_deg
                  if self.wrist_calib is not None else (0.0, 0.0))
        # UI/硬件角 → 模型角（2026-11-19，同位置环）：roll 方向与模型相反。
        rm = MODEL_AXIS_SIGN[0] * roll
        rr = math.radians(rm + dr)
        pr = math.radians(pitch_model_deg(pitch) + dp)
        self._pose_clamp_delta = (0.0, 0.0)
        key = (round(math.degrees(rr), 1), round(math.degrees(pr), 1))
        now = time.monotonic()
        cached = getattr(self, "_force_geo_cache", None)
        if (cached is not None and cached[0] == key
                and now - cached[2] < 1.0):
            return cached[1]
        out = wrist_eval(rr, pr)
        if not out.math_valid:
            return None
        pair = (out, positive_null_direction(rr, pr, out_model=out))
        self._force_geo_cache = (key, pair, now)
        return pair

    def _warn_pose_clamped(self, r_raw, p_raw, r_clip, p_clip) -> None:
        """位姿越出力封闭可行域时的 1 s 节流提示（只提示，不改控制目标）。"""
        now = time.monotonic()
        if now - getattr(self, "_pose_clamp_last", 0.0) < 1.0:
            return
        self._pose_clamp_last = now
        self._ctrl_status(
            f"⚠ 位姿越出力封闭域：模型按最近可行姿态计算"
            f"（roll {math.degrees(r_raw):+.1f}→{math.degrees(r_clip):+.1f}°, "
            f"pitch {math.degrees(p_raw):+.1f}→{math.degrees(p_clip):+.1f}°）",
            log=False)
        self._safety("FORCE_POSE_CLAMPED",
                     roll_raw=round(math.degrees(r_raw), 2),
                     pitch_raw=round(math.degrees(p_raw), 2),
                     roll_clip=round(math.degrees(r_clip), 2),
                     pitch_clip=round(math.degrees(p_clip), 2))

    def _force_fmax(self) -> float:
        """f_max 唯一来源=有效阈值（_effective_flimits）。"""
        fmin, fmax, _ok = self._effective_flimits()
        return fmax

    def _effective_flimits(self):
        """有效 f 界（PLAN v8.2 D5 / v8.3）：显示/TDA/守卫三路单源。

        fmin_eff = max(边界行 fmin, 守卫框 fmin, 0)——负值一律视 0（禁用
        下界；布局存档 −5000 的用户意图即禁用）；守卫框空=不贡献。
        fmax_eff = min(边界行 fmax_f 默认 30, 守卫框 fmax 或 +∞)。
        返回 (fmin_eff, fmax_eff, valid)；fmax≤fmin → invalid（力控拒启/
        徽章"阈值非法"）。守卫框接入后：位置模式在守卫框留空时也有过载
        停环（边界行兜底）。"""
        bmin = self._cl_fval("f_min", 0.0, 0.0, 200.0)
        bmax = self._cl_fval("fmax_f", 30.0, 1.0, 200.0)
        gmin = 0.0
        gmax = math.inf
        ge = getattr(self, "tension_fmin_edit", None)
        xe = getattr(self, "tension_fmax_edit", None)

        def _guard_txt(widget, key: str) -> str:
            """守卫框文本：窗口开着读控件，关掉后回落到持久镜像。

            2026-11-03 BUG：关掉观测台后控件引用被置空，守卫框阈值整段失效——
            fmax 从用户设的 8N 一路回到边界行默认 30N，过载保护被悄悄放宽
            （一键紧绳/力控/位置模式守卫共用这条单源）。镜像
            _tension_guard_saved 由 textChanged 实时写入、随布局落盘，正好补上。
            """
            if widget is not None and self._in_gui_thread():
                txt = widget.text().strip()
                if txt:
                    return txt
            return (self._tension_guard_saved.get(key) or "").strip()

        try:
            gmin_txt = _guard_txt(ge, "f_min")
            if gmin_txt:
                gmin = max(0.0, float(gmin_txt))
        except ValueError:
            pass
        try:
            gmax_txt = _guard_txt(xe, "f_max")
            if gmax_txt:
                gmax = float(gmax_txt)
        except ValueError:
            pass
        fmin_eff = max(bmin, gmin, 0.0)
        fmax_eff = min(bmax, gmax)
        return fmin_eff, fmax_eff, fmax_eff > fmin_eff

    def _t_bound_note(self) -> str:
        """张紧 t 越界预警（t_min/t_max 留空=0 不启用；只提示不停环——
        硬安全由逐缆 fmax 过载停环负责）。n̂ 缺失/无数据时返回空。"""
        t_min = self._cl_fval("t_min", 0.0, 0.0, 200.0)
        t_max = self._cl_fval("t_max", 0.0, 0.0, 200.0)
        if t_min <= 0.0 and t_max <= 0.0:
            return ""
        last = self._tension_last
        pose = self._wrist_pose_now()
        if last is None or pose is None:
            return ""
        geo = self._force_geo(pose[0], pose[1])
        if geo is None or geo[1] is None:
            return ""
        t = sum(last[1][i] * geo[1][i] for i in range(3))
        if t_max > 0.0 and t > t_max:
            return f"⚠预紧超限 t={t:.1f}>{t_max:g}N"
        if t_min > 0.0 and t < t_min:
            return f"⚠预紧丢失 t={t:.2f}<{t_min:g}N"
        return ""

    def _cl_text(self, key: str, default: str = "") -> str:
        """读参数框文本（跨线程安全）：工作线程读 GUI 快照，GUI 线程读控件。"""
        snap = getattr(self, "_cl_snap", None)
        if snap is not None and not self._in_gui_thread():
            v = snap.get(key)
            if v is not None:
                return v
        w = self.cl_edits.get(key)
        return w.text() if w is not None else default

    def _force_trim_sign(self):
        """trim方向框 → [3]±1 | None（非法 None=参数拒绝启动）。"""
        try:
            sign_txt = self._cl_text("trim_sign").strip().replace("，", ",")
            return [int(s.strip()) for s in sign_txt.split(",") if s.strip()]
        except (ValueError, AttributeError):
            return None

    def _sign_invariant_note(self) -> str:
        """k 与 trim方向 的符号自检（纯读，不拦截）。返回提示文本，空串=一致或无法判断。

        不变量（逐路）：sign(trim_sign_i) = −sign(k_i)。
            位置环靠 k 定方向（J = −k·R）；三个力控模式与一键松绳靠 trim_sign 定方向。
        两条路径对"counts 增大是收/放"必须给出**相反**的符号——同号说明其中一处写反了
        （位置环正反馈，或力控/松绳反着走）。k 的符号是**逐路**的（电机可能反向安装），
        所以这里逐路判并指出哪几路不符；台架用 +100c 逐缆点动一次即可定论。
        """
        calib = self.wrist_calib
        if calib is None:
            return ""
        k = calib.k_counts_per_m
        if any(not math.isfinite(v) or v == 0.0 for v in k):
            return ""
        ksign = [1 if v > 0 else -1 for v in k]
        ts = self._force_trim_sign()
        if not ts or len(ts) != 3 or any(v not in (-1, 1) for v in ts):
            return "trim方向 未填/非法：力控与一键松绳没有方向基准"
        bad = [i for i in range(3) if ts[i] != -ksign[i]]
        if not bad:
            return ""
        names = " ".join(f"C{i + 1}(M{27 + i})" for i in bad)
        want = ",".join(str(-ksign[i]) for i in range(3))
        if len(bad) == 3:
            return (f"k 与 trim方向 三路同号（应相反）：位置环与力控/松绳的方向必有一处反了，"
                    f"按当前 k 应填 trim方向 = {want}；先点动 +100c 核对再上闭环")
        return (f"trim方向 的 {names} 与 k 的反号关系不符（其余路一致）："
                f"按当前 k 应填 trim方向 = {want}；换线/反向安装后需逐缆点动复核")

    def _capacity_note(self, r_m, nd, t_floor, f_min, f_max) -> str:
        """四个"顶点方向"的能力 [N·m]（闭式 4×9 次比较，O(1)）。

        2026-11-23 起不再做"按轴钳制"（那是矩形近似，双轴会高估）；
        这里只用来**显示**"这台机器现在最多能出多少"：
        `cap(r±a/b p±c/d)`（本机 (0,0) 位姿约 `r±0.43/0.55 p±0.50/1.44`）。
        """
        caps = []
        for d in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
            m = capacity_closed_form(r_m, nd, d[0], d[1],
                                     t_floor, f_min, f_max)
            caps.append(m if m is not None and math.isfinite(m) else 0.0)
        return (f"cap(r±{caps[0]:.2f}/{caps[1]:.2f} p±{caps[2]:.2f}/{caps[3]:.2f})N·m")

    def _force_params_v2(self, roll, pitch):
        """读力控 UI + 动态 R(q) → WristForceV2Params | None（力矩模式）。"""
        geo = self._force_geo(roll, pitch)
        if geo is None:
            return None
        out, nd = geo
        r_max = self._cl_fval("tau_r_max", 0.0, 0.0, 100.0)
        p_max = self._cl_fval("tau_p_max", 0.0, 0.0, 100.0)
        imp = getattr(self, "_imp_tau", None)
        if self._cl_mode == "impedance" and imp is not None:
            # 2026-11-22：阻抗模式 → τ 由外环算（K·e + D·ė + τ_ff），不读 τ 输入框
            tau_r, tau_p = imp
        else:
            tau_r = self._cl_fval("tau_roll", 0.0, -100.0, 100.0)
            tau_p = self._cl_fval("tau_pitch", 0.0, -100.0, 100.0)
        if r_max > 0.0:
            tau_r = max(-r_max, min(r_max, tau_r))
        if p_max > 0.0:
            tau_p = max(-p_max, min(p_max, tau_p))
        # 2026-11-23：**不再在这里钳 τ**。「能不能做」由分配层的 α（沿方向、
        # 闭式）决定：做不到就按 α 缩，并显示"τ* → ατ* → 实测"。
        # 旧的 `_clamp_tau_to_capacity` 按轴独立二分，双轴组合会高估能力
        # （实测 (0.1,-2.0)：pitch 单轴 1.443，叠加 0.1 roll 后真实只有 1.380），
        # 砍完仍不可行 → 误判停环。函数保留但不再参与分配路径。
        try:
            mt = self._cl_fval("max_trim", 3000.0, 1.0, 50000.0)
            return WristForceV2Params(
                tau_d=(tau_r, tau_p),
                preload_n=self._cl_fval("preload", 5.0, 0.0, 100.0),
                # 2026-11-18：力矩 **P** 外环已移除；2026-11-24 加了"慢积分修正"
                # （见 `tau_trim_step` 与 `tau_ki` 框）。kp/ki 仍是历史占位字段，
                # law 里不读；真正在用的是内环 kp_inner/ki_inner 与 τ修正 tau_ki。
                kp=0.0,
                ki=0.0,
                trim_sign=self._force_trim_sign(),
                # 内环 P/I 分离（2026-11-17）：与张力环共用同一组增益，
                # 旧的 trim_gain=50 是 P=I 单旋钮，S·50=2.32 越界（实测 50Hz 极限环）。
                kp_inner=self._cl_fval("kp_f", 15.0, 0.0, 10000.0),
                ki_inner=self._cl_fval("ki_f", 20.0, 0.0, 10000.0),
                max_trim=mt,
                f_max=self._force_fmax(),
                f_min=self._effective_flimits()[0],
                deadband=0.01,
                r_m=out.r_m, null_dir=nd,
                max_step=self._cl_fval("max_step_f", 20.0, 0.1, 2000.0),
                # 2026-11-20：以前力矩模式**漏接**积分钳制（law 里传的是
                # max_trim＝不限），这里补上，与张力/张紧同一个口径。
                i_term_lim=self._tension_i_term_lim(mt),
                # 2026-11-24：逐缆覆盖（与张力模式同一个"1 个或 3 个"口径）
                kp3=self._cl_fval3("kp_f", 15.0, 0.0, 10000.0),
                ki3=self._cl_fval3("ki_f", 20.0, 0.0, 10000.0),
                max_step3=self._cl_fval3("max_step_f", 20.0, 0.1, 2000.0),
                i_term_lim3=self._cl_fval3(
                    "i_term_lim", float(self._tension_i_term_lim(mt)), 0.0, 1e6),
                # 速度阻尼（2026-11-24）：与张力模式共用同一个 Kd_f 框
                # 2026-11-25：`kd_f` = **误差微分 D**（标准 PID）
                kd=self._cl_fval("kd_f", 0.0, 0.0, 5.0),
                kd3=self._cl_fval3("kd_f", 0.0, 0.0, 5.0))
        except (ValueError, KeyError):
            return None

    def _clamp_per_tick(self, outs: dict[int, int]) -> dict[int, int]:
        """闭环**每拍限幅**：与力控三模式共用同一个 `max_step_f`。

        力控模式每拍增量由 `_incr_step(..., max_step)` 限幅；位置模式的输出是
        绝对目标，所以这里换算成"每拍变化 ≤ max_step_f"，两种模式对舵机的
        实际限制才一致。
        """
        if not outs or not self._safety_on():
            return outs
        slew = int(self._cl_fval("max_step_f", 20.0, 0.1, 2000.0))
        limited = {}
        for m, out in outs.items():
            prev = self.targets.get(m)
            limited[m] = out if prev is None else max(prev - slew, min(prev + slew, int(out)))
        return {m: v for m, v in limited.items() if v != self.targets.get(m)}

    def _tension_i_term_lim(self, max_trim: float) -> float:
        """积分累积上限 [counts]，三个力控模式共用，**界面上可调**。

        2026-11-20 用户定案：积分允许一直累积（不再靠"饱和闸门"冻结），
        只用一个累积上限封顶；该上限放到界面「积分上限」框，可随时改。
          · 贡献上限 = 本值（counts）
          · 状态上限 = 本值 / Ki（N·s）—— 由 `_incr_step` 自动换算
          · 填 0 = 关闭积分（`lim_state=0` ⟹ 状态恒 0 ⟹ 纯 P）
        `max_trim` 参数保留只为兼容旧调用点，不再参与回退。
        """
        return self._cl_fval("i_term_lim", 5.0, 0.0, 2000.0)

    def _tension_params(self):
        """读力控 UI → WristTensionParams | None（张力模式，每缆独立）。

        2026-11-24：`kp_f / ki_f / i_term_lim / max_step_f` 支持**逐缆填写**
        （"15" 或 "15,15,8"，逗号分隔按 C1,C2,C3）。三根缆的摩擦/绳长不同，
        一套增益不可能同时最优；填错格式直接返回 None（拒绝开环）。
        """
        try:
            mt = self._cl_fval("max_trim", 3000.0, 1.0, 50000.0)
            kp3 = self._cl_fval3("kp_f", 15.0, 0.0, 10000.0)
            ki3 = self._cl_fval3("ki_f", 20.0, 0.0, 10000.0)
            ms3 = self._cl_fval3("max_step_f", 20.0, 0.1, 2000.0)
            itl3 = self._cl_fval3(
                "i_term_lim", float(self._tension_i_term_lim(mt)), 0.0, 1e6)
            kd3 = self._cl_fval3("kd_f", 0.0, 0.0, 5.0)
            if (kp3 is None or ki3 is None or ms3 is None or itl3 is None
                    or kd3 is None):
                return None
            return WristTensionParams(
                f_target=(self._cl_fval("f1_tgt", 2.0, 0.0, 50.0),
                          self._cl_fval("f2_tgt", 2.0, 0.0, 50.0),
                          self._cl_fval("f3_tgt", 2.0, 0.0, 50.0)),
                kp=kp3[0], ki=ki3[0], max_step=ms3[0], i_term_lim=itl3[0],
                trim_sign=self._force_trim_sign(),
                max_trim=mt,
                f_max=self._force_fmax(),
                deadband=0.05,
                kp3=kp3, ki3=ki3, max_step3=ms3, i_term_lim3=itl3,
                kd=kd3[0], kd3=kd3)
        except (ValueError, KeyError):
            return None

    def _tight_params(self, roll, pitch, quiet=False):
        """读力控 UI + 当前位姿 n̂ → WristTightParams | None（张紧模式）。

        入口可行域（PLAN v8.2 D4）：t_tgt 必须满足
            t_min_req = fmin_eff/min(n̂) ≤ t_tgt ≤ t_max_allow = fmax_eff/max(n̂)
        ——低于下界=标准分布 t·n̂ 有缆达不到 fmin（地板不负责抬缆，v8.3）；
        高于上界=有缆会超 fmax。n̂ 缺失/非全正直接拒绝。
        t_max>0 时目标仍被钳到 t_max；tmin/tmax 都设且 tmax<=tmin 拒绝。
        quiet=True 供门禁/弹窗复查路径：只判定不写状态行（REVIEW Important#2：
        复查 1Hz 改写状态行会把急停消息顶掉）。"""
        geo = self._force_geo(roll, pitch)
        if geo is None:
            return None
        _, nd = geo
        if nd is None or any(v <= 0.0 for v in nd):
            return None
        fmin_eff, fmax_eff, ok = self._effective_flimits()
        if not ok:
            return None
        # 2026-11-18 A2：可行域改为**带 τ 项的通用式**（wrist_tda.preload_window）。
        # 现在是纯预紧（τ=0），结果与旧式 `fmin/min(n̂) … fmax/max(n̂)` 完全一致；
        # 以后接重力补偿（τ=τ_g0）时，这里**不用再改**。
        # 复用同一个 _force_geo 的模型结果：geo = (WristModelOut, n̂)
        out = geo[0]
        r_m = out.r_m if hasattr(out, "r_m") else out
        win = preload_window(r_m, nd, 0.0, 0.0, fmin_eff, fmax_eff)
        if win is None:
            if not quiet:
                self._ctrl_status("张紧：该位姿/该张力阈值下无可行预紧区间", log=False)
            return None
        t_min_req, t_max_allow = win
        t_min = self._cl_fval("t_min", 0.0, 0.0, 200.0)
        t_max = self._cl_fval("t_max", 0.0, 0.0, 200.0)
        if t_min > 0.0 and t_max > 0.0 and t_max <= t_min:
            return None
        # 2026-11-18 合并：张紧的 t* 与力矩的 preload 是同一个物理量（n̂·f），
        # 统一读「预紧N」这一个框；张紧侧的 t_tgt 只做只读镜像显示。
        t_tgt = self._cl_fval("preload", 5.0, 0.0, 200.0)
        if t_max > 0.0:
            t_tgt = min(t_tgt, t_max)
        if t_tgt < t_min_req:
            if not quiet:
                self._ctrl_status(
                    f"张紧：t={t_tgt:g}N 低于可行下界 {t_min_req:.2f}N"
                    "（三缆都要 ≥ fmin，最小那根不够）", log=False)
            return None
        if t_tgt > t_max_allow:
            if not quiet:
                self._ctrl_status(
                    f"张紧：t={t_tgt:g}N 超出可行上界 {t_max_allow:.2f}N"
                    "（三缆都要 ≤ fmax，最大那根会超）", log=False)
            return None
        try:
            mt = self._cl_fval("max_trim", 3000.0, 1.0, 50000.0)
            return WristTightParams(
                t_target=t_tgt,
                # 2026-11-18：内环增益与张力/力矩统一（同一根绳、同一个执行器、
                # 同一个 S ⇒ 稳定判据相同）。Kp_t/Ki_t 已弃用，只读占位。
                kp=self._cl_fval("kp_f", 15.0, 0.0, 10000.0),
                ki=self._cl_fval("ki_f", 20.0, 0.0, 10000.0),
                trim_sign=self._force_trim_sign(),
                max_trim=mt,
                f_max=fmax_eff,
                deadband=0.05,
                null_dir=nd,
                max_step=self._cl_fval("max_step_f", 20.0, 0.1, 2000.0),
                f_min=fmin_eff,
                i_term_lim=self._tension_i_term_lim(mt))
        except (ValueError, KeyError):
            return None

    def _tau_ff(self, roll: float, pitch: float):
        """重力前馈 τ_ff [N·m]（2026-11-23 恢复可测：读界面 `τff@90°` 两个框）。

        τ_g,roll  = A_r·sin(roll)
        τ_g,pitch = A_p·sin(pitch)·cos(roll)
        τ_ff      = −τ_g

        `A` = 90° 处的重力力矩幅值；两框填 0（默认）= 不补偿，行为与之前完全一致。
        """
        return gravity_tau_sine(
            self._cl_fval("tau_ff_r", 0.0, -10.0, 10.0),
            self._cl_fval("tau_ff_p", 0.0, -10.0, 10.0),
            roll, pitch)

    def _imp_deadband(self) -> float:
        """阻抗模式的角度死区 [deg]。

        2026-11-26：优先用阻抗行自己的 `imp_deadband`；**留空则沿用位置模式的
        `deadband`**（旧行为，逐位不变）。这样阻抗的死区不再被"藏在位置模式里"。
        """
        base = self._cl_fval("deadband", 0.3, 0.0, 10.0)
        return self._cl_fval("imp_deadband", base, 0.0, 10.0)

    def _impedance_params(self, roll: float = 0.0, pitch: float = 0.0):
        """读阻抗行 → WristImpedanceParams | None（2026-11-22 框架）。

        `τ_ff` 目前恒为 0（2026-11-23 按用户要求注释掉了重力前馈，
        见 `_tau_ff`）。钳制用「τ 上限」两框（与力矩模式共用）。
        """
        try:
            tau_ff = self._tau_ff(roll, pitch)
            return WristImpedanceParams(
                k_roll=self._cl_fval("k_roll", 0.5, 0.0, 100.0),
                k_pitch=self._cl_fval("k_pitch", 0.5, 0.0, 100.0),
                d_roll=self._cl_fval("d_roll", 0.0, 0.0, 100.0),
                d_pitch=self._cl_fval("d_pitch", 0.0, 0.0, 100.0),
                tau_ff=tau_ff,
                tau_r_max=self._cl_fval("tau_r_max", 0.0, 0.0, 100.0),
                tau_p_max=self._cl_fval("tau_p_max", 0.0, 0.0, 100.0),
                deadband_deg=self._imp_deadband(),
            )
        except (ValueError, KeyError):
            return None

    def _cl_tick_impedance(self, roll: float, pitch: float) -> None:
        """100Hz 阻抗外环：q*−q → τ* → 复用②（分配+张力内环）。

        外环只做"位置→力矩"，其余全部沿用 `_cl_tick_force`：
        能力钳制 → `allocate_torque_priority` → 三缆张力 PI → trim。
        所以这里先把 τ* 存到 `self._imp_tau`，再由 `_force_params_v2` 取用。
        """
        ip = self._impedance_params(roll, pitch)
        if ip is None:
            self._stop_closed_loop("阻抗控制：参数非法")
            return
        roll_tgt = self._cl_fval("roll_tgt", 0.0, -90.0, 90.0)
        pitch_tgt = self._cl_fval("pitch_tgt", 0.0, -90.0, 90.0)
        # 2026-11-25：**D 项原料** —— 编码器只给角度，这里差分出一阶低通后的
        # 角速度（`RateFilter`）。`wrist_impedance_torque` 的入参约定是
        # `q̇* − q̇`，目标速率恒 0 ⇒ 传 `−ω`；于是 D 项出来是"反抗运动"，
        # 且**目标角阶跃不会产生微分 kick**（D 作用在测量上）。
        w_roll, w_pitch = self._imp_rate.update(roll, pitch, time.perf_counter())
        d_roll, d_pitch = -w_roll, -w_pitch
        self._imp_omega = (w_roll, w_pitch)
        # D 项这一拍实际贡献的力矩（deadband 对 D 无影响），供状态行拆分显示
        _d2r = math.pi / 180.0
        self._imp_d_tau = (ip.d_roll * d_roll * _d2r,
                           ip.d_pitch * d_pitch * _d2r)
        tau_r, tau_p, fl = wrist_impedance_torque(
            ip, roll, pitch, roll_tgt, pitch_tgt, d_roll, d_pitch)
        if fl & IMP_NO_TARGET:
            self._stop_closed_loop("阻抗控制：位置/目标含非有限值")
            return
        # 2026-11-23：阻抗外环的 roll 输出取反（台架实测方向反）。
        # 弹簧项 K·e、阻尼项 D·ė、前馈 τ_ff_r 一起翻——整条 roll 轴一个符号。
        # 后续 TDA 还会做一次 `τ_model = s_r·τ_ui`（s_r=−1），叠加后本项不再翻转，
        # 等价于"阻抗外环按模型系输出"。pitch 保持 UI 口径，不动。
        tau_r = IMPEDANCE_ROLL_SIGN * tau_r
        self._imp_tau = (tau_r, tau_p)
        self._imp_flags = fl
        # τ_ff 目前只存不用；跟着同一个符号存，避免以后显示时和 τ* 对不上。
        self._imp_ff = (IMPEDANCE_ROLL_SIGN * ip.tau_ff[0], ip.tau_ff[1])
        self._cl_tick_force(roll, pitch)

    def _cl_tick_force(self, roll: float, pitch: float) -> None:
        """100Hz 力控一拍：**τ 目标 → TDA 分配 f_d → 逐缆张力 PI → 位置增量**。

        闭环结构（2026-11-24 定稿，⚠ 旧版此处写"没有力矩闭环"已不成立）：
          · **主闭环**：每根缆的张力 f（逐缆增量 PI，100 Hz）—— 唯一靠反馈的量
          · **慢积分修正**：`τ_cmd = τ* + ∫(τ* − R·f)·ki_τ`（`τ修正` 框，默认
            1.0 /s，修正量上限 `TAU_TRIM_MAX`）。**只积分、不带 P**：τ 误差本身
            就是内环的响应（10~30 ms），外环带 P 会和内环打架——2026-11-18
            实测 `Kp=20` 时 51% 的拍 α<1、摆动 0.075 N·m。填 0 = 回到纯前馈。
          · 该积分**只补"内环到不了 f_d"的稳态差**（积分权限/`max_trim` 打满/
            摩擦迟滞）。它补不了 R 模型误差，也补不了导管摩擦造成的
            "关节侧张力 ≠ 传感器侧张力"——因为 `τ_meas` 用的是同一个 R 和
            电机侧 f 反算（见 `wrist_force_law.tau_trim_step` 与
            docs/系统数学推导_20261123.md）。
          · 由 `R·P⁻¹ = [I₂ 0]`：只要 `f → f_d`，`τ → ατ*` 自动成立。

        不是论文 §7 的 `P⁻ᵀ` 关节空间解耦律；`R·Rᵀ` 的动态耦合仍在
        （本机相关系数仅 3.2%，见 docs/系统数学推导_20261123.md §3）。
        """
        p = self._force_params_v2(roll, pitch)
        if p is None:
            # `_force_geo` 现在用真实位姿（不钳制）：返回 None 就是**该位姿真的
            # 没有全正零空间**，拿不到 n̂ 就无法做 2 轴力矩分配。
            self._stop_closed_loop(
                f"力控：该位姿力封闭失败（无全正零空间） roll={roll:+.1f}° "
                f"pitch={pitch:+.1f}° → 把腕摆回可行域 "
                f"roll {FORCE_CLOSURE_ENVELOPE_ROLL_DEG[0]:g}…"
                f"{FORCE_CLOSURE_ENVELOPE_ROLL_DEG[1]:g}°、"
                f"pitch {FORCE_CLOSURE_ENVELOPE_PITCH_DEG[0]:g}…"
                f"{FORCE_CLOSURE_ENVELOPE_PITCH_DEG[1]:g}°")
            return
        if abs(roll) > 30.0 or pitch < -30.0 or pitch > 50.0:
            self._stop_closed_loop(
                f"力控：关节越界 ROLL{roll:+.1f}° PITCH{pitch:+.1f}°")
            return
        # 力封闭**病态**判定（2026-11-23）：某根缆的零空间份额趋近 0 时，它几乎
        # 无法承载预紧 → 分配无解，或者它"永远收不满"（现场:一直收绳）。
        # 放在分配**之前**：否则先被分配层的"预紧下限冲突"挡住，报错会指错方向。
        nmin = min(p.null_dir) if p.null_dir else 1.0
        if nmin < FORCE_NULL_MIN_SHARE:
            i = list(p.null_dir).index(nmin)
            self._stop_closed_loop(
                f"力控：该位姿力封闭病态 —— C{i+1} 的零空间份额仅 {nmin:.3f}"
                f"（阈值 {FORCE_NULL_MIN_SHARE:g}）⟹ 这根缆几乎无法承担预紧，"
                f"分配必然无解或被它拖成一直收绳。\n"
                f"当前位姿 roll={roll:+.1f}° pitch={pitch:+.1f}°；"
                f"请把腕摆离力封闭边界（建议 |roll| ≤ 12°、pitch −20…+25°）再试。")
            return
        last = self._tension_last
        if last is None:
            self._stop_closed_loop("力控：张力数据丢失")
            return
        age_ms = (time.monotonic() - last[0]) * 1000.0
        # 2026-11-23：**α 内生**（沿方向的闭式能力）—— 替代旧的"外部按轴二分钳 τ"。
        # 旧做法把 3 缆 2 轴的能力当矩形（每轴独立测），双轴组合会高估 → 砍完仍
        # 不可行 → 误判停环（实测 (0.1,-2.0)）。现在一次算出 α，永远给可行解。
        acap = self._cl_fval("alpha_cap", 1.0, 0.05, 1.0)
        alloc = {}
        # ---- 力矩修正（慢积分外环，2026-11-24）：把"τ* − 实测τ"的**稳态部分**
        # 用积分补到 τ 命令里。只积分不带 P（见 wrist_force_law.tau_trim_step 说明：
        # τ 误差本身就是内环的响应，加 P 会和内环打架 → 旧实现 Kp_τ=20 就是这样振的）。
        tau_meas0 = self._tau_meas(roll, pitch, last[1])
        tki = self._cl_fval("tau_ki", 0.0, 0.0, 20.0)
        if not hasattr(self, "_tau_trim"):
            self._tau_trim = [0.0, 0.0]
        if tau_meas0 is not None and tki > 0.0:
            # 能力受限（α<1）时冻结：差距是物理上限，再积分只会把目标推得更不可行
            _freeze = getattr(self, "_alpha_limited", False)
            for _i in range(2):
                self._tau_trim[_i], _ = tau_trim_step(
                    p.tau_d[_i] - tau_meas0[_i], self._tau_trim[_i],
                    tki, self._cl_dt, TAU_TRIM_MAX, freeze=_freeze)
            self._tau_trim_on = True
        else:
            self._tau_trim_on = False
            if tki <= 0.0:
                self._tau_trim = [0.0, 0.0]
        tau_cmd = (p.tau_d[0] + self._tau_trim[0],
                   p.tau_d[1] + self._tau_trim[1])

        def _solve(r_m, nd, tr, tp, tfl, fmin, fmax):
            # **2026-11-23：roll 力矩换到模型系**（`τ_model = s·τ_ui`）。
            # s 由 `_roll_tau_sign()` 给出 = `MODEL_AXIS_SIGN[0]`（模型约定）
            # × 界面「τ方向」开关（±1）—— 实机方向与模型不一致时不用改代码，
            # 在该框填 −1 即可（会同时翻转下发与显示的实测 τ，两者永远同号）。
            tr_model = self._roll_tau_sign() * tau_cmd[0]
            tp_model = tau_cmd[1]
            # 给 f_max 留超调余量（见 FORCE_FMAX_HEADROOM_N 注释）
            headroom = min(FORCE_FMAX_HEADROOM_N, 0.1 * fmax)
            fmax_alloc = max(fmin + 0.1, fmax - headroom)
            f_d, fl, al, info = allocation_step(
                r_m, nd, tr_model, tp_model, tfl, fmin, fmax_alloc, alpha_cap=acap)
            alloc.update(info)
            # 2026-11-24：留存本拍目标张力，供 `tension_f*_tgt` 曲线
            if f_d is not None:
                self._f_d_last = list(f_d)
            return f_d, fl, al

        trim, flags, alpha = wrist_force_v2_step(p, self._force_state, last[1],
                                                 age_ms, self._cl_dt, _solve)
        self._alloc_info = alloc
        # 供下一拍的力矩修正判断是否"能力受限"（受限时冻结积分，防 windup）
        self._alpha_limited = alpha < 0.99
        if flags & FORCE_OVERLOAD:
            # 过载停环统一交给 `_tension_guard`（同一份 f/fmax，且已做去抖）。
            # 这里只"本拍不发目标"，等守卫连续超限再停。
            return
        if flags & FORCE_SENSOR_FAULT:
            # 2026-11-23：负到物理不可能 = 传感器/通道故障。绝不能再"钳 0 继续控"。
            self._stop_closed_loop(
                "力控：张力读数异常（物理不可能） ["
                + "/".join(f"{v:.1f}" for v in last[1])
                + f"] N，阈值 {F_SENSOR_MIN_N:g} N → 检查传感器接线/通道/零点")
            return
        if getattr(self, "_pose_clamp_delta", (0.0, 0.0)) and max(self._pose_clamp_delta) > POSE_CLAMP_STOP_DEG:
            dr, dp = self._pose_clamp_delta
            self._stop_closed_loop(
                f"力控：位姿超出力封闭可行域 {max(dr, dp):.1f}°（>{POSE_CLAMP_STOP_DEG:g}°）"
                f"→ 模型 R/n̂ 已与实际几何不符，继续跑会把某根绳收到过载；"
                f"先把腕摆回可行域（roll −15…+10°, pitch −25…+30°）")
            return
        if flags & FORCE_TDA_INFEASIBLE:
            # 2026-11-23：**按实际 flag 说清楚**。以前一律报"预紧下限冲突"，
            # 现场 45 次停环全被指错方向（真正原因是力矩在该位姿/该界限下无解）。
            if flags & TDA_PRELOAD_INFEASIBLE:
                self._stop_closed_loop(
                    f"力控：该位姿下预紧无解 —— 预紧下限 {p.preload_n:g} N 与界限 "
                    f"[{p.f_min:g},{p.f_max:g}] 及当前 n̂ 冲突（t·n̂ 落在界外）"
                    f"→ 调小「预紧N」、调大「fmax」，或把腕摆离力封闭边界")
            elif flags & TDA_INFEASIBLE:
                self._stop_closed_loop(
                    f"力控：该力矩在本位姿/本界限下不可实现"
                    f"（τ*=[{p.tau_d[0]:+.3f},{p.tau_d[1]:+.3f}] N·m，"
                    f"f∈[{p.f_min:g},{p.f_max:g}]，min n̂={min(p.null_dir):.3f}）"
                    f"→ 减小目标力矩 / 调大 fmax / 摆离边界")
            elif flags & TDA_NO_NULL:
                self._stop_closed_loop(
                    "力控：该位姿无全正零空间（力封闭失败）→ 把腕摆回可行域")
            else:
                self._stop_closed_loop(
                    f"力控：分配失败（flags={flags}）"
                    f"→ τ*=[{p.tau_d[0]:+.3f},{p.tau_d[1]:+.3f}] N·m")
            return
        if alpha < 0.5:
            # 2026-11-23 用户定案：**不拒绝启动** —— 目标超能力就"给到可行最大"。
            # 这里只做**限频告警**（1 s 一次），把"你填多少、实际只有多少"说清楚；
            # 真正的安全由 `f > f_max` 过载停环负责。
            now = time.monotonic()
            if now - getattr(self, "_alpha_warn_last", 0.0) > 1.0:
                self._alpha_warn_last = now
                self._ctrl_status(
                    f"⚠ 目标超能力：填 |τ|={math.hypot(p.tau_d[0], p.tau_d[1]):.3f} N·m，"
                    f"本方向能力 {self._alloc_info.get('m_max', float('nan')):.3f} N·m"
                    f" → 已按能力上限运行（α={alpha:.3f}）", log=False)
                self._safety("TORQUE_ALPHA_DERATED",
                             alpha=round(alpha, 4),
                             m_max=round(self._alloc_info.get("m_max", 0.0), 4))
        if trim is None:
            self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
            if self._cl_tick_count % 6 == 0:
                self._cl_status_set("力控：张力数据过期 → 冻结（电机保持）")
            return
        # 力控曲线通道：α + τ 目标（曲线由样本入口统一推实测 τ）
        now_rel = self._latest_t if self._latest_t is not None else 0.0
        self.channels["force_alpha"].buf.append(now_rel, alpha)
        tau = self._tau_meas(roll, pitch, last[1])   # 与张力/张紧模式同一入口（含几何缓存）
        tau_r = tau[0] if tau else 0.0
        tau_p = tau[1] if tau else 0.0
        self.channels["force_tau_roll_tgt"].buf.append(now_rel, p.tau_d[0])
        self.channels["force_tau_pitch_tgt"].buf.append(now_rel, p.tau_d[1])
        # 2026-11-24：三缆目标张力（f_d，分配结果）推曲线，与实测 `tension_f*` 对比
        self._push_tension_tgt_curves(getattr(self, "_f_d_last", None))
        self._apply_force_step(trim, p.max_trim)
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        self._record_diag(3, roll, pitch, last[1], tau, p)
        if self._cl_tick_count % 6 == 0:
            fvals = last[1]
            tb = self._t_bound_note()
            info = getattr(self, "_alloc_info", {}) or {}
            t_used = float(info.get("t", p.preload_n))
            t_raised = t_used > p.preload_n + 1e-6
            m_max = info.get("m_max", float("nan"))
            # α 乘的是**含修正的命令** tau_cmd（tau* + trim），不是原始 tau*
            _tc = (p.tau_d[0] + self._tau_trim[0], p.tau_d[1] + self._tau_trim[1])
            tau_tgt = [alpha * _tc[0], alpha * _tc[1]]
            trim_txt = ""
            if (hasattr(self, "_tau_trim_on") and self._tau_trim_on
                    and (abs(self._tau_trim[0]) > 1e-4 or abs(self._tau_trim[1]) > 1e-4)):
                trim_txt = f"  τ修=[{self._tau_trim[0]:+.3f},{self._tau_trim[1]:+.3f}]"
            cap_txt = ""
            if self._cl_tick_count % 30 == 0:      # 每 0.3 s 刷一次能力显示
                cap_txt = "  " + self._capacity_note(
                    p.r_m, p.null_dir, p.preload_n, p.f_min, p.f_max)
            # 阻抗模式（2026-11-25）：额外显示 D 项的两样东西 ——
            #   ω   = 这一拍的角速度（D 项的输入，调 D 时看它是否合理）
            #   D·ė = D 项实际贡献了多少力矩（对比 τ* 就知道 D 在不在起作用）
            imp_txt = ""
            head = "力矩控"
            if self._cl_mode == "impedance":
                head = "阻抗控"
                _w = getattr(self, "_imp_omega", (0.0, 0.0))
                _d = getattr(self, "_imp_d_tau", (0.0, 0.0))
                imp_txt = (f"  ω=[{_w[0]:+.1f},{_w[1]:+.1f}]°/s"
                           f"  D·ė=[{_d[0]:+.3f},{_d[1]:+.3f}]N·m")
            self._cl_status_set(
                head + "  τ*=[%+.3f,%+.3f]→ατ*=[%+.3f,%+.3f]→实测[%+.3f,%+.3f]N·m"
                "  α=%.3f  m_max=%.3f  t=%.2fN%s  f=[%s]N  trim=[%s]c%s%s%s%s"
                % (p.tau_d[0], p.tau_d[1], tau_tgt[0], tau_tgt[1],
                   tau_r, tau_p, alpha, m_max, t_used,
                   ("↑" if t_raised else ""),
                   "/".join(f"{v:.2f}" for v in fvals),
                   "/".join(f"{v:+.0f}" for v in self._force_trim),
                   cap_txt, (f"  {tb}" if tb else ""), trim_txt, imp_txt))

    def _roll_tau_sign(self) -> float:
        """**力矩链专用的 roll 换号因子**（±1）—— 界面可翻转，2026-11-23。

        背景：角度链路用 `MODEL_AXIS_SIGN[0]`（roll 换号）是确定的；但"力矩 →
        角度"的方向（即 `R` 的 roll 行符号）在实机上是否与模型一致，**只能靠
        实验定**（给正力矩看腕往哪转）。为了不再靠改代码/重启来试方向，
        这里给一个界面开关：

            τ_model = _roll_tau_sign() · τ_ui
            τ_ui    = _roll_tau_sign() · (R·f)_roll      ← 显示与命令同一个因子

        所以「τ方向」框 = 1（默认，按模型）或 −1（整条力矩链翻一次）。
        改这个框会**同时**翻转"下发的力矩"和"显示的实测 τ"，两者永远同号。
        """
        v = self._cl_fval("roll_tau_sign", 1.0, -1.0, 1.0)
        return MODEL_AXIS_SIGN[0] if v >= 0.0 else -MODEL_AXIS_SIGN[0]

    def _tau_meas(self, roll, pitch, fvals):
        """实测关节力矩 τ=R(q)·f（N·m）——传感器只给张力，真实力矩经 R 换算。

        R 与力控律同一条 θ_model 链（含 δ、0.1° 缓存）；R 无效返回 None。

        **2026-11-23 统一约定**：力矩的"对外口径"是 **UI 角度约定**（与用户填的
        `τ_roll` 框、状态行一致）。R 在**模型系**（`q_model = s_r·q_ui`），
        所以 rollout 分量要乘回 `s_r` 才能和 UI 目标同号比较。
        （位置环一直是这么换算的，力矩链之前漏了 → 表现为"roll 力矩反了"。）
        """
        geo = self._force_geo(roll, pitch)
        if geo is None:
            return None
        out, _ = geo
        s_r = self._roll_tau_sign()
        return (s_r * sum(out.r_m[0][i] * fvals[i] for i in range(3)),
                sum(out.r_m[1][i] * fvals[i] for i in range(3)))

    def _cl_flag(self, key: str, widget) -> bool:
        """跑环标志读取（跨线程安全）：工作线程读快照，GUI 线程读控件。"""
        snap = getattr(self, "_cl_snap", None)
        if snap is not None and not self._in_gui_thread():
            v = snap.get(key)
            if v is not None:
                return bool(v)
        return bool(widget.isChecked())

    def _cl_status_set(self, txt: str) -> None:
        """闭环状态行写文字（跨线程安全）。"""
        # 注意：这里用 `setText, txt` 形式（不是 `setText(txt)`），
        # 避免被后面那次「批量改成 _cl_status_set」的替换命中而递归。
        self._ui_call(self.cl_status.setText, txt)

    # ---------- 线程解耦（2026-11-19）：控制环搬到独立线程 ----------
    # 背景：原来 `_cl_timer`(QTimer) 和所有重绘/表格在同一个 GUI 线程里排队，
    # 实测控制拍周期 22~28 ms（设计 10 ms）→ 只有 36~44 Hz，速度上限打 4.4 折。
    # 现在 `_ClLoopThread` 用 time.sleep 精确调度跑 `_cl_tick()`，
    # 一切 UI 写操作经 `_ui_call` 排队，由 GUI 线程的 `_drain_ui_queue` 执行。
    def _in_gui_thread(self) -> bool:
        return threading.get_ident() == self._gui_thread_id

    def _ui_call(self, fn, *a, **kw) -> None:
        """在 GUI 线程执行 fn；若当前在工作线程则排队。"""
        if self._in_gui_thread():
            fn(*a, **kw)
        else:
            self._ui_queue.append((fn, a, kw))

    def _drain_ui_queue(self) -> None:
        """GUI 侧定时执行工作线程投递的 UI 动作（20 ms 一次）。"""
        q = self._ui_queue
        for _ in range(len(q)):
            try:
                fn, a, kw = q.popleft()
            except IndexError:
                break
            try:
                fn(*a, **kw)
            except Exception:      # 单个 UI 动作失败不应影响后续
                pass

    def _warn_batch_skip(self, reason: str) -> None:
        """批量下发被跳过时限频提示，避免静默不动（跨线程安全）。"""
        now = time.monotonic()
        if now - getattr(self, "_batch_warn_t", 0.0) < 1.0:
            return
        self._batch_warn_t = now
        self._ui_call(self._ctrl_status, f"批量下发跳过：{reason}", log=False)

    def _send_motor_batch(self, outs) -> bool:
        """把本拍要改的电机目标合成一帧 0xD3（30 路）下发。

        100 Hz 一拍一帧，替代“每根绳一帧 0xDE”：P4 侧只取一次锁、
        复制一次目标数组、post 一个 RUN_DIRECT 事件，也没有逐命令的
        INFO 日志，3 根绳同时控时不会把 host task 压垮。
        返回是否真正交给串口线程；False 时调用方不要更新 targets。
        """
        if not outs or self.rx_thread is None:
            return False
        if not self.last_servo_abs_all or len(self.last_servo_abs_all) < 30:
            self._warn_batch_skip("无 30 路 ABS 快照")
            return False
        if self.rx_thread.tx_queue.qsize() > 200:
            self._warn_batch_skip("下行队列积压")
            return False
        base = [int(v) for v in self.last_servo_abs_all[:30]]
        for m in SERVO_TARGETS:
            v = self.targets.get(m)
            if v is not None:
                base[m] = int(v)
        for m, out in outs.items():
            base[m] = int(out)
        ok = self.rx_thread.send(build_motor_pos_abs_cmd(base))
        if not ok:
            self._warn_batch_skip("串口线程已停止")
        return ok

    def _apply_force_step(self, step, max_trim: float) -> None:
        """三力控模式统一出口（增量式，基准 = **实测当前位置**）。

        out = 实测当前位置 + 本拍整数步长；max_trim 限制"相对进入点的累计行程"，
        堵转/丢帧时目标不漂。三根绳的目标合并成一帧 0xD3 下发。

        **历史教训（2026-11-20，别再试）**：11-19 曾把基准改成"上一帧目标"，
        想让目标值跑在前面给伺服"跑道"加速。结果 `max_step=20` 时目标值以 2000 c/s
        前进、伺服只能 ~1000 c/s，目标值相对实测越积越远（直到 max_trim=5000），
        执行器被顶成 bang-bang → **现场剧烈振荡**。
        要提速应该动伺服的**速度/加速度指令**，或把 `max_step` 降到 ≈ 伺服能力
        （1000 c/s → 10 counts/帧），**不能**让目标值跑在实测前面。至于"松绳时
        目标值该不该持续前进"，见 `_apply_force_step` 的收绳阶段方案（有上限、可退出）。
        """
        origins = [self._motor_origin.get(m) for m in MOTOR_FOR_CABLE]
        if any(o is None for o in origins):
            self._stop_closed_loop("缺少电机起点")
            return
        # 2026-11-23 防御：`_force_base` 只有在力控族模式启动时才初始化。
        # 若某条路径漏了（阻抗模式曾经就是这样），这里就地补一个基准，
        # 而不是让 `base - max_trim` 抛 TypeError 把控制线程打死。
        if getattr(self, "_force_base", None) is None:
            self._force_base = [self._motor_pos_now(m) for m in MOTOR_FOR_CABLE]
        need_send = getattr(self, "_force_need_send", False)
        now_rel = self._latest_t if self._latest_t is not None else 0.0
        outs = {}
        for i, m in enumerate(MOTOR_FOR_CABLE):
            n = int(step[i])
            if n == 0 and not need_send:
                continue
            cur = self._motor_pos_now(m)
            base = self._force_base[i]
            out = cur + n
            # 相对进入点的累计行程夹紧（堵转/丢帧时目标不漂）
            out = max(base - int(max_trim), min(base + int(max_trim), out))
            out = max(origins[i] - MOTOR_SOFT_LIMIT,
                      min(origins[i] + MOTOR_SOFT_LIMIT, out))
            if m in self._cl_motor_on:
                outs[m] = out
                self.channels[f"m{m}_tgt"].buf.append(now_rel, float(out))
                self.channels[f"force_trim_{i + 1}"].buf.append(
                    now_rel, float(out - base))
                self._force_trim[i] = float(out - base)
            else:
                # 未勾选的缆不驱动、也不计入 trim 展示（否则状态行的 trim
                # 会混进没被下发的缆，看着像在动实际没动）。
                self._force_trim[i] = 0.0
        sent = self._send_motor_batch(outs)
        if sent:
            for m, out in outs.items():
                self.targets[m] = out
        if need_send and sent:
            self._force_need_send = False

    def _force_tick_prelude(self, roll: float, pitch: float, name: str):
        """三力控模式共用的逐拍前置：越界停 / 张力丢失停。
        返回 (last|None)——None 时调用方直接 return（内部已处理提示）。"""
        if abs(roll) > 30.0 or pitch < -30.0 or pitch > 50.0:
            self._stop_closed_loop(
                f"{name}：关节越界 ROLL{roll:+.1f}° PITCH{pitch:+.1f}°")
            return None
        last = self._tension_last
        if last is None:
            self._stop_closed_loop(f"{name}：张力数据丢失")
            return None
        return last

    def _force_tick_freeze(self, name: str) -> None:
        """STALE 冻结提示（33Hz 节流），三力控模式共用。"""
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        if self._cl_tick_count % 6 == 0:
            self._cl_status_set(f"{name}：张力数据过期 → 冻结（电机保持）")

    def _force_tick_apply(self, name: str, p, trim, flags, last,
                          roll: float, pitch: float, mode_id: int = 0,
                          f_target=None):
        """三个力控模式共用的收尾（2026-11-19 抽出，原来三份重复）。

        顺序：过载 → 停环；trim 缺失（过期/无零空间）→ 冻结；否则
        量 τ、下发步长、累加拍数。

        Args:
            f_target: 本拍三缆的**目标张力** [N]（`f_d`）。给了就推到 `tension_f*_tgt`
                曲线上，和实测 `tension_f*` 同图对比（2026-11-24 用户要求）。
                各模式来源不同：力控/阻抗=`f_d`（分配结果），张力=`f_target`，
                张紧=`t*·n̂`。

        Returns:
            (ok: bool, tau | None, tick_count)
            ok=False 时调用方直接 return（停环/冻结已在此处理）。
        """
        if flags & FORCE_OVERLOAD:
            # 停环由 `_tension_guard` 统一下结论（含 3 拍去抖），这里只本拍不下发。
            return False, None, 0
        if trim is None:
            self._force_tick_freeze(name)
            return False, None, 0
        tau = self._tau_meas(roll, pitch, last[1])   # 状态行用；曲线由样本入口统一推
        if f_target is not None:
            self._push_tension_tgt_curves(f_target)
        self._apply_force_step(trim, p.max_trim)
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        self._record_diag(mode_id, roll, pitch, last[1], tau, p)
        return True, tau, self._cl_tick_count

    def _push_tension_tgt_curves(self, f_target) -> None:
        """把本拍三缆**目标张力**推到 `tension_f*_tgt` 曲线（2026-11-24）。

        只做曲线，不参与控制。与 `tension_f*`（实测）同组「腕部张力」，
        在曲线窗里可以三缆"目标 vs 实测"成对看。
        """
        try:
            vals = [float(v) for v in f_target][:3]
        except (TypeError, ValueError):
            return
        if len(vals) < 3:
            return
        rel = self._latest_t if self._latest_t is not None else 0.0
        for i, v in enumerate(vals, start=1):
            ch = self.channels.get(f"tension_f{i}_tgt")
            if ch is not None and math.isfinite(v):
                ch.buf.append(rel, v)

    # ---- 诊断记录（2026-11-19）：给「🔬 诊断 CSV」用 ----
    # 目的：把「位姿 + 三缆张力 + τ + 预紧 + 下发 trim」写进同一张表，
    # 用于离线分析"张紧时 τ 到底有多大、由什么误差造成"。
    # 与力状态卡（只有 t/τR/τP/t）互补：这里有三缆张力和位姿。
    def _record_diag(self, mode_id: int, roll: float, pitch: float,
                     fvals, tau, p) -> None:
        """20 Hz 抽样记录一行（100 Hz 主循环每 5 拍取 1）。"""
        if self._cl_tick_count % 5 != 0:
            return
        n = getattr(p, "null_dir", None)
        if n is None:                       # 张力模式没有 null_dir → 用几何缓存里的 n̂
            geo = self._force_geo(roll, pitch)
            n = geo[1] if geo is not None else None
        t_m = (sum(fvals[i] * n[i] for i in range(3))
               if n else float("nan"))
        pre = getattr(p, "t_target", None)
        if pre is None:
            pre = getattr(p, "preload_n", float("nan"))
        t_rel = self._latest_t if self._latest_t is not None else 0.0
        self._diag_rows.append((
            t_rel, float(mode_id), roll, pitch,
            fvals[0], fvals[1], fvals[2], t_m,
            (tau[0] if tau else float("nan")) * 1000.0,   # mN·m（保留 2 位小数）
            (tau[1] if tau else float("nan")) * 1000.0,
            float(pre),
            self._force_trim[0], self._force_trim[1], self._force_trim[2]))

    def _export_diag_csv(self) -> None:
        """导出诊断 CSV。

        位置模式：t_s, roll, pitch, tgt_roll, tgt_pitch, 下发目标 counts, 实测 counts（20 Hz）
        力控/张力：t_s, mode, roll, pitch, f1..f3, t_meas, τ(2), 预紧, trim(3)（20 Hz）
        混合模式：三绳实测张力、电机位置、复位绳及两轴前馈状态。
        """
        if self._cl_mode == "c1_position":
            rows = list(self._c1_diag_rows)
            if len(rows) < 2:
                self._ctrl_status("诊断：先运行混合模式采集数据", log=False)
                return
            name = "diag_c1_position_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".csv"
            path = dump_csv(
                name,
                header=["roll_deg", "pitch_deg", "tgt_roll_deg", "tgt_pitch_deg",
                        "c1_n", "c1_target_n", "tgt_c1_c", "tgt_c2_c", "tgt_c3_c",
                        "meas_c1_c", "meas_c2_c", "meas_c3_c", "c1_pid_c", "c1_ff_c",
                        "angle_ff_gain", "c1_ff_gain", "angle_flags",
                        "c1_step_limited", "c1_travel_limited", "c23_step_limited",
                        "c1_age_ms", "command_sent", "c2_n", "c3_n",
                        "return_cable", "return_n", "return_target_n", "return_pid_c",
                        "return_ff_c", "return_ff_gain", "return_step_limited",
                        "return_travel_limited", "angle_step_limited",
                        "return_age_ms", "roll_ff_on", "pitch_ff_on",
                        "roll_ff_gain", "pitch_ff_gain"],
                t=[row[0] for row in rows],
                columns=[list(col) for col in zip(*(row[1:] for row in rows))])
            self._ctrl_status(
                f"诊断：已导出 {len(rows)} 行 → {name}" if path else "诊断：导出失败",
                log=False)
            return
        if self._cl_mode == "position":
            rows = list(self._pos_diag_rows)
            if len(rows) < 2:
                self._ctrl_status(
                    "诊断：位置模式还没有数据（先跑一次闭环 ≥1 秒）", log=False)
                return
            name = ("diag_pos_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    + ".csv")
            cols = list(zip(*[r[1:] for r in rows]))
            path = dump_csv(
                name,
                header=["roll_deg", "pitch_deg", "tgt_roll_deg", "tgt_pitch_deg",
                        "tgt27_c", "tgt28_c", "tgt29_c",
                        "meas27_c", "meas28_c", "meas29_c"],
                t=[r[0] for r in rows],
                columns=[list(c) for c in cols])
            self._ctrl_status(
                (f"诊断：已导出 {len(rows)} 行 → {name}" if path
                 else "诊断：导出失败（路径校验不过）"), log=False)
            return
        rows = list(self._diag_rows)
        if len(rows) < 2:
            self._ctrl_status("诊断：还没有数据（先跑一次闭环 ≥1 秒）", log=False)
            return
        name = ("diag_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                + ".csv")
        cols = list(zip(*[r[1:] for r in rows]))
        path = dump_csv(
            name,
            header=["mode", "roll_deg", "pitch_deg", "f1_N", "f2_N", "f3_N",
                    "t_meas_N", "tau_r_mNm", "tau_p_mNm", "preload_N",
                    "trim1_c", "trim2_c", "trim3_c"],
            t=[r[0] for r in rows],
            columns=[list(c) for c in cols])
        self._ctrl_status(
            (f"诊断：已导出 {len(rows)} 行 → {name}" if path
             else "诊断：导出失败（路径校验不过）"), log=False)

    def _cl_tick_tension(self, roll: float, pitch: float) -> None:
        """100Hz 张力控制：每缆独立张力 PI → 相对位置增量（out=实测位置+步长）。"""
        p = self._tension_params()
        if p is None:
            self._stop_closed_loop("张力控制：参数非法（含 trim方向格式）")
            return
        last = self._force_tick_prelude(roll, pitch, "张力控制")
        if last is None:
            return
        sine_txt = ""
        # 自愈（2026-11-25）：正在跑自动调参/正弦但没有记录文件 → 就地开一个，
        # 避免"跑完 98 s 才发现没落盘"。
        _want_log = ((getattr(self, "cl_auto_tune_check", None) is not None
                      and self.cl_auto_tune_check.isChecked())
                     or (getattr(self, "cl_tension_sine_check", None) is not None
                         and self.cl_tension_sine_check.isChecked()))
        if _want_log and getattr(self, "_sine_log_fp", None) is None:
            self._sine_log_open()
        # 2026-11-24：**自动调参**优先（与正弦互斥）。序列见 wrist_autotune。
        if (getattr(self, "cl_auto_tune_check", None) is not None
                and self.cl_auto_tune_check.isChecked()):
            if self._auto_t0_pc is None:
                self._auto_t0_pc = time.perf_counter()
            t_auto = time.perf_counter() - self._auto_t0_pc
            fmin_e, fmax_e, _ok = self._effective_flimits()
            idx, name, kind, tgts, local = wrist_autotune.command_at(
                t_auto, f_min=fmin_e, f_max=fmax_e)
            if idx is None:
                if self._auto_next_round(p):
                    return
                self._stop_closed_loop(
                    f"🤖 自动调参完成（{wrist_autotune.stage_count()} 档 / "
                    f"{wrist_autotune.total_seconds():g}s，共 "
                    f"{getattr(self, '_auto_round', 0) + 1} 轮）—— 数据已保存")
                return
            p = self._retarget(p, tgts)
            self._auto_stage = idx
            self._auto_kind = kind
            sine_txt = (f"  🤖{idx + 1}/{wrist_autotune.stage_count()} {name}"
                        f" t={local:.1f}s → {tgts[0]:.2f}N")
        # 手动正弦跟随（与自动调参互斥）
        elif (getattr(self, "cl_tension_sine_check", None) is not None
                and self.cl_tension_sine_check.isChecked()):
            f_sine, why = self._tension_sine_targets(p.f_target)
            if f_sine is None:
                self._stop_closed_loop(f"正弦跟随：{why}")
                return
            # ⚠ 必须用 `_retarget` 而不是手写构造：手写会**丢掉逐缆增益**
            # （kp3/ki3/... = None）→ 三缆全部退回标量（= 列表第一个值），
            # 表现就是"开了正弦以后三根缆都只看第一个参数"（2026-11-24 实战发现）。
            p = self._retarget(p, f_sine)
            sine_txt = (f"  🔁A={self._cl_fval('sine_amp', 1.0, 0.0, 100.0):.2f}N"
                        f" f={self._cl_fval('sine_hz', 0.5, 0.0, 20.0):.3f}Hz"
                        f" t={time.monotonic() - (self._sine_t0 or time.monotonic()):.1f}s")
        age_ms = (time.monotonic() - last[0]) * 1000.0
        trim, flags = wrist_tension_step(p, self._tension_state, last[1],
                                         age_ms, self._cl_dt)
        ok, tau, n = self._force_tick_apply("张力控制", p, trim, flags, last,
                                            roll, pitch, mode_id=1,
                                            f_target=getattr(p, "f_target", None))
        if not ok:
            return
        # 正弦测试数据自动落盘（只在勾选时写；写失败自动关文件，不影响控制）
        if sine_txt and getattr(self, "_sine_log_fp", None) is not None:
            self._sine_log_row(
                roll, pitch, p.f_target, last[1], self._force_trim,
                stage=getattr(self, "_auto_stage", -1),
                kind=getattr(self, "_auto_kind", ""))
        if n % 6 == 0:
            tb = self._t_bound_note()
            self._cl_status_set(
                "张力控  f=[%s]→[%s]N  τ=R·f=[%+.4f,%+.4f]N·m  trim=[%s]c%s%s"
                % ("/".join(f"{v:.2f}" for v in last[1]),
                   "/".join(f"{v:.2f}" for v in p.f_target),
                   tau[0] if tau else 0.0, tau[1] if tau else 0.0,
                   "/".join(f"{v:+.0f}" for v in self._force_trim),
                   f"  {tb}" if tb else "", sine_txt))

    # ---------- 正弦跟随的数据记录（2026-11-24） ----------
    # 目的：用户跑正弦时不用手工导出，数据自动落到 run_data/sine/*.csv，
    # 频率/幅值/符号写在文件头注释里，事后可离线算幅值比与相位滞后。
    SINE_LOG_DIR = "sine"

    def _sine_log_open(self) -> None:
        """开一个新的正弦记录文件（勾上「正弦跟随」时调用）。失败不影响控制。"""
        self._sine_log_close()
        try:
            d = str(REPO_ROOT / "run_data" / self.SINE_LOG_DIR)
            os.makedirs(d, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(d, f"sine_{stamp}.csv")
            # 同一秒内连开两次（同一轮里勾选→起环）不能覆盖前一个文件
            _n = 2
            while os.path.exists(path):
                path = os.path.join(d, f"sine_{stamp}_{_n}.csv")
                _n += 1
            fp = io.open(path, "w", encoding="utf-8", newline="")
            amp = self._cl_fval("sine_amp", 1.0, 0.0, 100.0)
            hz = self._cl_fval("sine_hz", 0.5, 0.0, 20.0)
            ph = self._cl_fval("sine_phase", 0.0, -360.0, 360.0)
            sg = (self.cl_edits["sine_sign"].text()
                  if self.cl_edits.get("sine_sign") is not None else "1,1,1")
            base = [self._cl_fval(f"f{i}_tgt", 2.0, 0.0, 50.0) for i in (1, 2, 3)]
            # ---- 原文读取器（**必须用输入框原文**，不能用 `_cl_fval`）----
            # 2026-11-24 教训：逐缆填 "18,30,24" 时 `_cl_fval(float)` 解析失败会
            # 退回默认值 → 文件头把 kp 记成 15（实际 18/30/24）→ 事后分析误判。
            def _raw(k):
                try:
                    return self.cl_edits[k].text().strip() or "-"
                except (KeyError, AttributeError):
                    return "?"

            # 混合行（`_c1_position_edits`）的原文读取器：下面「混合正弦」与
            # 「混合模式增益」两段都用它，**只定义一次**。
            def _rawc(k, d="-"):
                try:
                    return self._c1_position_edits[k].text().strip() or d
                except (KeyError, AttributeError):
                    return "?"
            fp.write(f"# 正弦跟随测试 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            if self._cl_mode == "c1_position":
                label = f"C{self._hybrid_return_index + 1}"
                # 目标角框留空时，运行时基值取的是**实测角度** —— 文件头据此写。
                def _ang_base(k):
                    try:
                        return self._c1_position_edits[k].text().strip() or "实测"
                    except (KeyError, AttributeError):
                        return "?"
                fp.write(f"# 混合正弦 复位绳={label} {label}幅度={_rawc('c1_sine_amp', '3')}N "
                         f"{label}频率={_rawc('c1_sine_hz', '0.25')}Hz "
                         f"{label}相位={_rawc('c1_sine_phase', '0')}deg "
                         f"{label}符号={_rawc('c1_sine_sign', '1')} "
                         f"基值={_rawc('c1_pos_target', '5')}N | "
                         f"角度频率={_rawc('ang_sine_hz', '0.2')}Hz "
                         f"ROLL幅值={_rawc('ang_sine_roll', '0')}deg "
                         f"PITCH幅值={_rawc('ang_sine_pitch', '0')}deg "
                         f"角度基值=({_ang_base('roll_tgt')},"
                         f"{_ang_base('pitch_tgt')})deg "
                         f"调参轮数={_rawc('c1_auto_rounds', '3')}\n")
            else:
                fp.write(f"# 幅度A={amp:g}N 频率f={hz:g}Hz 相位={ph:g}deg "
                         f"符号={sg} 基值={base}\n")
            fp.write(f"# kp_f={_raw('kp_f')} ki_f={_raw('ki_f')} "
                     f"i_term_lim={_raw('i_term_lim')} "
                     f"max_step_f={_raw('max_step_f')} "
                     f"f_min={_raw('f_min')} fmax_f={_raw('fmax_f')} "
                     f"trim_sign={_raw('trim_sign')}\n")
            # 2026-11-26：混合模式（C1 单路张力 + 双轴角度）单独记一段，
            # 否则事后无法从文件头判断这组数据是哪套增益跑出来的。
            if self._cl_mode == "c1_position":
                fp.write(f"# 混合模式 {label}目标={_rawc('c1_pos_target')}N "
                         f"{label} Kp/Ki/Kd/积分上限="
                         f"{_rawc('c1_pos_kp')}/{_rawc('c1_pos_ki')}/"
                         f"{_rawc('c1_pos_kd')}/{_rawc('c1_pos_i_limit')} "
                         f"{label}步长={_rawc('c1_pos_step')} 行程={_rawc('c1_pos_travel')} "
                         f"角度Kp/Ki/Kd={_rawc('pos_kp')}/{_rawc('pos_ki')}/{_rawc('pos_kd')} "
                         f"角度步长={_rawc('pos_step')} 死区={_rawc('pos_deadband')} "
                         f"限幅={_rawc('pos_limit')}\n")
                gains = ["C" + str(i + 1) + "=" + "/".join(edit.text().strip() or "默认"
                         for edit in row) for i, row in enumerate(self._hybrid_pi_edits)]
                ff_roll, ff_pitch = (int(check.isChecked()) for check in self._hybrid_ff_checks)
                fp.write(f"# Roll前馈={ff_roll} 系数={_rawc('pos_ff')} "
                         f"Pitch前馈={ff_pitch} 系数={_rawc('pos_ff_pitch')} 逐绳Roll/Pitch PI "
                         + " ".join(gains) + "\n")
            fp.write("# 注意：t_s 从勾选时刻起算；tgt=目标张力[N]；f=实测张力[N]；"
                     "trim=本拍位置增量[counts]\n")
            fp.write("t_s,roll_deg,pitch_deg,"
                     "f1_tgt,f2_tgt,f3_tgt,f1,f2,f3,"
                     "trim1,trim2,trim3,stage,kind,"
                     "roll_tgt_deg,pitch_tgt_deg,c1_tgt_n\n")
            self._sine_log_fp = fp
            self._sine_log_path = path
            self._sine_t0_pc = time.perf_counter()
            self._sine_log_n = 0
            self._ctrl_status(
                f"📄 正弦数据记录 → {path}",
                log=False)
        except OSError as exc:
            self._sine_log_fp = None
            self._sine_log_path = None
            self._ctrl_status(f"⚠ 正弦记录文件打不开（{exc}）→ 只跑不记", log=False)

    def _sine_log_close(self) -> None:
        fp = getattr(self, "_sine_log_fp", None)
        if fp is not None:
            try:
                fp.close()
            except OSError:
                pass
            self._ctrl_status(
                f"📄 正弦数据已存（{getattr(self, '_sine_log_n', 0)} 行）: "
                f"{os.path.basename(getattr(self, '_sine_log_path', '') or '')}",
                log=False)
        self._sine_log_fp = None

    def _sine_log_row(self, roll: float, pitch: float, f_tgt, f_meas,
                      trim, stage: int = -1, kind: str = "",
                      angle_tgt=None, c1_tgt=None) -> None:
        """写一行（100 Hz，每 10 行 flush 一次；任何异常都不打断控制）。

        `stage`/`kind`（2026-11-24 加）：自动调参时标出"第几档、阶跃还是正弦"，
        离线分析靠它切段落；手动正弦时是 `-1`/`sine`。

        `angle_tgt` / `c1_tgt`（2026-11-26 加，**只在末尾追加列**）：
        混合模式要同时看「角度目标 vs 实测」和「C1 目标」，张力模式填 None
        即写空值。追加在末尾是为了不破坏已有 CSV 的列序。
        """
        fp = getattr(self, "_sine_log_fp", None)
        if fp is None:
            return
        try:
            # ⚠ 必须用 perf_counter：Windows 上 `time.monotonic()` 分辨率是
            # **15.6 ms**（GetTickCount64），写出来的 t_s 会被量化成
            # "15/16 ms 台阶 + 一堆 0 ms"，看起来像"控制频率低/连跑"，
            # 实际是时钟分辨率伪影（2026-11-24 血泪教训：
            #  `CL_RATE` 用 perf_counter 测出 hz=100 与 CSV 的"15 ms"矛盾，
            #  才发现是日志时钟的问题）。
            t = time.perf_counter() - (self._sine_t0_pc or time.perf_counter())

            def _num(v):
                if v is None:
                    return ""
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    return ""
                return "%.4f" % f if math.isfinite(f) else ""

            fp.write("%.4f,%.3f,%.3f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.1f,%.1f,%.1f,"
                     "%d,%s,%s,%s,%s\n"
                     % (t, roll, pitch,
                        f_tgt[0], f_tgt[1], f_tgt[2],
                        f_meas[0], f_meas[1], f_meas[2],
                        trim[0], trim[1], trim[2], int(stage), str(kind),
                        _num(None if angle_tgt is None else angle_tgt[0]),
                        _num(None if angle_tgt is None else angle_tgt[1]),
                        _num(c1_tgt)))
            self._sine_log_n = getattr(self, "_sine_log_n", 0) + 1
            if self._sine_log_n % 10 == 0:
                fp.flush()
        except (OSError, TypeError, ValueError, IndexError):
            self._sine_log_close()

    def _retarget(self, p, f_target):
        """**只换目标张力**、其余参数（含逐缆增益）原样保留（2026-11-24）。

        为什么单独一个方法：正弦跟随每拍都要换目标。如果就地手写
        `WristTensionParams(...)`，很容易漏掉 `kp3/ki3/max_step3/i_term_lim3`
        —— 一漏就变成"三缆全部退回标量（= 逐缆列表的第一个值）"，
        现场表现正是"开了正弦以后三根缆都只看第一个参数"。

        用 `__slots__` 全量拷贝 + 只改 `f_target`，从结构上杜绝这种漏项。
        """
        new = WristTensionParams.__new__(WristTensionParams)
        for name in WristTensionParams.__slots__:
            setattr(new, name, getattr(p, name, None))
        new.f_target = [float(v) for v in f_target]
        return new

    # ---------- 自动调参的**轮间迭代**（2026-11-25 用户要求）----------
    def _auto_next_round(self, p) -> bool:
        """一轮跑完后：算指标 → 改增益 → 决定是否再来一轮。

        Returns:
            True  = 已切换到下一轮（调用方直接 return，继续跑）
            False = 结束（调用方去停环）
        """
        path = getattr(self, "_sine_log_path", None)
        self._sine_log_close()
        rnd = getattr(self, "_auto_round", 0)
        try:
            max_rounds = int(max(1.0, min(6.0, self._cl_fval(
                "auto_rounds", 3.0, 1.0, 6.0))))
        except (TypeError, ValueError):
            max_rounds = 3
        stages = []
        try:
            meta, data = wrist_autotune.read_csv(path) if path else (None, None)
            if data:
                stages = wrist_autotune.metrics(data)
        except (OSError, ValueError):
            stages = []
        if not stages:
            self._ctrl_status("⚠ 自动调参：本轮数据读不到 → 结束", log=True)
            return False
        cur = {
            "kp": [float(x) for x in (p.kp3 or [p.kp] * 3)],
            "ki": [float(x) for x in (p.ki3 or [p.ki] * 3)],
            "itl": [float(x) for x in (p.i_term_lim3 or [p.i_term_lim] * 3)],
            "kd": [float(x) for x in (p.kd3 or [p.kd] * 3)],
        }
        new, notes, conv = wrist_autotune.tune(
            stages, cur, max_rounds_hit=(rnd + 1 >= max_rounds))
        try:
            self._safety("AUTOTUNE_ROUND", round=rnd + 1, max_rounds=max_rounds,
                         converged=int(conv), kp=wrist_autotune.fmt(new["kp"]),
                         ki=wrist_autotune.fmt(new["ki"]),
                         itl=wrist_autotune.fmt(new["itl"]),
                         kd=wrist_autotune.fmt(new["kd"]))
        except Exception:
            pass
        for note in notes:
            self._ctrl_status("🤖 " + note, log=True)
        if conv:
            self._ctrl_status("✅ 自动调参收敛（增益变化已小于阈值）", log=True)
            return False
        if rnd + 1 >= max_rounds:
            self._ctrl_status(f"⏹ 自动调参用完 {max_rounds} 轮", log=True)
            return False
        # 把新增益写回界面（GUI 线程），等一拍让快照刷新，再开下一轮
        self._ui_call(self._apply_autotune_gains, new)
        self._force_state.reset()
        self._tension_state.reset()
        self._force_base = [self._motor_pos_now(m) for m in MOTOR_FOR_CABLE]
        self._force_trim = [0.0, 0.0, 0.0]
        self._auto_t0_pc = None
        self._auto_stage = -1
        self._auto_kind = ""
        self._auto_round = rnd + 1
        self._sine_log_open()
        self._ctrl_status(
            f"🔁 进入第 {self._auto_round + 1}/{max_rounds} 轮（增益已更新）",
            log=True)
        return True

    def _apply_autotune_gains(self, g) -> None:
        """把新增益写进输入框（**必须在 GUI 线程**，由 `_ui_call` 投递）。"""
        try:
            f = wrist_autotune.fmt
            self.cl_edits["kp_f"].setText(f(g["kp"]))
            self.cl_edits["ki_f"].setText(f(g["ki"]))
            self.cl_edits["i_term_lim"].setText(f(g["itl"]))
            self.cl_edits["kd_f"].setText(f(g["kd"]))
            self._refresh_cl_param_cache()
        except (KeyError, AttributeError):
            pass

    def _on_auto_tune_toggled(self, on: bool) -> None:
        """自动调参开/关（2026-11-24）。与「正弦跟随」互斥。"""
        self._auto_t0_pc = None
        if on:
            if self.cl_tension_sine_check.isChecked():
                self.cl_tension_sine_check.setChecked(False)
            self._sine_log_open()
            self._ctrl_status("🤖 " + wrist_autotune.summary_text(), log=True)
            self._ctrl_status(
                "🤖 自动调参已开：起环后自动跑完 7 档；中途按「停止闭环」即中止并保存",
                log=False)
        else:
            self._sine_log_close()
            self._ctrl_status("⏹ 自动调参已关", log=False)

    def _on_c1_test_toggled(self, on: bool, other) -> None:
        """混合模式的「正弦 / 自动调参」开关（2026-11-26）。

        两者互斥；也**不与张力模式的两个开关联动** —— 它们的被控量完全不同
        （C1 单路 vs 三缆共模），共用一个开关会互相污染。
        """
        self._auto_t0_pc = None
        self._auto_stage = -1
        self._auto_kind = ""
        if on:
            self._sine_t0 = None            # 相位基准归零：从基值起，不跳变
            try:
                if other is not None and other.isChecked():
                    other.setChecked(False)
            except (AttributeError, RuntimeError):
                pass
            self._sine_log_open()           # 每次开启都换一份文件
            is_auto = other is getattr(self, "cl_c1_sine_check", None)
            self._ctrl_status(
                ("🧪 混合自动调参已开：" + hybrid_autotune.summary_text().replace("C1", "复位绳")) if is_auto
                else "🧪 混合正弦已开。复位绳按张力正弦参数变化，张力幅度填 0 时保持恒定。"
                     "「ROLL幅值°/PITCH幅值°」>0 时角度也按「角度Hz」摆"
                     "（参数都在本模式行里）", log=False)
        else:
            self._sine_log_close()

    def _on_tension_sine_toggled(self, on: bool) -> None:
        """正弦跟随开/关（2026-11-24）。重开时把相位基准归零 → 从 sin(0)=0 起，不跳变。"""
        self._sine_t0 = None if on else self._sine_t0
        if on:
            if getattr(self, "cl_auto_tune_check", None) is not None \
                    and self.cl_auto_tune_check.isChecked():
                self.cl_auto_tune_check.setChecked(False)
            self._sine_log_open()          # 每次勾上都开新文件（频率改了就换一份）
            self._ctrl_status(
                "🔁 正弦跟随已开：目标 = 基值 + 符号·A·sin(2πft+φ)"
                "（t 从此刻算起，起点为基值）", log=False)
        else:
            self._sine_log_close()
            self._ctrl_status("⏹ 正弦跟随已关：目标回到常数「C目标N」", log=False)

    def _tension_sine_targets(self, base_target):
        """张力模式的**正弦目标**（2026-11-24 用户要求，测内环动态响应）。

            f_target_i = base_i + sign_i · A · sin(2π f t + φ)

        · `t` 从勾上「正弦跟随」那一刻算起（`_sine_t0`），所以起点严格等于基值；
        · 目标先夹到 `[f_min, f_max−余量]` —— 幅度填太大不会撞界停环，只会削顶；
        · 任何一项非法（幅度/频率/符号）→ 返回 `(None, 说明)` 交给调用方报错。

        Returns:
            (list[3] | None, str) —— `None` 表示参数非法（带原因）。
        """
        try:
            amp = self._cl_fval("sine_amp", 1.0, 0.0, 100.0)
            hz = self._cl_fval("sine_hz", 0.5, 0.0, 20.0)
            phase = math.radians(self._cl_fval("sine_phase", 0.0, -360.0, 360.0))
        except (TypeError, ValueError):
            return None, "正弦参数读取失败"
        raw = (self.cl_edits.get("sine_sign").text()
               if self.cl_edits.get("sine_sign") is not None else "1,1,1")
        try:
            signs = [float(v) for v in raw.replace("，", ",").split(",")]
            if len(signs) != 3:
                raise ValueError
            signs = [1.0 if v >= 0 else -1.0 for v in signs]
        except (TypeError, ValueError):
            return None, f"符号需 3 个 ±1（当前 {raw!r}）"
        now = time.monotonic()
        if getattr(self, "_sine_t0", None) is None:
            self._sine_t0 = now
        t = now - self._sine_t0
        fmin, fmax, _ok = self._effective_flimits()
        # 削顶而不是撞界：留 1 N（或 4%）给超调，与分配层的 headroom 口径一致
        hi = max(fmin + 0.1, fmax - min(FORCE_FMAX_HEADROOM_N, 0.04 * fmax))
        out = sine_target_step(base_target, amp, hz, phase, t, signs, fmin, hi)
        if not out:
            return None, "正弦目标生成失败（参数或基值非法）"
        return out, ""

    def _tight_f_target(self, p) -> list:
        """张紧的三缆目标张力 f_d = f_tau0 + t*·n̂（2026-11-17 改结构）。

        为什么改：原来把误差合成 1 个标量 `t` 再按 n̂ 分配，反馈秩只有 1 ——
        n̂_i 小的那根绳"看不见"（(−18,0) 时 C3 错 2.89 N 才让 t 动 0.05 N）。
        现在每缆有绝对目标，误差 3 维、秩 3，三根绳各自闭环。

        `f_tau0` 是"力矩偏移"（重力/外载补偿）：
        **暂缓**（用户 2026-11-17 定），现恒为 0 ⇒ f_d 是"零力矩分布"。
        后果：腕带载时会被这条分布带得下垂/漂移（物理必然）。
        以后要接：起环静止时锁 `f_tau0 = P⁻¹[R·f, 0]`（不是模型，只锁一次）。
        """
        return [p.t_target * p.null_dir[i] for i in range(3)]

    def _cl_tick_tight(self, roll: float, pitch: float) -> None:
        """100Hz 张紧控制（新结构）：t* → f_d = t*·n̂ → 三缆各自 PID（复用张力环）。"""
        p = self._tight_params(roll, pitch)
        if p is None:
            self._stop_closed_loop("张紧控制：参数非法或该位姿 R(q) 无效")
            return
        last = self._force_tick_prelude(roll, pitch, "张紧控制")
        if last is None:
            return
        age_ms = (time.monotonic() - last[0]) * 1000.0
        f_d = self._tight_f_target(p)
        # 目标必须先过三缆阈值（可行域检查已保证 t* 区间，这里再兜一道）
        bad = [i for i in range(3) if not (p.f_min <= f_d[i] <= p.f_max)]
        if bad:
            self._stop_closed_loop(
                "张紧控制：目标越界 "
                + " ".join(f"C{i + 1}={f_d[i]:.2f}N" for i in bad)
                + f"（需在 [{p.f_min:g},{p.f_max:g}]）")
            return
        tp = WristTensionParams(
            f_target=f_d, kp=p.kp, ki=p.ki, max_step=p.max_step,
            trim_sign=p.trim_sign, max_trim=p.max_trim, f_max=p.f_max,
            deadband=p.deadband, i_term_lim=p.i_term_lim,
            # 2026-11-24：张紧复用张力环，D 项也要跟着带过来
            kd=self._cl_fval("kd_f", 0.0, 0.0, 1.0),
            kd3=self._cl_fval3("kd_f", 0.0, 0.0, 1.0))
        trim, flags = wrist_tension_step(tp, self._tension_state, last[1],
                                         age_ms, self._cl_dt)
        ok, tau, n = self._force_tick_apply("张紧控制", p, trim, flags, last,
                                            roll, pitch, mode_id=2, f_target=f_d)
        if not ok:
            return
        if n % 6 == 0:
            t_meas = sum(last[1][j] * p.null_dir[j] for j in range(3))
            tb = self._t_bound_note()
            self._cl_status_set(
                "张紧控  f=[%s]→[%s]N  t=%.2f→%.1fN  τ=[%+.4f,%+.4f]N·m  trim=[%s]c%s"
                % ("/".join(f"{v:.2f}" for v in last[1]),
                   "/".join(f"{v:.1f}" for v in f_d),
                   t_meas, p.t_target,
                   tau[0] if tau else 0.0, tau[1] if tau else 0.0,
                   "/".join(f"{v:+.0f}" for v in self._force_trim),
                   f"  {tb}" if tb else ""))

    def _c1_position_targets(self, pose):
        return tuple(float(self._c1_position_edits[key].text().strip() or value)
                     for key, value in zip(("roll_tgt", "pitch_tgt"), pose))

    def _hybrid_tension_fields(self):
        return {key: self._c1_position_edits[key].text() for key in self._hybrid_tension_labels}

    def _show_hybrid_return_selection(self) -> None:
        selected = self._hybrid_return_index
        for label, original in self._hybrid_tension_labels.values():
            label.setText(original.replace("C1", f"C{selected + 1}"))
        for i, motor in enumerate(MOTOR_FOR_CABLE):
            is_return = i == selected
            self._hybrid_pi_labels[i].setText(f"C{i + 1} / M{motor}" + (" · 复位" if is_return else ""))
            for edit in self._hybrid_pi_edits[i]:
                edit.setEnabled(not is_return)

    def _on_hybrid_return_changed(self, index: int) -> None:
        previous = self._hybrid_return_index
        if index == previous:
            return
        combo = self.cl_return_cable_combo
        if self.cl_enabled or index not in range(len(MOTOR_FOR_CABLE)):
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(previous)
            combo.blockSignals(blocked)
            return
        self._hybrid_tension_profiles[previous] = self._hybrid_tension_fields()
        self._hybrid_return_index = index
        for key, value in self._hybrid_tension_profiles[index].items():
            self._c1_position_edits[key].setText(value)
        self._show_hybrid_return_selection()
        self._c1_position_state.reset()
        self._c1_angle_state.reset()
        if self.preset_combo.currentText() == "混合调试":
            self._apply_preset(self.preset_combo.currentIndex())
        self._save_layout()

    def _restore_hybrid_settings(self, data) -> None:
        # 旧存档里的单套张力增益只迁给 C1。
        self._hybrid_tension_profiles[0] = self._hybrid_tension_fields()
        saved = data.get("hybrid_tension_profiles")
        if isinstance(saved, list):
            for profile, row in zip(self._hybrid_tension_profiles, saved):
                if isinstance(row, dict):
                    profile.update({key: str(row[key]) for key in profile if key in row})
        selected = data.get("hybrid_return_cable", 0)
        if not isinstance(selected, int) or selected not in range(len(MOTOR_FOR_CABLE)):
            selected = 0
        self._hybrid_return_index = selected
        blocked = self.cl_return_cable_combo.blockSignals(True)
        self.cl_return_cable_combo.setCurrentIndex(selected)
        self.cl_return_cable_combo.blockSignals(blocked)
        for key, value in self._hybrid_tension_profiles[selected].items():
            self._c1_position_edits[key].setText(value)
        gains = data.get("hybrid_angle_pi")
        if isinstance(gains, list):
            for edits, values in zip(self._hybrid_pi_edits, gains):
                if isinstance(values, list):
                    for edit, value in zip(edits, values):
                        edit.setText(str(value))
        axes = data.get("hybrid_ff_axes")
        if isinstance(axes, list):
            for check, value in zip(self._hybrid_ff_checks, axes):
                if isinstance(value, bool):
                    blocked = check.blockSignals(True)
                    check.setChecked(value)
                    check.blockSignals(blocked)
        self._show_hybrid_return_selection()

    def _read_c1_position_params(self):
        try:
            roll, pitch = self._c1_position_targets(self._wrist_pose_now() or (0.0, 0.0))
            v = {key: float(edit.text()) for key, edit in self._c1_position_edits.items()
                 if key not in ("roll_tgt", "pitch_tgt")}
            gain_keys = ("pos_kp", "pos_ki", "c1_pos_kp", "c1_pos_ki")
            if not all(math.isfinite(v[key]) and v[key] >= 0.0 for key in gain_keys):
                return None
            defaults = (v["pos_kp"], v["pos_ki"]) * 2
            cable_pi = []
            for i, row in enumerate(self._hybrid_pi_edits):
                values = ((0.0,) * 4 if i == self._hybrid_return_index else
                          tuple(float(edit.text().strip() or default)
                                for edit, default in zip(row, defaults)))
                if not all(math.isfinite(value) and value >= 0.0 for value in values):
                    return None
                cable_pi.append((values[:2], values[2:]))
        except ValueError:
            return None
        ranges = {
            "pos_kd": (0, 10), "pos_ff": (0, 1), "pos_ff_pitch": (0, 1),
            "pos_step": (1, 2000),
            "pos_deadband": (0, 10), "pos_limit": (1, 90),
            "c1_pos_kd": (0, 10000),
            "c1_pos_ff": (0, 1), "c1_pos_step": (1, 2000),
            "c1_pos_travel": (1, 50000), "c1_pos_i_limit": (0, 2000),
            "c1_pos_min_n": (0, 200), "c1_pos_max_n": (1, 200),
        }
        if (not all(lo <= v[key] <= hi for key, (lo, hi) in ranges.items())
                or not all(-90.0 <= a <= 90.0 for a in (roll, pitch))):
            return None
        target = v["c1_pos_target"]
        f_min, f_max = v["c1_pos_min_n"], v["c1_pos_max_n"]
        if not (0.0 < target < f_max and target >= f_min):
            return None
        angles = WristControlParams()
        angles.kp, angles.ki, angles.kd = v["pos_kp"], v["pos_ki"], v["pos_kd"]
        angles.ff_axis_gains = (v["pos_ff"], v["pos_ff_pitch"])
        angles.cable_pi = tuple(cable_pi)
        angles.ff_axes = tuple(check.isChecked() for check in self._hybrid_ff_checks)
        angles.max_step = int(v["pos_step"])
        angles.deadband_deg = v["pos_deadband"]
        angles.target_limit_deg = v["pos_limit"]
        angles.i_limit_deg = angles.target_limit_deg
        angles.soft_limit = MOTOR_SOFT_LIMIT
        angles.origin = [self._motor_origin.get(m) or 0 for m in MOTOR_FOR_CABLE]
        c1 = C1TensionParams(
            target_n=target, kp=v["c1_pos_kp"], ki=v["c1_pos_ki"], kd=v["c1_pos_kd"],
            ff_gain=v["c1_pos_ff"], max_step=int(v["c1_pos_step"]),
            travel=int(v["c1_pos_travel"]), i_limit=v["c1_pos_i_limit"],
            min_n=f_min, max_n=f_max)
        return HybridWristParams(angles, roll, pitch, c1, self._hybrid_return_index)

    def _c1_position_feedback(self, f_max, return_cable=0):
        label = f"C{return_cable + 1}"
        last = self._tension_last
        fresh_s = STALE_MS / 1000.0
        if last is None or not (0.0 <= time.monotonic() - last[0] <= fresh_s):
            return None, None, f"{label} 张力无数据或已过期"
        force = last[1][return_cable]
        if not math.isfinite(force) or force < F_SENSOR_MIN_N:
            return None, None, f"{label} 张力读数无效"
        if force >= f_max:
            return None, None, f"{label} 张力过载 {force:.2f} N（上限 {f_max:g} N）"

        t0 = self.t0
        if t0 is None:
            return None, None, "没有磁编和电机实测位置"
        names = ("enc_raw_16", "enc_raw_17", *(f"m{m}_abs" for m in MOTOR_FOR_CABLE))
        samples = [self.channels[name].buf.last_sample() for name in names]
        age_at = time.monotonic() - t0
        for name, (sample_t, value) in zip(names, samples):
            if not math.isfinite(value) or not (0.0 <= age_at - sample_t <= fresh_s):
                return None, None, f"{name} 反馈无效或已过期"
        return [int(value) for _, value in samples[2:]], last, None

    def _c1_position_geometry(self, roll, pitch, return_cable=0):
        dr, dp = self.wrist_calib.zero_offset_deg
        model = wrist_eval(math.radians(MODEL_AXIS_SIGN[0] * roll + dr),
                           math.radians(pitch_model_deg(pitch) + dp))
        if not model.math_valid or not model.angle_in_range:
            return None
        # 参与位置控制的两根绳必须能独立产生双轴修正。
        i, j = (i for i in range(len(MOTOR_FOR_CABLE)) if i != return_cable)
        a, b = model.r_m[ROLL][i], model.r_m[ROLL][j]
        c, d = model.r_m[PITCH][i], model.r_m[PITCH][j]
        if abs(a * d - b * c) <= 1e-6 * (a * a + b * b + c * c + d * d):
            return None
        return model

    def _read_cl_params(self):
        """20Hz 节流读 UI 参数（原 _cl_tick 内联段原样搬移，100Hz→20Hz）。"""
        prm = WristControlParams()
        prm.kp = self._cl_fval("kp", 0.2, 0.0, 5.0)
        prm.ki = self._cl_fval("ki", 0.05, 0.0, 100.0)
        prm.kd = self._cl_fval("kd", 0.05, 0.0, 10.0)
        prm.k_ff = self._cl_fval("k_ff", 0.3, 0.0, 1.0)
        prm.deadband_deg = self._cl_fval("deadband", 0.3, 0.0, 10.0)
        prm.target_limit_deg = self._cl_fval("limit", 25.0, 1.0, 90.0)
        prm.i_limit_deg = prm.target_limit_deg   # 积分项最多等效"一个满量程角"
        prm.soft_limit = MOTOR_SOFT_LIMIT
        prm.max_step = self._cl_fval("max_step_f", 20.0, 0.1, 2000.0)
        # 分轴每拍限幅（0 = 不限，仍由 max_step 兜底）
        prm.max_step_roll = self._cl_fval("max_step_r", 0.0, 0.0, 2000.0)
        prm.max_step_pitch = self._cl_fval("max_step_p", 0.0, 0.0, 2000.0)
        for i, m in enumerate(SERVO_TARGETS):
            origin = self._motor_origin.get(m)
            if origin is None:
                return None
            prm.origin[i] = origin
            kr, kp = self._cl_gain_vals.get(m, (0.0, 0.0))
            prm.gain_roll[i] = kr if self.cl_roll_check.isChecked() else 0.0
            prm.gain_pitch[i] = kp if self.cl_pitch_check.isChecked() else 0.0
        return prm

    def _check_cmd_authority(self) -> None:
        """启动自检：`max_step × 频率` 是否超过伺服能力（饱和 → 振荡）。

        力控输出是增量式，命令能力 = max_step[counts/拍] × (1/周期)[Hz]。
        超过 `SERVO_MAX_COUNTS_PER_S` 时，PI 一旦要求满步长，伺服就跟不上，
        执行器进入饱和/极限环（2026-11-20 现场事故的机理）。
        **只提示，不改参数**——要不要降 max_step 由操作者决定。
        """
        if self._cl_mode == "c1_position":
            params = self._c1_position_params
            if params is None:
                return
            ms = max(params.c1.max_step, params.angles.max_step)
        else:
            ms = self._cl_fval("max_step_f", 20.0, 0.1, 2000.0)
        rate = 1.0 / max(1e-3, CL_LOOP_PERIOD_S)
        cap = ms * rate
        if cap > SERVO_MAX_COUNTS_PER_S * 1.05:
            self._ctrl_status(
                f"⚠ 命令能力 {cap:.0f} c/s > 伺服 {SERVO_MAX_COUNTS_PER_S:.0f} c/s"
                f"（max_step={ms:g} × {rate:.0f}Hz）→ 若张力抖动，把 max_step 降到"
                f" {SERVO_MAX_COUNTS_PER_S / rate:.0f}", log=False)
            self._safety("CL_CMD_OVERCAP", cap_cps=round(cap, 1),
                         max_step=ms, period_s=CL_LOOP_PERIOD_S)

    def _refresh_cl_param_cache(self) -> None:
        """GUI 线程每 50 ms 刷新一次闭环参数快照（工作线程只读快照）。

        为什么：Qt 规定控件只能在 GUI 线程访问；控制线程现在独立运行，
        若在控制线程里读 `QLineEdit.text()` / `isChecked()` 属于未定义行为。
        顺带把「字符串→float」的解析从 100 Hz 降到 20 Hz。
        """
        if not self._in_gui_thread():
            return
        # 仅连接观测台时采集线程也会计算实测力矩；紧绳恢复判定还会读取边界。
        if not self.cl_enabled or self._cl_mode == "c1_position":
            self._cl_snap = {k: self.cl_edits[k].text()
                             for k in ("roll_tau_sign", "f_min", "fmax_f")}
        if not self.cl_enabled:
            self._cl_param_cache = None
            self._c1_position_params = None
            return
        if self._cl_mode == "c1_position":
            self._cl_snap["__record_on"] = self.cl_record_check.isChecked()
            self._cl_param_cache = None
            self._c1_position_params = self._read_c1_position_params()
            return
        # 控件状态快照：文本（给 _cl_fval 用）+ 勾选（给 _cl_tick 用）
        self._cl_snap = {k: w.text() for k, w in self.cl_edits.items()}
        self._cl_snap["__roll_on"] = self.cl_roll_check.isChecked()
        self._cl_snap["__pitch_on"] = self.cl_pitch_check.isChecked()
        self._cl_snap["__ff_on"] = self.cl_ff_check.isChecked()
        self._cl_snap["__record_on"] = self.cl_record_check.isChecked()
        self._cl_param_cache = self._read_cl_params()

    # ---------- 混合模式的测试激励（正弦 / 自动调参，2026-11-26）----------
    # 为什么要单独一套：混合模式的被控量是「C1 单路张力 + 双轴角度」，与张力模式
    # 的「三缆共模张力」完全不同 —— 共用一套开关会让两边的目标互相污染。
    MIX_STAGE_MANUAL = -1
    MIX_STAGE_DONE = -2

    def _c1_fval(self, key: str, default: float) -> float:
        """读「混合模式专用参数」某一框为 float（解析失败回默认）。"""
        try:
            return float(self._c1_position_edits[key].text().strip() or default)
        except (KeyError, AttributeError, TypeError, ValueError):
            return float(default)

    def _c1_test_override(self, params):
        """把「混合正弦 / 混合自动调参」的目标覆盖到 params 上。

        Returns:
            `(params2, stage, kind, note, done)`
            · 都没开     → `(params, -1, "", "", False)`
            · 序列跑完   → `(params, -2, "done", "", True)`（调用方决定下一轮/停环）
        只改**目标**，不动增益（增益在轮末由 `_c1_auto_next_round` 写回界面）。
        """
        auto_on = (getattr(self, "cl_c1_auto_check", None) is not None
                   and self.cl_c1_auto_check.isChecked())
        sine_on = (getattr(self, "cl_c1_sine_check", None) is not None
                   and self.cl_c1_sine_check.isChecked())
        if not (auto_on or sine_on):
            return params, self.MIX_STAGE_MANUAL, "", "", False
        from dataclasses import replace as _rp

        c1_min = max(0.0, self._c1_fval("c1_pos_min_n", 0.2))
        c1_max = max(c1_min + 0.1, self._c1_fval("c1_pos_max_n", 25.0))
        label = f"C{params.return_cable + 1}"
        if auto_on:
            if self._auto_t0_pc is None:
                self._auto_t0_pc = time.perf_counter()
            t_auto = time.perf_counter() - self._auto_t0_pc
            idx, name, kind, c1_n, roll_t, pitch_t, local = hybrid_autotune.command_at(
                t_auto, c1_base_n=params.c1.target_n,
                roll_base_deg=params.roll_target_deg,
                pitch_base_deg=params.pitch_target_deg,
                c1_min=max(0.2, c1_min), c1_max=c1_max,
                angle_limit_deg=self._c1_fval("pos_limit", 25.0))
            if idx is None:
                return params, self.MIX_STAGE_DONE, "done", "", True
            self._auto_stage, self._auto_kind = idx, kind
            note = (f"  🤖{idx + 1}/{hybrid_autotune.stage_count()} {name.replace('C1', label)}"
                    f" t={local:.1f}s {label}={c1_n:.2f}N R={roll_t:+.1f}° P={pitch_t:+.1f}°")
            p2 = _rp(params, roll_target_deg=roll_t, pitch_target_deg=pitch_t,
                     c1=_rp(params.c1, target_n=c1_n))
            return p2, idx, kind, note, False

        # ---- 手动正弦：C1 张力 + 角度（两路参数全部来自混合行，2026-11-26）----
        # 之前这里读的是张力行的 `sine_amp/sine_hz/...`，而那一行在混合模式下
        # 整行隐藏 → 用户改不了。现在读混合行自己的 5 个框。
        amp = self._c1_fval("c1_sine_amp", 3.0)
        hz = self._c1_fval("c1_sine_hz", 0.25)
        sg = self._c1_fval("c1_sine_sign", 1.0)
        sg = 1.0 if sg >= 0.0 else -1.0
        ph = self._c1_fval("c1_sine_phase", 0.0)
        ang_hz = self._c1_fval("ang_sine_hz", 0.2)
        amp_r = self._c1_fval("ang_sine_roll", 0.0)
        amp_p = self._c1_fval("ang_sine_pitch", 0.0)
        if self._sine_t0 is None:
            self._sine_t0 = time.monotonic()
        t = time.monotonic() - self._sine_t0
        v = (params.c1.target_n + sg * amp
             * math.sin(2.0 * math.pi * hz * t + math.radians(ph)))
        v = max(max(0.0, c1_min), min(c1_max, v))
        roll_t = params.roll_target_deg
        pitch_t = params.pitch_target_deg
        if amp_r > 0.0 or amp_p > 0.0:
            s_a = math.sin(2.0 * math.pi * ang_hz * t)
            lim_a = abs(self._c1_fval("pos_limit", 25.0))
            roll_t = roll_t + amp_r * s_a
            pitch_t = pitch_t + amp_p * s_a
            roll_t = max(-lim_a, min(lim_a, roll_t))
            pitch_t = max(-lim_a, min(lim_a, pitch_t))
        ang_txt = (f" R±{amp_r:g}°/P±{amp_p:g}°@{ang_hz:g}Hz"
                   if (amp_r > 0.0 or amp_p > 0.0) else "")
        note = (f"  🔁{label} {amp:.2f}N@{hz:.3f}Hz{ang_txt} t={t:.1f}s"
                f"→{label} {v:.2f}N")
        p2 = _rp(params, c1=_rp(params.c1, target_n=v),
                 roll_target_deg=roll_t, pitch_target_deg=pitch_t)
        return (p2, self.MIX_STAGE_MANUAL, "sine", note, False)

    def _apply_c1_autotune_gains(self, new) -> None:
        """把混合自动调参算出的增益写回界面（GUI 线程调用）。"""
        try:
            c1, ang = new["c1"], new["ang"]
            self._c1_position_edits["c1_pos_kp"].setText(hybrid_autotune.fmt([c1["kp"]]))
            self._c1_position_edits["c1_pos_ki"].setText(hybrid_autotune.fmt([c1["ki"]]))
            self._c1_position_edits["c1_pos_i_limit"].setText(
                hybrid_autotune.fmt([c1["itl"]]))
            self._c1_position_edits["c1_pos_kd"].setText(hybrid_autotune.fmt([c1["kd"]]))
            self._c1_position_edits["pos_kp"].setText(hybrid_autotune.fmt([ang["kp"]]))
            self._c1_position_edits["pos_ki"].setText(hybrid_autotune.fmt([ang["ki"]]))
        except (KeyError, AttributeError, TypeError):
            return
        self._refresh_cl_param_cache()

    def _c1_auto_next_round(self) -> bool:
        """混合自动调参一轮结束：读 CSV → 算指标 → 出新增益 → 是否再来一轮。"""
        path = getattr(self, "_sine_log_path", None)
        self._sine_log_close()
        rnd = getattr(self, "_auto_round", 0)
        max_rounds = int(max(1.0, min(6.0, self._c1_fval("c1_auto_rounds", 3.0))))
        rows = []
        try:
            _meta, data = wrist_autotune.read_csv(path) if path else (None, None)
            if data:
                rows = hybrid_autotune.metrics(data, self._hybrid_return_index)
        except (OSError, ValueError):
            rows = []
        if not rows:
            self._ctrl_status("⚠ 混合自动调参：本轮数据读不到（stage 列缺失或太短）→ 结束",
                              log=True)
            return False
        cur = {
            "c1": {"kp": self._c1_fval("c1_pos_kp", 5.0),
                   "ki": self._c1_fval("c1_pos_ki", 0.0),
                   "itl": self._c1_fval("c1_pos_i_limit", 5.0),
                   "kd": self._c1_fval("c1_pos_kd", 0.0)},
            "ang": {"kp": self._c1_fval("pos_kp", 0.2),
                    "ki": self._c1_fval("pos_ki", 0.0)},
        }
        new, notes, conv = hybrid_autotune.tune(
            rows, cur, max_rounds_hit=(rnd + 1 >= max_rounds))
        try:
            self._safety("AUTOTUNE_ROUND", mode="c1_position", round=rnd + 1,
                         max_rounds=max_rounds, converged=int(conv),
                         return_cable=self._hybrid_return_index + 1,
                         c1_kp=new["c1"]["kp"], c1_ki=new["c1"]["ki"],
                         c1_itl=new["c1"]["itl"], c1_kd=new["c1"]["kd"],
                         ang_kp=new["ang"]["kp"], ang_ki=new["ang"]["ki"])
        except Exception:
            pass
        for note in notes:
            self._ctrl_status("🤖 " + note, log=True)
        if conv:
            self._ctrl_status("✅ 混合自动调参收敛（增益变化已小于阈值）", log=True)
            return False
        if rnd + 1 >= max_rounds:
            self._ctrl_status(f"⏹ 混合自动调参用完 {max_rounds} 轮", log=True)
            return False
        self._ui_call(self._apply_c1_autotune_gains, new)
        self._c1_position_state.reset()
        self._c1_angle_state.reset()
        self._auto_t0_pc = None
        self._auto_stage = -1
        self._auto_kind = ""
        self._auto_round = rnd + 1
        # 新一轮要重开记录文件（否则上一轮的 stage 会接在一起，指标串档）
        self._sine_log_open()
        self._ctrl_status(
            f"🔁 混合自动调参进入第 {self._auto_round + 1}/{max_rounds} 轮（增益已更新）",
            log=False)
        return True

    def _cl_tick_c1_position(self, roll: float, pitch: float) -> None:
        params = (self._read_c1_position_params() if self._in_gui_thread()
                  else self._c1_position_params)
        calib = self.wrist_calib
        if params is None or calib is None:
            self._stop_closed_loop("混合模式：专用参数或标定无效")
            return
        # 2026-11-26：混合正弦 / 自动调参只覆盖**目标**（增益在轮末写回界面）
        params, mix_stage, mix_kind, mix_note, mix_done = self._c1_test_override(params)
        if mix_done:
            if self._c1_auto_next_round():
                return
            self._stop_closed_loop(
                f"🧪 混合自动调参完成（{hybrid_autotune.stage_count()} 档 / "
                f"{hybrid_autotune.total_seconds():g}s）—— 数据已保存")
            return
        return_cable = params.return_cable
        return_label = f"C{return_cable + 1}"
        angle_cables = [i for i in range(len(MOTOR_FOR_CABLE)) if i != return_cable]
        base, sample, reason = self._c1_position_feedback(params.c1.max_n, return_cable)
        if reason is not None:
            self._stop_closed_loop(f"混合模式：{reason}")
            return
        model = self._c1_position_geometry(roll, pitch, return_cable)
        if model is None:
            self._stop_closed_loop("混合模式：姿态无效或两根角度绳无法独立控制双轴")
            return

        roll_target, pitch_target = params.roll_target_deg, params.pitch_target_deg
        # 2026-11-26：把本拍**实际下发**的目标交给 GUI（`_update_tables` 60Hz 读它
        # 画目标曲线 + 更新大字）。没有这一行，混控开正弦时屏幕上目标线不动。
        self._c1_cmd_tgt = (roll_target, pitch_target, params.c1.target_n)
        sign = MODEL_AXIS_SIGN[0]
        angles = params.angles
        ff_gains = angles.ff_axis_gains
        ff_active = tuple(on and gain > 0.0 for on, gain in zip(angles.ff_axes, ff_gains))
        outputs, flags = wrist_control_step_pid(
            angles, calib, self._c1_angle_state,
            sign * roll, pitch_model_deg(pitch),
            sign * roll_target, pitch_model_deg(pitch_target), self._cl_dt,
            feedforward=False, base_counts=base, chord_from_fb=any(ff_active))
        if outputs is None:
            self._stop_closed_loop("混合模式：双轴位置指令无效")
            return

        force_time, forces = sample
        force = forces[return_cable]
        tension_output = c1_tension_target(
            params.c1, self._c1_position_state, force_n=force, force_time=force_time,
            length_m=model.s_m[ROLL][return_cable] + model.s_m[PITCH][return_cable],
            counts=base[return_cable], origin=angles.origin[return_cable],
            spool_k=calib.k_counts_per_m[return_cable],
            dt=self._cl_dt)
        if tension_output is None:
            self._stop_closed_loop(f"混合模式：{return_label} 实测位置超出专用行程或张力指令无效")
            return

        targets = list(base)
        targets[return_cable] = tension_output.counts
        pos_limited = False
        for i in angle_cables:
            step = outputs[i] - base[i]
            pos_limited |= abs(step) > angles.max_step
            targets[i] = base[i] + max(-angles.max_step, min(angles.max_step, step))
        outs = {m: target for m, target in zip(MOTOR_FOR_CABLE, targets)
                if m in self._cl_motor_on and target != self.targets.get(m)}
        sent = bool(outs) and self._send_motor_batch(outs)
        if sent:
            self.targets.update(outs)

        now = time.monotonic()
        rel = now - self.t0
        applied = [self.targets.get(m) for m in MOTOR_FOR_CABLE]
        for m, target in zip(MOTOR_FOR_CABLE, applied):
            if target is not None:
                self.channels[f"m{m}_tgt"].buf.append(rel, target)
        force_age_ms = (now - force_time) * 1000.0
        return_fields = (params.c1.target_n, tension_output.pid_counts, tension_output.ff_counts,
                         params.c1.ff_gain, int(tension_output.step_limited),
                         int(tension_output.travel_limited))
        # 旧列继续表示物理 C1，角色相关的通用列另列。
        c1_fields = return_fields if return_cable == 0 else (math.nan,) * len(return_fields)
        shared_ff_gain = ff_gains[0] if ff_gains[0] == ff_gains[1] else math.nan
        self._c1_diag_rows.append((
            rel, roll, pitch, roll_target, pitch_target, forces[0], c1_fields[0],
            *applied, *base, c1_fields[1], c1_fields[2],
            shared_ff_gain, c1_fields[3], flags, c1_fields[4], c1_fields[5],
            int(pos_limited) if return_cable == 0 else math.nan,
            force_age_ms if return_cable == 0 else math.nan, int(bool(sent)), *forces[1:],
            return_cable + 1, force, *return_fields, int(pos_limited), force_age_ms,
            *(int(on) for on in ff_active), *ff_gains))
        # 2026-11-26：勾了「混合正弦 / 混合自动调参」时同步落盘（与张力模式
        # 共用同一个 CSV 写入器；多了末尾三列 roll_tgt_deg/pitch_tgt_deg/c1_tgt_n）。
        if mix_note and getattr(self, "_sine_log_fp", None) is not None:
            force_targets = [math.nan] * len(MOTOR_FOR_CABLE)
            force_targets[return_cable] = params.c1.target_n
            self._sine_log_row(
                roll, pitch, force_targets, forces,
                [float(t - b) if t is not None else 0.0
                 for t, b in zip(targets, base)],
                stage=mix_stage, kind=mix_kind,
                angle_tgt=(roll_target, pitch_target),
                c1_tgt=params.c1.target_n if return_cable == 0 else None)
        if self._cl_beat % 6 == 0:
            notes = []
            if tension_output.travel_limited:
                notes.append(f"{return_label} 行程限幅")
            if tension_output.step_limited:
                notes.append(f"{return_label} 步长限幅")
            if pos_limited:
                notes.append("角度绳步长限幅")
            notes.extend(name for bit, name in CL_FLAG_NAMES if flags & bit)
            suffix = f"  ⚠{'、'.join(notes)}" if notes else ""
            # 2026-11-26：显示当前位姿下 C1 的「预紧份额」与耦合比 —— 决定
            # 这一档 C1 张力能不能加得动而不拽姿态的关键数（见 coupling_ratios）。
            coup_txt = ""
            try:
                _dr, _dp = self.wrist_calib.zero_offset_deg
                _nd = positive_null_direction(
                    math.radians(MODEL_AXIS_SIGN[0] * roll + _dr),
                    math.radians(pitch_model_deg(pitch) + _dp),
                    out_model=model)
                _cp = coupling_ratios(_nd, return_cable) if _nd is not None else None
                if _cp is not None:
                    share, *ratios = _cp
                    detail = "/".join(f"C{i + 1}{gain:+.1f}"
                                      for i, gain in zip(angle_cables, ratios))
                    coup_txt = f"  {return_label}预紧{share:.2f}(+1N→{detail}N)"
                    if share < 0.20:
                        coup_txt += "⚠耦合重"
            except Exception:
                coup_txt = ""
            self._cl_status_set(
                f"混合控制  {return_label} {force:.2f}→{params.c1.target_n:.2f} N  "
                f"ROLL {roll:+.2f}→{roll_target:+.2f}°  "
                f"PITCH {pitch:+.2f}→{pitch_target:+.2f}°{suffix}{coup_txt}{mix_note}")

    def _cl_tick(self) -> None:
        """100Hz：读 J16/J17 -> 控制律（wrist_control_law）-> M27-29。

        控制数学全部在 wrist_control_law.py（无 UI 依赖，可逐行译成 C）。
        输出有变化抑制：目标不变时不重发，稳态零流量。
        P4 端 MotionControl 也是 100Hz，两者同拍。

        **节拍自检（2026-11-24）**：现场发现正弦数据里 `dt` 中位 15~16 ms、
        且有 38% 的相邻行时间戳相同 —— 说明控制线程**一拍要 15.6 ms，
        然后靠"追补"连跑两拍**。追补那两拍用的是**同一个张力样本**，
        等于把 P 作用了两遍（实测 trim 两次不同），等效增益翻倍 + 相位变差。
        这里先量：`tick_ms`（本拍自身耗时）、`hz`（实测节拍率）、`late_ms`。
        """
        now_pc = time.perf_counter()
        prev = getattr(self, "_cl_tick_ts", None)
        self._cl_tick_ts = now_pc
        self._cl_dt = 0.01 if prev is None else min(max(now_pc - prev, 0.001), 0.05)
        self._cl_beat = getattr(self, "_cl_beat", 0) + 1
        if self._cl_beat % 50 == 0:      # ~2Hz 取证快照（张力+目标+模式），出事可回放
            self._safety("CL_TICK")
        # 节拍统计：最近 100 拍的间隔 → 实测 Hz / 抖动 / 追补比例
        try:
            dts = getattr(self, "_cl_dt_hist", None)
            if dts is None:
                dts = self._cl_dt_hist = deque(maxlen=100)
            if prev is not None:
                dts.append(self._cl_dt)
            if self._cl_beat % 100 == 0 and len(dts) >= 20:
                arr = list(dts)
                mean = sum(arr) / len(arr)
                mx = max(arr)
                burst = sum(1 for v in arr if v < 0.002) / len(arr)
                self._cl_hz = 1.0 / mean if mean > 0 else 0.0
                self._safety("CL_RATE", hz=round(1.0 / mean, 2),
                             dt_med=round(sorted(arr)[len(arr) // 2] * 1000.0, 2),
                             dt_max=round(mx * 1000.0, 2),
                             burst_pct=round(burst * 100.0, 1))
        except Exception:
            pass
        t_tick0 = time.perf_counter()
        try:
            self._cl_tick_body()
        finally:
            cost = (time.perf_counter() - t_tick0) * 1000.0
            self._cl_cost_ms = cost
            if self._cl_beat % 100 == 0:
                try:
                    self._safety("CL_COST", ms=round(cost, 2))
                except Exception:
                    pass

    def _cl_tick_body(self) -> None:
        """`_cl_tick` 的实体（把计时外壳与逻辑分开，见上面的节拍自检说明）。"""
        if not self.armed or not self.connected:
            self._stop_closed_loop("连接/使能丢失")
            return
        raw16 = self._enc_filt_raw[16]
        raw17 = self._enc_filt_raw[17]
        if raw16 is None or raw17 is None:
            self._stop_closed_loop("磁编无数据")
            return

        roll = self._angle_delta(self._axis_deg(16, raw16), self.angle_baseline[16])
        pitch = self._angle_delta(self._axis_deg(17, raw17), self.angle_baseline[17])
        if self._cl_mode == "c1_position":
            if self._cl_flag("__record_on", self.cl_record_check):
                self._record_calib_row(roll, pitch)
            self._cl_tick_c1_position(roll, pitch)
            return

        # 参数来自 GUI 侧每 50 ms 拍一次的**快照**（`_refresh_cl_param_cache`）。
        # 2026-11-20：不再在工作线程里读控件（Qt 规定控件只在 GUI 线程碰），
        # 也省掉每拍 13 次「字符串→float」解析。
        prm = self._cl_param_cache
        if prm is None and self._in_gui_thread():
            # 直接调用（测试/单步）时没有 GUI 定时快照 → 当场生成一份
            prm = self._cl_param_cache = self._read_cl_params()
        if prm is None:
            self._stop_closed_loop("参数未就绪（GUI 快照未生成）")
            return
        roll_tgt = self._cl_fval("roll_tgt", 0.0, -90.0, 90.0)    # 目标框即时生效（输入路径）
        pitch_tgt = self._cl_fval("pitch_tgt", 0.0, -90.0, 90.0)
        # 界面 pitch 的可用行程（按 PITCH_MODEL_SIGN 镜像）∩ 限幅：先夹一次，
        # 免得状态行显示"→+30"而实际被模型钳到 +25（所见即所算）。
        _lo_p, _hi_p = pitch_ui_range()
        _lo_p = max(_lo_p, -prm.target_limit_deg)
        _hi_p = min(_hi_p, prm.target_limit_deg)
        pitch_tgt = max(_lo_p, min(_hi_p, pitch_tgt))
        if self._cl_flag("__record_on", self.cl_record_check):
            self._record_calib_row(roll, pitch)

        tens_ev, tens_txt = self._tension_guard(roll, pitch)
        tens_note = ""
        if tens_ev is not None:
            if tens_ev.flags & TENSION_STALE:
                tens_note = "  τ:样本过期"
            else:
                # roll 分量换回 UI 约定（与 τ 目标框/状态行同号），见 `_tau_meas`
                _s_r = self._roll_tau_sign()
                tens_note = (f"  τ={_s_r * tens_ev.tau_roll_nm:+.3f}/"
                             f"{tens_ev.tau_pitch_nm:+.3f}N·m"
                             + (f" {tens_txt}" if tens_txt else "")
                             + ("  ⚠松绳" if tens_ev.flags & TENSION_SLACK else ""))
            if tens_ev.flags & TENSION_OVERLOAD:
                return
        elif tens_txt:
            tens_note = f"  {tens_txt}"   # 阈值非法守卫未启用：显式示警，不再静默

        if self._cl_mode == "impedance":
            self._cl_tick_impedance(roll, pitch)        # 阻抗外环 → 力矩内环
            return
        if self._cl_mode == "force":
            self._cl_tick_force(roll, pitch)            # 力矩模式分支
            return
        if self._cl_mode == "tension":
            self._cl_tick_tension(roll, pitch)          # 张力模式分支
            return
        if self._cl_mode == "tight":
            self._cl_tick_tight(roll, pitch)            # 张紧模式分支
            return

        if self.wrist_calib is None:
            self._stop_closed_loop("位置模式：缺少 k/R 换算参数（标定对象被清空）")
            return
        # 位置环结构（2026-11-23）：**可开关的绳长前馈 + PI，目标每拍限幅**。
        #   ① 前馈：k·[l(θ*) − l(θ_now)]（`chord_from_fb`，当前**关闭**，用户在调 PID）
        #   ② PI  ：J·δθ（δθ = kp·e + ki∫e + kd·…），关节角域
        #   ③ 目标：(1)+(2) 算出的"本拍应走多少"，叠加到**本拍实测**上
        #   ④ 限幅：每拍步长最多 ±max_step_f
        # 调完 PID 想恢复前馈：把下面 chord_from_fb 改回 True。
        base = [self._motor_pos_now(m) for m in SERVO_TARGETS]
        # UI/硬件角 → 模型角（2026-11-19）：location 环 roll 方向与模型相反，
        # 统一在这里换算，law 仍是纯模型函数（见 wrist_control_law.MODEL_AXIS_SIGN）。
        s_r = MODEL_AXIS_SIGN[0]
        outputs, flags = wrist_control_step_pid(
            prm, self.wrist_calib, self._pos_pid_state,
            s_r * roll, pitch_model_deg(pitch),
            s_r * roll_tgt, pitch_model_deg(pitch_tgt),
            self._cl_dt,
            feedforward=False,
            base_counts=base,
            chord_from_fb=self._cl_flag("__ff_on", self.cl_ff_check),  # 前馈总开关
            roll_enabled=self._cl_flag("__roll_on", self.cl_roll_check),
            pitch_enabled=self._cl_flag("__pitch_on", self.cl_pitch_check))
        max_step = max(1, int(round(prm.max_step)))
        if outputs is not None:
            now_rel = self._latest_t if self._latest_t is not None else 0.0
            # **限幅加在“本拍走多少”上**（2026-11-23 现场：实测不动时目标一直
            # 累加）。step = out − 本拍实测，clamp 到 ±max_step 后再加回实测：
            #   · 实测不动 → step 恒定 → 目标恒定（不再每拍 +max_step 累加）；
            #   · 实测在走 → 目标跟着实测走，每拍最多领先 max_step。
            raw = {}
            for i, (m, out) in enumerate(zip(SERVO_TARGETS, outputs)):
                if m not in self._cl_motor_on:      # 未勾选的缆不推曲线/不下发
                    continue
                step = max(-max_step, min(max_step, out - base[i]))
                raw[m] = base[i] + step
            # 变更抑制 + 逐绳开关（绝对目标的斜率限幅已在上面按步长做过）
            outs = self._clamp_per_tick(raw)
            if self._send_motor_batch(outs):
                for m, out in outs.items():
                    self.targets[m] = out
            # 曲线记**实际下发**的目标（限幅后），与力控模式的 m_tgt 口径一致。
            # 以前记的是律的原始绝对目标：限幅生效时曲线会"跳一下就不动"，
            # 跟真正下发的阶梯对不上（2026-11-23 修）。
            for m in self._cl_motor_on:
                v = self.targets.get(m)
                if v is not None:
                    self.channels[f"m{m}_tgt"].buf.append(now_rel, float(v))
            # 2 Hz 取证：下发目标 vs 实测 vs 角度。位置模式"跑一下不动"时，
            # 看这三个量谁不动就能定位（目标没变=进死区/被限幅；实测没跟=
            # 舵机/固件没执行；角度没变=绳松/几何）。
            if self._cl_beat % 50 == 0:
                self._safety("POS_TICK",
                             tgt={m: self.targets.get(m) for m in SERVO_TARGETS},
                             meas={m: self._motor_pos_now(m) for m in SERVO_TARGETS},
                             ang=(round(roll, 2), round(pitch, 2)),
                             tgt_ang=(round(roll_tgt, 2), round(pitch_tgt, 2)),
                             flags=int(flags))
            # 位置模式诊断（20 Hz）：给「🔬 诊断 CSV」用，调 PID 时看响应
            if getattr(self, "_cl_tick_count", 0) % 5 == 0:
                self._pos_diag_rows.append((
                    now_rel, roll, pitch, roll_tgt, pitch_tgt,
                    self.targets.get(27), self.targets.get(28), self.targets.get(29),
                    self._motor_pos_now(27), self._motor_pos_now(28),
                    self._motor_pos_now(29)))
        # outputs=None（非有限/几何无效/基准缺失）：保持上一目标不发送，本拍跳过
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        if self._cl_tick_count % 6 == 0:
            warns = "".join(name for bit, name in CL_FLAG_NAMES if flags & bit)
            state = ("保持(硬错误)" if outputs is None
                     else "跟踪中" + (f" ⚠{warns}" if warns else ""))
            r_on = self._cl_flag("__roll_on", self.cl_roll_check)
            p_on = self._cl_flag("__pitch_on", self.cl_pitch_check)
            both = r_on and p_on
            only = ("" if both else
                    (" [仅ROLL环]" if r_on else
                     (" [仅PITCH环]" if p_on else " [两轴均关：不动]")))
            self._cl_status_set(
                f"{self._pos_loop_name()} {state}  "
                f"ROLL {roll:+6.2f}→{roll_tgt:+6.2f}°  "
                f"PITCH {pitch:+6.2f}→{pitch_tgt:+6.2f}°{only}{tens_note}")
        return

    def _save_wrist_zero(self) -> None:
        motors = {}
        for m in SERVO_TARGETS:
            v = self.channels[f"m{m}_abs"].buf.last()
            if math.isnan(v):
                self._ctrl_status("存储零位失败：M27-29 尚无位置数据")
                return
            motors[str(m)] = int(v)
        encs = {}
        for j in (16, 17):
            v = self.channels[f"enc_raw_{j}"].buf.last()
            if math.isnan(v):
                self._ctrl_status("存储零位失败：J16/J17 尚无数据")
                return
            encs[str(j)] = int(v)
        ok = save_named_json("wrist_zero.json", {
            "motors": motors,
            "encoders": encs,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if ok:
            self._ctrl_status(f"💾 零位已存储 M={motors} J16/J17={encs['16']}/{encs['17']}")
        else:
            self._ctrl_status("存储零位失败：文件写入被拒")

    # ---------- 绳一键操作（PLAN v8.2/v8.3） ----------

    RELEASE_STEPS = 5          # 2500 counts 拆 5 步，每步 500c
    RELEASE_STEP_MS = 200

    def _release_gate_reason(self):
        """一键松绳门禁（纯读，供按钮与拒绝弹窗 1Hz 复查共用）。

        覆盖：使能/连接 / 非闭环 / 无在途计划 / trim_sign 合法 / ≥1 绳勾选 /
        P4 活动域 / 勾选在缆序映射内。不做张力检测（2026-11-03 定案：
        张力保护只在闭环里）。"""
        if not self.armed or not self.connected:
            return "一键松绳：未使能/未连接"
        if self.cl_enabled:
            return "一键松绳：闭环运行中，先停止闭环"
        if getattr(self, "_release_plan", None):
            return "一键松绳：上一次松绳还在执行，等它结束"
        sign = self._force_trim_sign()
        deltas = release_delta(sign) if sign else None
        if deltas is None:
            return "一键松绳：trim方向非法（需 3 个 ±1）"
        motors = [m for m in SERVO_TARGETS if self._motor_enabled(m)]
        if not motors:
            return "一键松绳：未勾选任何绳"
        # 松绳走 0xD3 批量帧 → 同样受固件活动域收窄；缺电机时先补活动域
        missing = self._scope_missing(motors)
        if missing:
            return (f"⛔ 一键松绳：P4 活动域不含 {self._motor_list_text(missing)}"
                    f"——先停止并重新「使能直控」重建活动域后再松绳")
        if not any(m in MOTOR_FOR_CABLE for m in motors):
            return "一键松绳：勾选的绳都不在 M27-29 映射内"
        return None

    def _on_release_rope(self) -> None:
        """一键松绳：按 trim_sign 方向**分步**放绳（5 步 × 500c，共 2500c）。

        2026-11-03 用户定案：**松绳不做张力检测**（张力保护只在闭环里）。
        保留的仍是"分步下发"本身——它解决的是多电机连发被固件代际合并
        （只有一台动），不是张力保护。
        """
        reason = self._release_gate_reason()
        if reason:
            self._reject("🪢 一键松绳", reason,
                         recheck=self._release_gate_reason)
            return
        sign = self._force_trim_sign()
        deltas = release_delta(sign)
        motors = [m for m in SERVO_TARGETS if self._motor_enabled(m)]
        items = []
        skipped = []
        for i, m in enumerate(MOTOR_FOR_CABLE):
            if m not in motors:
                skipped.append(m)
                continue
            t = self.targets.get(m)
            baseline = t if t is not None else self._motor_pos_now(m)
            if t is None:
                # REVIEW P1-5：_send_motor_target 的 ramp 起点取 targets；
                # 不落 baseline 会从 origin 起跳——先写回实际位置。
                self.targets[m] = baseline
            items.append({
                "motor": m,
                "delta": int(deltas[i]),
                "moved": 0,
            })
        # 松绳前先取消这些电机的在途斜坡：否则 _on_ramp_tick 会继续朝旧目标走，
        # 把松绳目标顶回去（"点了松绳只有一根动"的常见原因之一）。
        for item in items:
            self._ramp_state.pop(item["motor"], None)
        if not self._ramp_state and self._ramp_timer.isActive():
            self._ramp_timer.stop()
        per_step = max(1, RELEASE_COUNTS // self.RELEASE_STEPS)
        self._release_plan = {
            "items": items,
            "per_step": per_step,
            "left": self.RELEASE_STEPS,
            "skipped": skipped,
            "sign": list(sign) if sign else None,
        }
        note = "" if not skipped else f"（未勾选跳过 {self._motor_list_text(skipped)}）"
        self._ctrl_status(
            f"🪢 一键松绳：M={[it['motor'] for it in items]}{note} 分 "
            f"{self.RELEASE_STEPS} 步 × {per_step}c（每台共 {per_step * self.RELEASE_STEPS}c）")
        self._safety("RELEASE_START", motors=[it["motor"] for it in items],
                     per_step=per_step, total=per_step * self.RELEASE_STEPS,
                     sign=sign, skipped=skipped)
        self._release_step()

    def _release_step(self, expected_plan=None) -> None:
        """执行一步松绳（一帧 0xD3 批量；不看张力）。"""
        plan = getattr(self, "_release_plan", None)
        if not plan or (expected_plan is not None and plan is not expected_plan):
            return
        outs = {}
        for item in plan["items"]:
            m = item["motor"]
            step = plan["per_step"] * (1 if item["delta"] >= 0 else -1)
            cur = self.targets.get(m)
            if cur is None:
                # 急停会清空 targets：此时继续放没有基准，直接中止免得猜
                self._release_plan = None
                self._ctrl_status(f"⛔ 一键松绳中止：M{m} 没有指令基准（刚急停过？先重新使能）")
                self._safety("RELEASE_ABORT", reason="no_baseline", motor=m)
                return
            outs[m] = int(max(-30000, min(30000, cur + step)))
            item["_next_step"] = step
        if not self._send_direct_targets(outs, "RELEASE_STEP"):
            self._release_plan = None
            self._ctrl_status("⛔ 一键松绳中止：批量下发失败（无 ABS 快照/串口积压）")
            return
        for item in plan["items"]:
            item["moved"] += item.pop("_next_step", 0)

        plan["left"] -= 1
        self._safety("RELEASE_STEP", left=plan["left"],
                     moved={it["motor"]: it["moved"] for it in plan["items"]})
        if plan["left"] <= 0:
            self._release_plan = None
            moved = {it["motor"]: it["moved"] for it in plan["items"]}
            self._ctrl_status(f"✅ 一键松绳完成：{moved}")
            self._safety("RELEASE_DONE", moved=moved)
            return
        QTimer.singleShot(self.RELEASE_STEP_MS, lambda: self._release_step(plan))

    def _tighten_gate_check(self):
        """一键紧绳门禁十三查（纯读，供按钮与拒绝弹窗 1Hz 复查共用）。

        返回 (reason|None, ctx)：通过时 ctx 携带事务所需值（t_use/t_tgt/
        n̂/f 界），handler 直接复用不重算；拒绝时 ctx 为空 dict。"""
        ctx = {}
        if not self.armed or not self.connected:
            return "一键紧绳：未使能/未连接", ctx
        if self.cl_enabled:
            return "一键紧绳：闭环运行中，先停止闭环", ctx
        last = self._tension_last
        if last is None or time.monotonic() - last[0] > 0.5:
            return "一键紧绳：无新鲜张力数据（先连观测台张力串口）", ctx
        # REVIEW P1-1：当前已过载/NaN 直接拒——否则事务成功后第一拍守卫停环，
        # 模式/参数已被改（成功即会话开始不回滚），留下脏状态。
        _fmn, _fmx, _ok = self._effective_flimits()
        if not _ok or any(not math.isfinite(v) or v > _fmx for v in last[1]):
            return "一键紧绳：当前张力已过载/非法，先松绳再恢复", ctx
        unchecked = [m for m in SERVO_TARGETS if not self._motor_enabled(m)]
        if unchecked:
            return f"一键紧绳：需三缆全勾选（M{unchecked} 未勾）", ctx
        pose = self._wrist_pose_now()
        if pose is None:
            return "一键紧绳：无位姿（J16/J17 未归零或无数据）", ctx
        geo = self._force_geo(pose[0], pose[1])
        if geo is None:
            return "一键紧绳：该位姿 R(q) 无效", ctx
        out_model, nd = geo
        if nd is None or any(v <= 0.0 for v in nd):
            return "一键紧绳：该位姿无全正 n̂（张紧不可定义）", ctx
        if not out_model.angle_in_range:
            return "一键紧绳：位姿超出模型行程，先回中", ctx
        fmin_eff, fmax_eff, ok = self._effective_flimits()
        if not ok:
            return "一键紧绳：阈值非法（需 fmin<fmax）", ctx
        t_min_req = fmin_eff / min(nd)
        t_max_allow = fmax_eff / max(nd)
        # 2026-11-18 合并：t* 与力矩 preload 同一个量，统一读「预紧N」
        t_tgt_raw = self._cl_fval("preload", 5.0, 0.0, 200.0)
        if not (t_min_req <= t_tgt_raw <= t_max_allow):
            return (f"一键紧绳：t={t_tgt_raw:g}N 不在当前位姿可行域 "
                    f"[{t_min_req:.2f},{t_max_allow:.2f}]N"), ctx
        t_use, reason = tighten_t_use(
            t_tgt_raw,
            self._cl_fval("t_min", 0.0, 0.0, 200.0),
            self._cl_fval("t_max", 0.0, 0.0, 200.0),
            t_min_req, t_max_allow)
        if t_use is None:
            return f"一键紧绳：{reason}", ctx
        # 启动前按**真实位姿**校验力控参数（trim 方向/限幅/增益）。
        # 旧实现只靠 _start_closed_loop 里 (0°,0°) 的快检：极端位姿下会
        # "事务成功 → 第一拍就停环"，用户看到的是刚说恢复中又停了。
        if self._force_params_v2(pose[0], pose[1]) is None:
            return ("一键紧绳：力控参数非法（trim方向需 3 个 ±1，或 R(q) 无效）",
                    ctx)
        ctx.update(t_use=t_use, t_tgt=t_tgt_raw, nd=nd,
                   fmin=fmin_eff, fmax=fmax_eff)
        return None, ctx

    def _on_tighten_rope(self) -> None:
        """一键紧绳（事务化，D3）：TDA 恢复三缆到标准分布 t·n̂。

        门禁十三查 → 备份 → 切力矩模式/τd=0/preload=t_use → 启动 →
        成功才置 _force_recovery；任一步失败恢复备份全回滚。"""
        reason, ctx = self._tighten_gate_check()
        if reason:
            self._reject("🪢 一键紧绳", reason,
                         recheck=lambda: self._tighten_gate_check()[0])
            return
        t_use = ctx["t_use"]

        # ---- 事务执行：备份 → 切换 → 启动 → 成功置 flag / 失败回滚 ----
        backup = (self._cl_mode,
                  self.cl_edits["tau_roll"].text(),
                  self.cl_edits["tau_pitch"].text(),
                  self.cl_edits["preload"].text())
        try:
            self.cl_mode_combo.blockSignals(True)
            self.cl_mode_combo.setCurrentIndex(self.cl_mode_combo.findData("force"))
            self.cl_mode_combo.blockSignals(False)
            self._cl_mode = "force"
            self._apply_cl_mode_visibility()
            self.cl_edits["tau_roll"].setText("0.0")
            self.cl_edits["tau_pitch"].setText("0.0")
            self.cl_edits["preload"].setText(f"{t_use:g}")
            self._force_recovery = False
            self._start_closed_loop()
            if not self.cl_enabled:
                raise RuntimeError("启动失败（见状态行原因）")
            self._force_recovery = True
            self._tighten_cl_active = True   # 会话旗标：故障停环要弹窗告知
            self._recovery_ok_since = None   # REVIEW P0-3：新一轮从零计时
            self._ctrl_status(
                f"🪢 一键紧绳：恢复中（t={t_use:g}N，TDA 分布，腕将沉降找平衡；"
                f"全缆进界 300ms 后自动转正常）")
            self._safety("TIGHTEN_OK", t=t_use, t_target=ctx["t_tgt"],
                         fmin=ctx["fmin"], fmax=ctx["fmax"], nd=list(ctx["nd"]))
        except Exception as exc:   # REVIEW P1-2：事务层宽捕获，任何异常都回滚
            # 2026-11-03 BUG：若 _start_closed_loop 已经真正启动（cl_enabled=True、
            # 100Hz 定时器已在跑）之后才抛异常，旧实现只还原模式/三个参数框，
            # 闭环仍在按 t_use 持续下发——状态行却写着"失败已回滚"。
            # 先停环，再还原 UI（_stop_closed_loop 自身会把 _force_recovery 清掉）。
            if self.cl_enabled:
                self._stop_closed_loop("一键紧绳失败回滚", popup=False)   # 回滚有自己的弹窗
            m, tr, tp, pl = backup
            self.cl_mode_combo.blockSignals(True)
            self.cl_mode_combo.setCurrentIndex(self.cl_mode_combo.findData(m))
            self.cl_mode_combo.blockSignals(False)
            self._cl_mode = m
            self._apply_cl_mode_visibility()
            self.cl_edits["tau_roll"].setText(tr)
            self.cl_edits["tau_pitch"].setText(tp)
            self.cl_edits["preload"].setText(pl)
            self._force_recovery = False
            self._recovery_ok_since = None
            self._reject("🪢 一键紧绳", f"🪢 一键紧绳失败已回滚：{exc}")
            self._safety("TIGHTEN_ROLLBACK", error=str(exc))

    def _goto_wrist_zero(self) -> None:
        if self.cl_enabled:
            self._reject("回零", "闭环运行中：先停止闭环再回零",
                         recheck=lambda: ("闭环运行中：先停止闭环再回零"
                                          if self.cl_enabled else None))
            return
        data = load_named_json("wrist_zero.json")
        if not data or "motors" not in data:
            def _zero_missing():   # REVIEW Minor#9：与 handler 同条件（非仅真值）
                d = load_named_json("wrist_zero.json")
                return None if (d and "motors" in d) else "尚无存储的零位"
            self._reject("回零", "尚无存储的零位（先点「存储零位」）",
                         recheck=_zero_missing)
            return
        if not self.armed:
            self._pending_target = None
            self._ctrl_status("回零：先自动使能…")
            self._want_goto_zero = True
            self._on_enable_direct()
            return
        self._do_goto_zero(data)

    def _do_goto_zero(self, data) -> None:
        outs = {}
        clamped = []
        for m in SERVO_TARGETS:
            if not self._motor_enabled(m):
                continue
            tgt = int(data["motors"].get(str(m), self._soft_limit_base(m)))
            # 2026-11-03 BUG：clamped 列表从来没被填过 → 状态行的"超软限位已钳制"
            # 永远不会出现，实际却把存档值原样下发（存档过期/手改 JSON 时会远行）。
            lim = self._clamp_to_soft_limit(m, tgt)
            if lim != tgt:
                clamped.append(m)
            outs[m] = lim
        # 一次批量下发：逐帧 0xDE 会被固件按代际合并，只有最后一台真正执行
        if not self._send_direct_targets(outs, "GOTO_ZERO"):
            self._ctrl_status("⛔ 回零中止：批量下发失败（无 ABS 快照/串口积压）")
            return
        off = [m for m in SERVO_TARGETS if not self._motor_enabled(m)]
        note = f"🎯 回零中（{data.get('saved_at', '')}）" + (
            f" 注意: {self._motor_list_text(clamped)} 超软限位已钳制" if clamped else "")
        if off:
            note += f"；未勾选 {self._motor_list_text(off)} 不回零"
        self._ctrl_status(note)

    def _on_stop(self) -> None:
        """急停：**先**抢占式下发 STOP，再做记账。

        2026-11-03 事故复盘发现：旧顺序先 _stop_closed_loop（可能同步写标定
        CSV）再 send(STOP)，而 STOP 与普通运动指令共用 FIFO，最坏要等约 300ms。
        现在顺序改为：清空待发运动帧 → 抢占通道发 STOP → 再停表/记账。
        """
        dropped = 0
        stop_in_fifo = False
        if self.connected and self.rx_thread is not None:
            drop = getattr(self.rx_thread, "drop_pending_tx", None)
            if callable(drop):
                dropped = drop()
            try:
                self.rx_thread.send(build_stop_cmd(), priority=True)
            except TypeError:
                # 兼容不支持 priority 的旧实现/测试替身；急停路径绝不允许抛异常
                self.rx_thread.send(build_stop_cmd())
                stop_in_fifo = True
        self._cancel_direct_motion("急停", discard_tx=not stop_in_fifo)
        self.estop_latched = True
        self._set_arm_light()
        self._safety("ESTOP", dropped_tx=dropped)
        self._ctrl_status(
            f"⛔ 已发送 STOP（抢占下发，丢弃 {dropped} 帧待发指令）："
            f"固件关闭舵机力矩，腕部会松开/下垂")

    def _toggle_servo_info_window(self) -> None:
        """打开/关闭舵机信息窗（2026-11-20）。"""
        win = getattr(self, "servo_info_window", None)
        if win is not None and win.isVisible():
            win.close()
            return
        self.servo_info_window = ServoInfoWindow(self)
        self.servo_info_window.show()
        self.servo_info_window.request_range()   # 顺手请求一次逻辑行程

    def _toggle_watch_window(self) -> None:
        if self.watch_window is not None and self.watch_window.isVisible():
            # 收口到 closeEvent：停表/清引用/销毁都在那里做（X 关闭同一条路）
            self.watch_window.close()
            return
        self.watch_window = ParameterWatchWindow(self)
        saved = getattr(self, "_saved_watch_params", None)
        if saved:
            for k in saved:
                self.watch_window.add_param(k)
        else:
            for k in ("roll_cur", "roll_tgt", "roll_err",
                      "pitch_cur", "pitch_tgt", "pitch_err",
                      "m27_off", "m28_off", "m29_off"):
                self.watch_window.add_param(k)
        self.watch_window.show()
        self._apply_run_prio()   # 闭环运行中打开 → 直接按当前档位起（勾了运行优先就是 30Hz）

    # ---------- 主题 ----------
    def _on_theme_selected(self, index: int) -> None:
        names = list(AT.DISPLAY_NAMES)
        name = names[index] if 0 <= index < len(names) else "night"
        if name == "custom":
            dlg = CustomThemeDialog(self, getattr(self, "_custom_theme", None))
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._sync_theme_combo()   # 取消：下拉回退到当前生效主题
                return
            self._custom_theme = dlg.overrides
            AT.set_theme("custom", self._custom_theme)
        else:
            AT.set_theme(name)
        self._apply_theme()
        self._save_layout()

    def _sync_theme_combo(self) -> None:
        names = list(AT.DISPLAY_NAMES)
        idx = names.index(AT.current_name()) if AT.current_name() in names else 0
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)

    def _style_legend(self) -> None:
        """图例：半透明底 + 小字号（2026-11-24）。

        原来图例是默认的"实底框"，压在曲线区左上角整块挡住波形；改成主题色
        半透明底（约 70% 不透明）+ 8pt 字，既认得出、又不挡数据。
        """
        lg = getattr(self, "legend", None)
        if lg is None:
            return
        try:
            bg = pg.mkColor(AT.T("panel"))
            bg.setAlpha(180)
            lg.setBrush(pg.mkBrush(bg))
            line = pg.mkColor(AT.T("panel_line"))
            line.setAlpha(140)
            lg.setPen(pg.mkPen(line))
            lg.setLabelTextSize("8pt")
        except Exception:      # 老版本 pyqtgraph 没有这些方法时保持默认
            pass

    def _apply_theme(self) -> None:
        """全局 QSS + 曲线区背景/轴色 + 曲线色板互换 + 观测台样式即时重建；
        动态着色路径读 AT.T 自动跟随。曲线色仅互换默认色板内的，用户自定不动。"""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(AT.build_app_qss())
        pg.setConfigOptions(background=AT.T("plot_bg"), foreground=AT.T("plot_fg"))
        if getattr(self, "plot", None) is not None:
            self.plot.setBackground(AT.T("plot_bg"))
            fg_pen = pg.mkPen(AT.T("plot_fg"))
            for name in ("left", "bottom"):
                ax = self.plot.getAxis(name)
                ax.setPen(fg_pen)
                ax.setTextPen(fg_pen)
            self._style_legend()      # 图例底色跟主题走
        if AT.curve_palette() is AT.CURVE_LIGHT:
            swap = dict(zip(AT.CURVE_DARK, AT.CURVE_LIGHT))
        else:
            swap = dict(zip(AT.CURVE_LIGHT, AT.CURVE_DARK))
        for ch in self.channels.values():
            if ch.color in swap:
                ch.color = swap[ch.color]
        if self.rt_window is not None:
            self.rt_window.setStyleSheet(AT.build_dashboard_qss())
            # 走势线颜色随主题重设（Sparkline 构造时定色，切主题后需更新）
            for i, card in enumerate(getattr(self.rt_window, "cards", ())):
                card.spark._color = CHC(i)
                card.spark.update()
        # REVIEW Minor#4：拒绝弹窗样式是构造时烘焙的，切主题要跟着刷
        dlg = getattr(self, "_reject_dlg", None)
        if dlg is not None:
            dlg._apply_theme()

    def _toggle_rt_window(self) -> None:
        if self.rt_window is not None and self.rt_window.isVisible():
            # 收口到 closeEvent：停表/清引用/销毁都在那里做（X 关闭同一条路）
            self.rt_window.close()
            return
        self.rt_window = RTensionWindow(self)
        self.rt_window.show()
        self._apply_run_prio()   # 闭环运行中打开 → 直接按当前档位起（勾了运行优先就是 30Hz）

    def _run_prio(self) -> bool:
        """运行优先生效中=闭环运行 ∧ 勾选（GUI 降档让路控制环）。"""
        chk = getattr(self, "runprio_check", None)
        return bool(self.cl_enabled and chk is not None and chk.isChecked())

    def _apply_run_prio(self) -> None:
        """把「🔒运行优先」落到各 GUI 定时器（60Hz ↔ 30Hz 一档切换）。

        默认不勾（全 60Hz）；勾上后闭环运行期间整体降到 30Hz，把 GUI 线程
        余量让给 100Hz 控制环，停环自动恢复 60Hz。
        数据链不受影响（缓冲/CSV/守卫全量照旧，只降显示刷新率）。
        """
        prio = self._run_prio()
        table_ms = 33 if prio else 16     # 30Hz / 60Hz
        win_ms = 33 if prio else 16       # 30Hz / 60Hz
        timer = getattr(self, "table_timer", None)
        if timer is not None:
            timer.setInterval(table_ms)
        for w in (getattr(self, "rt_window", None),
                  getattr(self, "watch_window", None)):
            t = getattr(w, "_timer", None)
            if t is not None:
                t.setInterval(win_ms)
        self._plot_gate = 0

    def _toggle_pause(self) -> None:
        self.plot_frozen = not self.plot_frozen
        self.pause_btn.setText("恢复曲线" if self.plot_frozen else "暂停曲线")
        self.paused_text.setVisible(self.plot_frozen)

    def _clear_buffers(self) -> None:
        """「清空」：清曲线数据 + 清双击加的标记线（2026-11-24 用户定案）。"""
        for ch in self.channels.values():
            ch.buf.clear()
        self._clear_h_markers()
        self._update_plot()

    # ---------- 表格 ----------
    def _encoder_filter_update(self, j: int, raw: float) -> None:
        """中值5 + EMA + 过圈解绕（实现见 wrist_filter，可移植模块）。

        先把 raw 在 counts 域解绕到上一滤波值所在圈，跨 0/16383 绕回点时
        滤波输出与下游角度差全程连续。角度消费端用 _enc_filt_raw——解绕后
        数值可能暂时超出 0..16383，_axis_deg/_angle_delta 的 mod 折回是正确
        的；raw 曲线/表格用通道原值，不受影响。"""
        if math.isfinite(raw):
            prev = self._enc_filt_raw.get(j)
            if prev is not None:
                raw = unwrap_counts(raw, prev)
        self._enc_filt_raw[j] = self._axis_filter[j].update(raw)

    @staticmethod
    def _enc_deg(raw: float) -> float:
        """14bit 磁编：一圈 360° = 16384 counts（1 count = 0.022°）。"""
        return ((raw / 16384.0 * 360.0) + 180.0) % 360.0 - 180.0

    @staticmethod
    def _axis_deg(j: int, raw: float) -> float:
        """腕部轴角：应用 J16/J17 方向符号（显示/闭环统一约定）。"""
        return ((raw / 16384.0 * 360.0 + 180.0) % 360.0 - 180.0) * AXIS_SIGN.get(j, 1.0)

    @staticmethod
    def _angle_delta(cur: float, base: float) -> float:
        """最短角差（±180° 内），避免跨绕回点时 Δ 跳变。"""
        return (cur - base + 180.0) % 360.0 - 180.0

    def _update_tables(self) -> None:
        self._table_frames = getattr(self, "_table_frames", 0) + 1
        enc_online = self.status_info.get("encoder_online", 0)
        grey = QColor(AT.T("muted"))
        white = QColor(AT.T("text"))
        good = QColor(AT.T("good"))
        bad = QColor(AT.T("bad"))
        # 差分刷新：只有文本/颜色真的变了才碰 item，避免每拍触发整表重绘。
        cache = getattr(self, "_enc_cell_cache", None)
        if cache is None:
            cache = self._enc_cell_cache = {}
        for j in range(ENCODER_COUNT):
            online = bool(enc_online >> j & 1)
            raw = self.channels[f"enc_raw_{j}"].buf.last()
            raw_txt = "-" if math.isnan(raw) else f"{raw:.0f}"
            if cache.get((j, 1)) != raw_txt:
                cache[(j, 1)] = raw_txt
                self.enc_table.item(j, 1).setText(raw_txt)
            disp_raw = self._enc_filt_raw.get(j) if j in (16, 17) else raw
            if disp_raw is None:
                disp_raw = raw
            deg_txt = "-" if math.isnan(raw) else f"{self._axis_deg(j, disp_raw):+.2f}"
            if cache.get((j, 2)) != deg_txt:
                cache[(j, 2)] = deg_txt
                self.enc_table.item(j, 2).setText(deg_txt)
            if cache.get((j, 3)) != online:
                cache[(j, 3)] = online
                self.enc_table.item(j, 3).setText("● 在线" if online else "○ 离线")
                self.enc_table.item(j, 3).setForeground(good if online else bad)
            if cache.get((j, "fg")) != online:
                cache[(j, "fg")] = online
                fg = white if online else grey
                for c in range(4):
                    self.enc_table.item(j, c).setForeground(fg)
        # 张力链路状态 ~1Hz 刷新（60Hz 表格定时器里每 60 帧一次）
        self._tension_ui_count = getattr(self, "_tension_ui_count", 0) + 1
        if (self._tension_sensor is not None
                and self._tension_ui_count % 30 == 0):
            self._tension_status_refresh()
        self._refresh_table_visibility()

    def _refresh_table_visibility(self) -> None:
        if not hasattr(self, "enc_table"):
            return
        enc_online = self.status_info.get("encoder_online", 0)
        only_online = self.only_online_check.isChecked() if hasattr(self, "only_online_check") else True
        hide_cache = getattr(self, "_rowhide_cache", None)
        if hide_cache is None:
            hide_cache = self._rowhide_cache = {}
        for j in range(ENCODER_COUNT):
            hide = only_online and not (enc_online >> j & 1)
            if hide_cache.get(j) != hide:
                hide_cache[j] = hide
                self.enc_table.setRowHidden(j, hide)
        for m in SERVO_TARGETS:
            self._update_motor_info(m)

        if hasattr(self, "cl_roll_now") and hasattr(self, "cl_pitch_now"):
            pose = self._wrist_pose_now()
            if self._cl_mode == "c1_position":
                try:
                    r_tgt, p_tgt = self._c1_position_targets(pose or (0.0, 0.0))
                except ValueError:
                    r_tgt = p_tgt = math.nan
            else:
                r_tgt = self._cl_fval("roll_tgt", 0.0, -999.0, 999.0)
                p_tgt = self._cl_fval("pitch_tgt", 0.0, -999.0, 999.0)
            # 2026-11-26：混合模式**运行中**要用它实际下发的目标（正弦/阶跃），
            # 不能用界面框里的基值 —— 否则「混合正弦」开着时屏幕上的目标线
            # 一动不动，看上去像"正弦没生效"（内部目标其实一直在变，
            # CSV 的 `c1_tgt_n` / `roll_tgt_deg` 列可以证明）。
            _cmd = getattr(self, "_c1_cmd_tgt", None)
            if (self._cl_mode == "c1_position" and self.cl_enabled
                    and _cmd is not None):
                r_tgt, p_tgt = _cmd[0], _cmd[1]
            if pose is not None:
                # 位置模式只显示角度：目标角 vs 当前角。
                # （不再换算/显示"目标编码器值"：那是 raw 口径，pitch 的
                #  AXIS_SIGN[17]=-1 与 roll 不同，写在这里容易看错，见 2026-11-23。）
                self.cl_roll_now.setText(
                    f"ROLL  {pose[0]:+6.2f}°→{r_tgt:+6.2f}°")
                self.cl_pitch_now.setText(
                    f"PITCH {pose[1]:+6.2f}°→{p_tgt:+6.2f}°")
            # 位姿曲线：当前角 + 目标角（位置环调参用，和 POS_TICK/诊断 CSV 对齐）
            rel = self._latest_t
            if pose is not None and rel is not None:
                self.channels["pose_roll"].buf.append(rel, pose[0])
                self.channels["pose_pitch"].buf.append(rel, pose[1])
                self.channels["pose_roll_tgt"].buf.append(rel, r_tgt)
                self.channels["pose_pitch_tgt"].buf.append(rel, p_tgt)
                # 2026-11-26：混合模式还要把 **C1 张力目标** 推上曲线。
                # 张力/力控模式由 `_force_tick_apply` 里的 `_push_tension_tgt_curves`
                # 负责；混合模式不走那条链，所以原来 `tension_f1_tgt` 从来没被写过
                # （实测计数恒为 0）。
                if (self._cl_mode == "c1_position" and self.cl_enabled
                        and _cmd is not None):
                    ch = self.channels.get(f"tension_f{self._hybrid_return_index + 1}_tgt")
                    if ch is not None and math.isfinite(_cmd[2]):
                        ch.buf.append(rel, float(_cmd[2]))
        roll_raw = self._enc_filt_raw[16]
        pitch_raw = self._enc_filt_raw[17]
        for axis, j, big, detail in (
                ("ROLL", 16, self.roll_label, self.roll_detail),
                ("PITCH", 17, self.pitch_label, self.pitch_detail)):
            raw = roll_raw if j == 16 else pitch_raw
            base = self.angle_baseline[j]
            if raw is None or math.isnan(raw):
                big.setText(f"{axis}   --.-°")
                detail.setText("无数据（编码器离线？）")
                continue
            cur = self._axis_deg(j, raw)
            if base is None:
                big.setText(f"{axis}   {cur:+7.2f}°")
                detail.setText(f"绝对角  raw {raw:.0f}  （未设基准，主显示为绝对角）")
            else:
                big.setText(f"{axis}   {self._angle_delta(cur, base):+7.2f}°")
                detail.setText(f"绝对 {cur:+.2f}°  raw {raw:.0f}  基准 {base:+.2f}°")
        servo_online = self.status_info.get("servo_online", 0)
        # ABS 最小/最大要扫整个 120s 缓冲（12000 点 × 3 台），60Hz 每拍都扫一次
        # 实测占 _update_tables 的大头（0.93ms/拍）。改成 ~4Hz 重算 + 其余拍复用缓存：
        # 这两列本来就是"窗口内的极值"，4Hz 刷新肉眼无差别。
        self._servo_mm_count = getattr(self, "_servo_mm_count", 0) + 1
        mm_cache = getattr(self, "_servo_mm_cache", None)
        if mm_cache is None:
            mm_cache = self._servo_mm_cache = {}
        refresh_mm = (self._servo_mm_count % 15 == 1) or not mm_cache
        for r, m in enumerate(SERVO_TARGETS):
            buf = self.channels[f"m{m}_abs"].buf
            if refresh_mm:
                _, hist = buf.series(BUFFER_SECONDS)
                mm_cache[m] = (float(np.nanmin(hist)) if hist.size else math.nan,
                               float(np.nanmax(hist)) if hist.size else math.nan)
            mm_lo, mm_hi = mm_cache.get(m, (math.nan, math.nan))
            vals = [
                buf.last(),
                mm_lo,
                mm_hi,
                self.channels[f"m{m}_raw"].buf.last(),
                self.channels[f"m{m}_speed"].buf.last(),
                self.channels[f"m{m}_load"].buf.last(),
                self.channels[f"m{m}_current"].buf.last(),
                self.channels[f"m{m}_volt"].buf.last(),
                self.channels[f"m{m}_temp"].buf.last(),
            ]
            for c, v in enumerate(vals):
                self.servo_table.item(r, c + 1).setText("-" if math.isnan(v) else f"{v:.2f}")
            self.servo_table.item(r, 10).setText("● 在线" if servo_online >> m & 1 else "○ 离线")

    def _update_status(self) -> None:
        self._plot_fps_last = getattr(self, "_plot_frames", 0)
        self._plot_frames = 0          # FPS 计数每秒归零（状态栏显示上一秒值）
        if self.t0 is not None:
            cutoff = (time.monotonic() - self.t0) - 2.0
            for dq in self.rate_counters.values():
                while dq and dq[0] < cutoff:
                    dq.popleft()
            names = {"enc_raw": "磁编raw", "enc_mapped": "映射", "servo_abs": "ABS",
                     "servo_raw": "单圈", "servo_telem": "遥测"}
            # 🖥fps + paint 用时 + 每像素点数：帧率掉没掉、还差多少预算，一眼可见
            paint_ms = getattr(getattr(self, "plot", None), "paint_ema_ms", 0.0)
            self.rate_label.setText(" | ".join(
                f"{names[k]} {len(dq) / 2.0:.0f}Hz" for k, dq in self.rate_counters.items())
                + f" | 🖥{getattr(self, '_plot_fps_last', 0)}fps"
                + f"/{paint_ms:4.1f}ms"
                + f"/{getattr(self, '_pts_per_px', 2.0):.2f}px"
                + ("·GL" if PLOT_GL_OK else "·软"))
        state = self.status_info.get("state")
        state_txt = STATE_NAMES.get(state, str(state)) if state is not None else "-"
        mode_txt = " [直控]" if self.status_info.get("control_mode") == 1 else ""
        enc_on = bin(self.status_info.get("encoder_online", 0)).count("1")
        srv_on = sum(1 for m in SERVO_TARGETS if self.status_info.get("servo_online", 0) >> m & 1)
        can = self.status_info.get("can_online", 0)
        conn = f"{self.port_combo.currentText().strip()} " if self.connected else ""
        shield = "" if self._safety_on() else "⚠安全保护关闭 | "
        self.status_label.setText(
            f"{shield}{conn}状态 {state_txt}{mode_txt} | CAN {'在线' if can else '离线'} | "
            f"磁编在线 {enc_on}/21 | M27-29 在线 {srv_on}/3")
        if TELEMETRY_PATH:
            self._tele_emit()

    # ---------- 运行遥测（MMHAND_TELEMETRY 生效时；否则不建定时器、不写文件） ----------
    def _timed_slot(self, key: str, fn):
        """返回定时器槽：开遥测时包一层计时，否则原样返回（零额外开销）。"""
        if not TELEMETRY_PATH:
            return fn
        return lambda: self._timed(key, fn)

    def _timed(self, key: str, fn) -> None:
        """包一层计时：记录上一秒内该回调的最大耗时（用于定位是谁卡住循环）。"""
        if not TELEMETRY_PATH:
            fn()
            return
        t0 = time.perf_counter()
        try:
            fn()
        finally:
            dt = (time.perf_counter() - t0) * 1000.0
            if dt > self._tele_max.get(key, 0.0):
                self._tele_max[key] = dt

    def _tele_beat(self) -> None:
        """50ms 心跳：记录事件循环的**迟到量**（被长回调阻塞会直接反映在这）。"""
        now = time.perf_counter()
        last = self._tele_last
        self._tele_last = now
        if last is not None:
            late = (now - last) * 1000.0 - 50.0   # 减掉心跳自身间隔才是"被占用"
            if late > self._tele_gap_ms:
                self._tele_gap_ms = late

    def _tele_emit(self) -> None:
        """把上一秒的运行指标追加成一行 JSONL。写失败不影响主流程。"""
        gap, self._tele_gap_ms = self._tele_gap_ms, 0.0
        table_hz, self._table_frames = getattr(self, "_table_frames", 0), 0
        spans = dict(self._tele_max)
        self._tele_max = {}
        sensor = self._tension_sensor
        last = self._tension_last
        fps = int(getattr(self, "_plot_fps_last", 0))
        rec = {
            "t": round(time.time(), 3),
            "fps": fps,
            # 无数据时主图不重绘，paint_ema 是上次的陈旧值 → 记 None 免得骗人
            "paint_ms": (round(float(getattr(self.plot, "paint_ema_ms", 0.0)), 2)
                         if fps > 0 else None),
            "pts_px": round(float(getattr(self, "_pts_per_px", 0.0)), 2),
            "loop_late_ms": round(gap, 1),
            "drain_max_ms": round(spans.get("drain", 0.0), 2),
            "plot_max_ms": round(spans.get("plot", 0.0), 2),
            "table_max_ms": round(spans.get("table", 0.0), 2),
            "tension_max_ms": round(spans.get("tension", 0.0), 2),
            "table_hz": int(table_hz),
            "rx_q": int(self.rx_queue.qsize()),
            "enc_hz": int(len(self.rate_counters["enc_raw"]) / 2),
            "telem_hz": int(len(self.rate_counters["servo_telem"]) / 2),
            "tension_age_ms": (None if last is None
                               else round((time.monotonic() - last[0]) * 1000.0, 1)),
            "tension_err": (None if sensor is None else int(sensor.protocol_errors)),
            "armed": bool(self.armed),
            "cl": bool(self.cl_enabled),
            "mode": self._cl_mode,
            "plot_ms": int(self.plot_timer.interval()),
            "table_ms": int(self.table_timer.interval()),
        }
        try:
            with open(TELEMETRY_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------- 导出（委托给 mmhand_scope_export，固定目录） ----------
    def _export_csv(self) -> None:
        self.export_btn.setEnabled(False)
        self._ctrl_status("CSV 导出中…", log=False)
        # 快照缓冲数据后在后台线程写文件，避免冻结界面。
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        servo_fields = ("abs", "raw", "speed", "load", "current", "volt", "temp")
        jobs = [
            (f"enc_raw_{stamp}.csv",
             [(f"J{j:02d}", self.channels[f"enc_raw_{j}"]) for j in range(ENCODER_COUNT)]),
            (f"servo_M27-29_{stamp}.csv",
             [(f"M{m}_{f}", self.channels[f"m{m}_{f}"])
              for m in SERVO_TARGETS for f in servo_fields]),
        ]

        def worker():
            try:
                for fname, named_channels in jobs:
                    live = [(name, *ch.buf.series(BUFFER_SECONDS))
                            for name, ch in named_channels
                            if ch.buf.count > 0]
                    if not live:
                        continue
                    n = min(len(t) for _, t, _ in live)
                    t_ref = live[0][1][-n:]
                    dump_csv(fname, [name for name, _, _ in live], list(t_ref),
                             [list(v[-n:]) for _, _, v in live])
            finally:
                self.exportFinished.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _export_done(self) -> None:
        self.export_btn.setEnabled(True)
        self._ctrl_status(f"CSV 已导出到 {EXPORT_DIR}")

    def _load_layout(self) -> None:
        data = load_layout_json()
        if not data:
            return
        try:
            # 勾选按保存原样应用；空列表=用户偏好空白启动，保持为空。
            saved_checked = [k for k in data.get("checked", [])
                             if k in self.channels]
            for ch in self.channels.values():
                ch.tree_item.setCheckState(
                    0, Qt.Checked if ch.key in saved_checked else Qt.Unchecked)
            for key, color in data.get("colors", {}).items():
                ch = self.channels.get(key)
                if ch is not None:
                    ch.color = color
            if "window" in data:
                i = self.window_combo.findText(data["window"])
                if i >= 0:
                    self.window_combo.setCurrentIndex(i)
            self.yauto_check.setChecked(data.get("yauto", True))
            self.norm_check.setChecked(data.get("normalize", False))
            self.abstime_check.setChecked(data.get("abstime", False))
            self.only_online_check.setChecked(data.get("only_online", True))
            self.ramp_check.setChecked(data.get("ramp", True))
            # 🛡 安全保护总开关（旧布局无此键 → 按默认开启，绝不给老配置放水）
            safety_on = bool(data.get("safety_on", True))
            self.safety_check.blockSignals(True)
            self.safety_check.setChecked(safety_on)
            self.safety_check.blockSignals(False)
            if not safety_on:
                self._ctrl_status("⚠ 安全保护为「关闭」状态（来自上次布局）："
                                  "直控不查张力，确认后再干活")
            if "ramp_rate" in data:
                self.ramp_rate_spin.setValue(int(data["ramp_rate"]))
            if "step" in data:
                i = self.step_combo.findText(str(data["step"]))
                if i >= 0:
                    self.step_combo.setCurrentIndex(i)
            for k, v in data.get("cl_params", {}).items():
                if k in self.cl_edits:
                    self.cl_edits[k].setText(str(v))
            hybrid = data.get("c1_position_params")
            if not isinstance(hybrid, dict):
                # 旧版只有 C1 参数归属混合模式，公用角度参数由专用默认值接替。
                hybrid = {k: v for k, v in data.get("cl_params", {}).items()
                          if k in ("c1_pos_target", "c1_pos_kp", "c1_pos_ki", "c1_pos_travel")}
            # 旧布局的 pos_ff 同时用于两轴。
            hybrid = {"pos_ff_pitch": hybrid.get("pos_ff", "0"), **hybrid}
            for key, edit in self._c1_position_edits.items():
                if key in hybrid:
                    edit.setText(str(hybrid[key]))
            self._restore_hybrid_settings(data)
            # 2026-11-18 合并后：t_tgt 是 preload 的只读镜像，旧布局里可能存着
            # 过时的 t*（如 15）而 preload 是 5 —— 加载完强制以 preload 为准。
            self.cl_edits["t_tgt"].setText(self.cl_edits["preload"].text())
            # fmin 迁移清洗（PLAN v8.2 §4）：负值=用户想禁用下界但留着毒数字
            # ——静默钳 0 会让"填了数却没下界"不可见（2026-11-03 台架实报 BUG）。
            # 归一为 0 并提示一次；守卫框 fmin 同治。
            try:
                fmin_txt = self.cl_edits["f_min"].text().strip()
                if fmin_txt and float(fmin_txt) < 0.0:
                    self.cl_edits["f_min"].setText("0")
                    print(f"[layout] fmin={fmin_txt} 无效已归 0（下界禁用）——"
                          "如需松绳检测请在边界行填正数")
            except (KeyError, ValueError):
                pass
            fp = data.get("force_params")   # 旧版布局遗留键：cl_params 已覆盖，兼容空转
            if isinstance(fp, dict):
                for k, v in fp.items():
                    if k in self.cl_edits:
                        self.cl_edits[k].setText(str(v))
            tg = data.get("tension_guard")
            if isinstance(tg, dict):
                self._tension_guard_saved.update(
                    {k: str(v) for k, v in tg.items() if k in ("f_min", "f_max")})
                # 观测台若已开着（罕见：布局重载），把存档回填进当前控件
                if self.tension_fmin_edit is not None:
                    self.tension_fmin_edit.setText(self._tension_guard_saved["f_min"])
                    self.tension_fmax_edit.setText(self._tension_guard_saved["f_max"])
            tl = data.get("tension_link")
            if isinstance(tl, dict):
                self._tension_link_saved.update(
                    {k: str(v) for k, v in tl.items() if k in ("port", "baud")})
            estimate_k = data.get("tension_estimate_k_n_mm")
            if (isinstance(estimate_k, list) and len(estimate_k) == 2
                    and all(isinstance(value, str) for value in estimate_k)):
                self._tension_estimate_k = estimate_k
            if isinstance(data.get("tension_trend"), bool):
                self._tension_trend_on = data["tension_trend"]
            if isinstance(data.get("tension_len_folded"), bool):
                self._tension_len_folded = data["tension_len_folded"]
            mode = data.get("cl_mode")
            # 2026-11-23 修复：漏了 "impedance" ⟹ 存档里的阻抗模式读回时被
            # 当成未知值忽略，界面静默退回「位置模式」。这正是"重启后阻抗
            # 模式跑不了"的根因之一（用户以为在阻抗，实际在位置）。
            mode_index = self.cl_mode_combo.findData(mode) if isinstance(mode, str) else -1
            if mode_index >= 0:
                self._cl_mode = mode
                self.cl_mode_combo.blockSignals(True)
                self.cl_mode_combo.setCurrentIndex(mode_index)
                self.cl_mode_combo.blockSignals(False)
                self._apply_cl_mode_visibility()
            ch_map = data.get("tension_ch_map")
            if (isinstance(ch_map, list) and len(ch_map) == 3
                    and all(isinstance(c, int) and 1 <= c <= 8 for c in ch_map)):
                self._tension_ch_map = list(ch_map)
            # 主题恢复：先设 AT 再同步下拉与全局样式（不触发保存回调）
            custom = data.get("custom_theme")
            self._custom_theme = custom if isinstance(custom, dict) else None
            AT.set_theme(data.get("theme", "night"), self._custom_theme)
            self._sync_theme_combo()
            self._apply_theme()
            yl = data.get("ylimits")
            if isinstance(yl, list) and len(yl) == 2:
                self._loading_layout = True
                self.ymin_spin.setValue(int(yl[0]))
                self.ymax_spin.setValue(int(yl[1]))
                self._loading_layout = False
            # 绘图偏好（2026-11-24）：帧率上限与抗锯齿，缺省保持启动默认。
            ph = data.get("plot_hz")
            if isinstance(ph, (int, float)) and 5 <= ph <= 120:
                self.plot_hz_combo.blockSignals(True)
                txt = str(int(ph))
                if self.plot_hz_combo.findText(txt) < 0:
                    self.plot_hz_combo.addItem(txt)
                self.plot_hz_combo.setCurrentText(txt)
                self.plot_hz_combo.blockSignals(False)
                self._plot_hz = float(int(ph))
                self._plot_interval_ms = max(1, int(round(1000.0 / int(ph))))
                if getattr(self, "plot_timer", None) is not None:
                    self.plot_timer.setInterval(self._plot_interval_ms)
            if isinstance(data.get("plot_aa"), bool):
                self.aa_check.blockSignals(True)
                self.aa_check.setChecked(data["plot_aa"])
                self.aa_check.blockSignals(False)
                self._set_plot_aa(data["plot_aa"])
            # 双击加的标记线（会话态落盘，重启回到原位）
            hm = data.get("h_markers")
            if isinstance(hm, list):
                self._clear_h_markers()
                for _y in hm[: self._H_MARKER_MAX]:
                    if isinstance(_y, (int, float)) and math.isfinite(float(_y)):
                        self._add_h_marker(float(_y), quiet=True)
            watch_saved = data.get("watch_params") or data.get("watch_last")
            if watch_saved:
                self._saved_watch_params = [k for k in watch_saved if isinstance(k, str)]
            if "cl_roll_on" in data:
                self.cl_roll_check.setChecked(bool(data["cl_roll_on"]))
            if "cl_pitch_on" in data:
                self.cl_pitch_check.setChecked(bool(data["cl_pitch_on"]))
            # 位置环结构（2026-11-23 定案：每拍递增 PID，同张力控制）：旧布局里的
            # `pos_loop` / `cl_model_on` 一律忽略——结构已固定，不再有切换。
            # 逐绳使能开关恢复：blockSignals 防触发 _save_layout 半程写盘
            # （与 cl_mode_combo 恢复同款手法）；恢复后统一刷新行可用性。
            ce = data.get("cable_enable")
            if isinstance(ce, dict):
                for m, cb in self.cable_enable_checks.items():
                    v = ce.get(str(m))
                    if isinstance(v, bool):
                        cb.blockSignals(True)
                        cb.setChecked(v)
                        cb.blockSignals(False)
                self._refresh_motor_rows()
            saved_raw = data.get("angle_baseline_raw", {})
            for j in (16, 17):
                rv = saved_raw.get(str(j))
                if isinstance(rv, int) and 0 <= rv <= 0xFFFF:
                    self._angle_baseline_raw[j] = rv
                    self.angle_baseline[j] = self._axis_deg(j, rv)
            # 窗口几何不恢复：每次启动固定 1600x900 居中（16:9）。
        except Exception as exc:
            print(f"[layout] 布局加载部分失败: {exc!r}")

    def _save_layout(self) -> None:
        import os
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return  # 离屏测试实例不写布局，防止污染用户配置
        hybrid_profiles = [dict(profile) for profile in self._hybrid_tension_profiles]
        hybrid_profiles[self._hybrid_return_index] = self._hybrid_tension_fields()
        legacy_hybrid = {key: edit.text() for key, edit in self._c1_position_edits.items()}
        legacy_hybrid.update(hybrid_profiles[0])
        data = {
            "checked": [k for k, ch in self.channels.items()
                        if ch.tree_item.checkState(0) == Qt.Checked],
            "colors": {k: ch.color for k, ch in self.channels.items()
                       if ch.color not in PALETTE},
            "window": self.window_combo.currentText(),
            "yauto": self.yauto_check.isChecked(),
            "normalize": self.norm_check.isChecked(),
            "abstime": self.abstime_check.isChecked(),
            "only_online": self.only_online_check.isChecked(),
            "ramp": self.ramp_check.isChecked(),
            "safety_on": self.safety_check.isChecked(),
            "ramp_rate": self.ramp_rate_spin.value(),
            "step": self.step_combo.currentText(),
            "cl_params": {k: e.text() for k, e in self.cl_edits.items()},
            "c1_position_params": legacy_hybrid,
            "hybrid_return_cable": self._hybrid_return_index,
            "hybrid_tension_profiles": hybrid_profiles,
            "hybrid_angle_pi": [[edit.text() for edit in row] for row in self._hybrid_pi_edits],
            "hybrid_ff_axes": [check.isChecked() for check in self._hybrid_ff_checks],
            # 位置环结构固定为「每拍递增 PID」。`pos_loop=2` / `cl_model_on=False`
            # 是给能读这两个键的旧版本看的（它们会落回自己的默认档）。
            "pos_loop": 2,
            "cl_model_on": False,
            "cl_mode": self._cl_mode,
            # force_params 已删：力控参数全在 cl_edits，cl_params 一处覆盖。
            # 旧条目引用 f1_tgt 等已删字段，v2 升级后每次保存 KeyError 全局丢档
            # （2026-11-02 修复，用户报"重启都归 0"的真凶）。
            "tension_guard": dict(self._tension_guard_saved),
            "tension_link": dict(self._tension_link_saved),
            "tension_estimate_k_n_mm": list(self._tension_estimate_k),
            "tension_trend": self._tension_trend_on,
            "tension_len_folded": self._tension_len_folded,
            "tension_ch_map": list(self._tension_ch_map),
            "theme": AT.current_name(),
            "custom_theme": getattr(self, "_custom_theme", None),
            "angle_baseline_raw": {str(j): self._angle_baseline_raw[j] for j in (16, 17)},
            "ylimits": [self.ymin_spin.value(), self.ymax_spin.value()],
            # 绘图偏好（2026-11-24）：帧率上限 + 抗锯齿
            "plot_hz": int(getattr(self, "_plot_hz", PLOT_HZ)),
            "plot_aa": self.aa_check.isChecked(),
            # 双击加的横线标记（数值，按添加顺序；重启后恢复到原位）
            "h_markers": [round(float(m.value()), 3)
                          for m in getattr(self, "_h_markers", ())
                          if math.isfinite(float(m.value()))],
            "cl_roll_on": self.cl_roll_check.isChecked(),
            "cl_pitch_on": self.cl_pitch_check.isChecked(),
            # 逐绳使能开关（缺省=全勾选；旧布局无此键按全勾处理）
            "cable_enable": {str(m): cb.isChecked()
                             for m, cb in self.cable_enable_checks.items()},
            "watch_params": ([k for k, _ in self.watch_window.tiles]
                             if self.watch_window is not None and self.watch_window.isVisible()
                             else None),
            "watch_last": ([k for k, _ in self.watch_window.tiles] if self.watch_window else None),
            # geometry 不存：窗口几何从不恢复（固定 1600x900 居中），存了就是死数据。
        }
        try:
            save_layout_json(data)
        except Exception:
            pass

    def closeEvent(self, event):
        if self.watch_window is not None:
            self.watch_window.close()  # Qt.Window 子窗不随父窗级联关闭，需显式关
        if self.rt_window is not None:
            self.rt_window.close()
        # 正弦记录：无论有没有在跑闭环，关窗都要收口（未武装时 _on_stop 不会执行）
        self._sine_log_close()
        self._safety("APP_CLOSE")
        if self._tension_sensor is not None:
            self._tension_disconnect("主窗关闭")
        self._save_layout()
        if self.armed:
            self._on_stop()
        self._disconnect()
        try:
            # 正常退出才写 session 日志；safety 日志是逐行 flush 的，崩溃也不丢
            from desktop.core.session_log import close_session_log
            close_session_log()
        except Exception:
            pass
        if self._tension_thread is not None:
            self._close_after_tension = True
            event.ignore()
            return
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="MMHand 全通道只读示波器")
    parser.add_argument("--port", default="COM13")
    parser.add_argument("--no-auto-connect", action="store_true", help="启动后不自动连接")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setStyleSheet(AT.build_app_qss())
    icon_path = Path(__file__).resolve().parent / "mmhand_scope.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = ScopeWindow(default_port=args.port)
    win.show()
    if not args.no_auto_connect:
        QTimer.singleShot(300, win._connect)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

