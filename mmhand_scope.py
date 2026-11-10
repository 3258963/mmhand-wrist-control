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
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
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
# 主图帧率：默认 60FPS（数据链路 0.5ms + paint 实测最坏 13ms，预算够）。
# 想省电/省 CPU 可 MMHAND_PLOT_HZ=30；想试更高 MMHAND_PLOT_HZ=120。
# 曲线点数由 _adapt_density 按 paint 实测自适应，帧率不会被点数拖下来。
try:
    PLOT_HZ = float(os.environ.get("MMHAND_PLOT_HZ", "60"))
except ValueError:
    PLOT_HZ = 60.0
PLOT_HZ = max(5.0, min(120.0, PLOT_HZ))
PLOT_INTERVAL_MS = max(1, int(round(1000.0 / PLOT_HZ)))

# 全局主题（app_theme：夜间/白天/赛博朋克/自定义；工具栏可切，即时生效）
import app_theme as AT
pg.setConfigOptions(background=AT.T("plot_bg"), foreground=AT.T("plot_fg"))

from desktop.core.communication.frame_decoder import FrameDecoder
from desktop.core.generated_upper_protocol import (
    CMD_UPLINK_MASK,
    PACKET_TYPE_ENCODER_RAW,
    PACKET_TYPE_PROTO_ACK,
    PACKET_TYPE_SERVO_ANGLE,
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
    build_active_scope_cmd,
    build_reset_cmd,
    build_host_heartbeat_cmd,
    build_motor_pos_abs_cmd,
    build_motor_pos_abs_one_cmd,
    build_servo_reset_zero_cmd,
    build_start_cmd,
    build_stop_cmd,
    parse_proto_ack,
    parse_servo_angle_packet,
    parse_servo_raw_packet,
    parse_servo_route_status_packet,
    parse_servo_telem_packet,
    parse_system_status_packet,
)

# 示波器保留的上行流：映射角 + 舵机 ABS + 磁编 raw + 路由（状态/故障/安全事件不受掩码影响）。
SCOPE_UPLINK_MASK = (UPLINK_MASK_SERVO_ANGLE |
                     UPLINK_MASK_SERVO_TELEM | UPLINK_MASK_SERVO_RAW |
                     UPLINK_MASK_ENCODER_RAW | UPLINK_MASK_SERVO_ROUTE)
# 逐绳使能开关（2026-11-02）后活动域不再是固定 M27-29 全集：使能时按勾选
# 动态算掩码（ScopeWindow._enabled_motor_mask），故不再有模块级 MOTOR_SCOPE_MASK。
MOTOR_SOFT_LIMIT = 2000000  # counts 输出上界（≈int32 安全域，等效解除 ±5000；仅防溢出）
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
TENSION_POLL_HZ = 250.0      # 重量帧目标频率：RTT~2ms+帧间隙1ms 的硬件地板之上留裕量（实测可稳定 250Hz）；
                             # 设备刷新 1280Hz、波特率 600000（见 znsv_app/rate_upgrade.py）；依赖 FTDI LatencyTimer=1，
                             # 未修复的机器上 RTT 16ms 自动降速 ~55Hz，无超时风暴。闭环 100Hz 下每拍都有新张力。
# J16/J17 角度显示方向（-1 = 与磁编原始方向相反，按用户实测约定）。
AXIS_SIGN = {16: 1.0, 17: -1.0}   # J16=ROLL / J17=PITCH 方向；2026-10-28 pitch 取反（编码器重接线后方向复核）
# 界面 pitch ↔ 模型 pitch（+X 右手定则）的换算。
# 2026-11-10 曾整体取反一次（AXIS_SIGN[17]=+1、本常数=-1），台架反馈"又反了" —— 已按用户
# 要求改回原约定：界面角 = AXIS_SIGN[17]·raw，模型角 = 界面角（本常数 +1，等价于不换算）。
# 若以后要翻 pitch 正方向：**两个一起改**（AXIS_SIGN[17] 与 PITCH_MODEL_SIGN 同时取反），
# 只改一个会让 R/l 与编码器错位、闭环变正反馈。
PITCH_MODEL_SIGN = 1.0


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
from wrist_model import RANGE_DEG, PITCH, ROLL, positive_null_direction, wrist_eval
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
from wrist_force_law import (FORCE_OK, FORCE_NO_NULL, FORCE_OVERLOAD,
                              FORCE_STALE, FORCE_TDA_INFEASIBLE,
                              WristForceV2Params, WristForceV2State,
                              WristTensionParams, WristTensionState,
                              WristTightParams, WristTightState,
                              wrist_force_v2_step, wrist_tension_step,
                              wrist_tight_step)
from wrist_tda import tda_solve
DIRECT_REJECT_NAMES = {
    0: "无", 1: "状态不允许", 2: "硬件不可控", 3: "多圈未知",
    4: "事件队列满", 5: "命令过期", 6: "系统故障",
}
from mmhand_scope_export import (EXPORT_DIR, dump_csv, load_layout_json,
                                 load_named_json, save_layout_json, save_named_json)
from wrist_control_law import (FLAG_FEEDBACK_CLAMPED, FLAG_GEOM_INVALID,
                               FLAG_I_CLAMPED, FLAG_LOW_PITCH, FLAG_NONFINITE,
                               FLAG_TARGET_CLAMPED, WristControlParams,
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
        elif packet_type == PACKET_TYPE_SYSTEM_STATUS:
            st = parse_system_status_packet(body)
            if st:
                self.out_queue.put(("status", now, {
                    "state": st[0],
                    "control_enabled": st[1],
                    "owner": st[2],
                    "control_mode": st[3],
                    "servo_online": st[12],
                    "encoder_online": st[13],
                    "can_online": st[14],
                    "multiturn_unknown": st[7],
                    # 活动域：0xD3 批量帧在固件里会与它求交（0xDE 单电机不查），
                    # 上位机必须核对，否则"只有活动域里那台动"。
                    "active_motor_mask": st[8] if len(st) > 8 else 0,
                    "direct_reject": st[29] if len(st) > 29 else 0,
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
            # 渲染减压：峰值降采样+关抗锯齿（clipToView 已撤——与手动
            # setXRange 组合在边界帧有裁剪边角，参与"显示不全"）
            pi = plt.getPlotItem()
            pi.setDownsampling(mode="peak")
            plt.setAntialiasing(False)
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
        """力状态历史导出 CSV（t_s, τR, τP, t；NaN 行自动跳过由 csv 写空）。"""
        rows = list(self._force_rows)
        if len(rows) < 2:
            if getattr(self.scope, "tension_status", None) is not None:
                self.scope.tension_status.setText("力状态：还没有数据可导出")
            return
        name = "force_status_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        path = dump_csv(
            name,
            header=["t_s", "tau_roll_mNm", "tau_pitch_mNm", "tight_t_N"],
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
            tau_r_v = sum(out.r_m[ROLL][i] * fvals[i] for i in range(3)) * 1000.0
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
    """主图控件：始终统计 paint 用时（喂给自适应点数阀门）；MMHAND_FPS=1 时每 2s 打印。"""

    _report = os.environ.get("MMHAND_FPS") == "1"
    paint_ema_ms = 0.0
    last_paint_ms = 0.0

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


class ScopeWindow(QMainWindow):
    exportFinished = Signal()

    def __init__(self, default_port: str = "COM13"):
        super().__init__()
        install_no_wheel_guard()   # 滚轮不得改控制模式/步长/波特率等（全局一次）
        self.setWindowTitle("MMHand 示波器+直控 - 磁编 J00-J20 + M27-M29")
        self.resize(1600, 900)  # 16:9
        # 居中到主屏
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(max(0, (screen.width() - 1600) // 2),
                  max(0, (screen.height() - 900) // 2))
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
        self.armed = False
        self.targets = {m: None for m in SERVO_TARGETS}
        self._zero_poll_count = 0
        self._ramp_state = {}
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
        # 位置环前馈参考位姿（启动瞬间的实测 roll/pitch，UI 约定）：
        # 前馈算 origin→目标 的绳长增量，origin 记的是启动瞬间的电机计数，
        # 两者必须同一姿态，否则稳态偏 s/(1−kp)（2026-11-10 修复）。
        self._cl_ref_pose = None
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
        self.cl_edits = {}
        self.watch_window = None
        self.rt_window = None
        self.wrist_calib = None
        self._tension_sensor = None     # ZnsvTransmitter（连接后非 None，观测台直接持有）
        self._tension_port_name = ""
        self._tension_ch_map = list(TENSION_CH_FOR_CABLE)   # C1/C2/C3 ← CHn（观测台可改）
        self._tension_poll_timer = QTimer(self)
        # 初始 1ms；连接后由 _tension_poll 按 driver.next_poll_delay() 自适应：
        # 传输中 1ms，空闲期排到下一个请求时隙（唤醒约减半，采样率不变）。
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
        # 标定文件存在就随启动载入（否则「模型前馈」永远是灰的，每次重启都得手点）
        self._load_wrist_calib(quiet=True)
        self._load_layout()
        # 布局里恢复了「trim方向」→ 符号自检要按恢复后的值再算一次（只刷新标签，不重读策略）
        if self.wrist_calib is not None:
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

        # 顶部工具栏
        bar = QHBoxLayout()
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
        bar.addWidget(QLabel("窗口"))
        self.window_combo = QComboBox()
        self.window_combo.addItems(["10s", "30s", "60s", "120s"])
        self.window_combo.setCurrentIndex(1)
        bar.addWidget(self.window_combo)
        self.xauto_check = QCheckBox("X跟随")
        self.xauto_check.setChecked(True)
        self.xauto_check.setToolTip("X 轴自动跟随最新数据滚动（示波器模式）；取消勾选可手动拖动/缩放")
        bar.addWidget(self.xauto_check)
        self.yauto_check = QCheckBox("Y自适应")
        self.yauto_check.setChecked(True)
        self.yauto_check.toggled.connect(self._on_yauto_toggled)
        bar.addWidget(self.yauto_check)
        bar.addWidget(QLabel("Y限"))
        self._loading_layout = False
        self.ymin_spin = QSpinBox()
        self.ymax_spin = QSpinBox()
        for s, default in ((self.ymin_spin, 0), (self.ymax_spin, 16384)):
            s.setRange(-200000, 200000)
            s.setValue(default)
            s.setFixedWidth(76)
            s.valueChanged.connect(lambda _=0: self._apply_y_limits())
            bar.addWidget(s)
        self.norm_check = QCheckBox("归一化")
        self.norm_check.setToolTip("每条曲线按窗口内自身 min/max 归一化，解决量纲混画")
        bar.addWidget(self.norm_check)
        self.abstime_check = QCheckBox("绝对时间")
        self.abstime_check.toggled.connect(self._on_abstime_toggled)
        bar.addWidget(self.abstime_check)
        bar.addWidget(QLabel("预设"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["自定义", "腕部调试", "全磁编raw", "M27-29遥测", "全清"])
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        bar.addWidget(self.preset_combo)
        self.only_online_check = QCheckBox("只显示在线")
        self.only_online_check.setChecked(True)
        self.only_online_check.toggled.connect(self._refresh_table_visibility)
        bar.addWidget(self.only_online_check)
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("全局配色：切换立即生效并随布局记住\n自定义=逐槽选色（未设槽继承夜间）")
        self.theme_combo.addItems(list(AT.DISPLAY_NAMES.values()))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        bar.addWidget(self.theme_combo)
        bar.addStretch(1)
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
        root_layout.addLayout(bar)

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
        self.tree.setMinimumWidth(240)
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
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        # 渲染减压（2026-11-03 卡顿修复）：多通道 100FPS 光栅是 GUI 卡顿主源，
        # 配合 33FPS 门 + 峰值降采样 + 视口裁剪，曲线密度再高也稳。
        _pi = self.plot.getPlotItem()
        _pi.setDownsampling(mode="peak")
        _pi.setClipToView(True)
        self.plot.setAntialiasing(False)
        self.legend = self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel("bottom", "时间")
        self.plot.getPlotItem().showButtons()
        # 暂停覆盖标记
        self.paused_text = pg.TextItem("⏸ 已暂停（点『恢复曲线』继续）", color="#ffb300", anchor=(0.5, 0))
        self.paused_text.setPos(0, 0)
        self.paused_text.setParentItem(self.plot.getPlotItem().vb)
        self.paused_text.setZValue(100)
        self.paused_text.hide()
        # 无曲线提示：勾选为空时给出可操作的指引
        self.empty_plot_text = pg.TextItem(
            "曲线区为空：在左侧通道树勾选通道，或用工具栏「预设」一键加载",
            color="#ffb300", anchor=(0.5, 0.5))
        self.empty_plot_text.setParentItem(self.plot.getPlotItem().vb)
        self.empty_plot_text.setZValue(99)
        self.plot.getPlotItem().vb.sigRangeChanged.connect(
            lambda *_: self.empty_plot_text.setPos(
                sum(self.plot.getPlotItem().vb.viewRange()[0]) / 2,
                sum(self.plot.getPlotItem().vb.viewRange()[1]) / 2))
        # 十字游标 + 数值读出
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen="#888")
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen="#888")
        self.plot.addItem(self.vLine, ignoreBounds=True)
        self.plot.addItem(self.hLine, ignoreBounds=True)
        self.cursor_label = pg.TextItem("", color="#e0e0e0", anchor=(0, 1))
        self.cursor_label.setParentItem(self.plot.getPlotItem().vb)
        self.cursor_label.setZValue(99)
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
        panel_scroll.setMinimumWidth(640)
        panel_scroll.setMaximumWidth(700)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        splitter.addWidget(panel_scroll)

        # 底部：数值表
        tables = QSplitter(Qt.Horizontal)
        self.enc_table = QTableWidget(ENCODER_COUNT, 4)
        self.enc_table.setHorizontalHeaderLabels(["通道", "raw", "角度°", "在线"])
        self.enc_table.verticalHeader().setVisible(False)
        self.enc_table.setEditTriggers(QTableWidget.NoEditTriggers)
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
        box.setMinimumWidth(620)
        box.setMaximumWidth(680)
        lay = QVBoxLayout(box)
        head = QHBoxLayout()
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
        body = QHBoxLayout()
        body.setSpacing(12)
        lay.addLayout(body)
        left = QVBoxLayout()
        right = QVBoxLayout()
        body.addLayout(left, 0)
        body.addLayout(right, 1)

        self.roll_label = QLabel("ROLL  --.-°")
        self.roll_label.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {AT.T('accent')}; padding: 2px;")
        self.roll_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.pitch_label = QLabel("PITCH --.-°")
        self.pitch_label.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {AT.T('good')}; padding: 2px;")
        self.pitch_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left.addWidget(self.roll_label)
        left.addWidget(self.pitch_label)
        self.roll_detail = QLabel("绝对 --.-°  raw --  基准 --")
        self.roll_detail.setObjectName("muted")
        self.pitch_detail = QLabel("绝对 --.-°  raw --  基准 --")
        self.pitch_detail.setObjectName("muted")
        left.addWidget(self.roll_detail)
        left.addWidget(self.pitch_detail)
        zero_row = QHBoxLayout()
        tip = "把当前角度记为 0 点参考，Δ 立即归零；随时可按，不影响控制"
        self.zero_roll_btn = QPushButton("📐 ROLL")
        self.zero_roll_btn.setToolTip("ROLL(J16) 零位 = 当前角度。" + tip)
        self.zero_roll_btn.clicked.connect(lambda _=False: self._set_angle_baseline_now(16))
        self.zero_pitch_btn = QPushButton("📐 PITCH")
        self.zero_pitch_btn.setToolTip("PITCH(J17) 零位 = 当前角度。" + tip)
        self.zero_pitch_btn.clicked.connect(lambda _=False: self._set_angle_baseline_now(17))
        self.zero_both_btn = QPushButton("📐 双轴")
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
        self.reset_btn.setStyleSheet("padding: 8px;")
        self.reset_btn.setToolTip("清除 E-STOP 锁存与可恢复故障（CMD_RESET）")
        self.reset_btn.clicked.connect(self._on_reset)
        estop_row.addWidget(self.reset_btn)
        left.addLayout(estop_row)
        zero_row = QHBoxLayout()
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
        step_row.addWidget(QLabel("步长"))
        self.step_combo = QComboBox()
        self.step_combo.addItems(["100", "250", "500", "1000", "2000"])
        self.step_combo.setCurrentIndex(2)
        step_row.addWidget(self.step_combo)
        step_row.addStretch(1)
        left.addLayout(step_row)
        # 步长快捷档：一键切换（与下拉框同步，按钮文字随选中的档位高亮）
        preset_row = QHBoxLayout()
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
        for m in SERVO_TARGETS:
            row = QHBoxLayout()
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
            row.addWidget(tag)
            minus = QPushButton(f"−{self._step()}")
            plus = QPushButton(f"＋{self._step()}")
            self.jog_buttons_by_motor[m] = [minus, plus]
            for b, d in ((minus, -1), (plus, 1)):
                b.setMinimumHeight(34)
                b.setAutoRepeat(True)
                b.setAutoRepeatDelay(280)
                b.setAutoRepeatInterval(90)
                b.clicked.connect(lambda _=False, mm=m, dd=d: self._jog(mm, dd * self._step()))
                b.setEnabled(False)
                self.jog_buttons.append(b)
                row.addWidget(b, 1)
            right.addLayout(row)
            # 手动目标行：绝对值输入 + Go（回车同效）
            tgt_row = QHBoxLayout()
            edit = QLineEdit()
            edit.setPlaceholderText(f"M{m} 相对当前位置，回车=发送")
            edit.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhLatinOnly)
            edit.setMinimumHeight(30)
            go = QPushButton("Go")
            go.setMinimumHeight(30)
            go.setFixedWidth(44)
            edit.returnPressed.connect(lambda mm=m, ed=edit: self._send_manual_target(mm, ed))
            go.clicked.connect(lambda _=False, mm=m, ed=edit: self._send_manual_target(mm, ed))
            tgt_row.addWidget(edit, 1)
            tgt_row.addWidget(go)
            right.addLayout(tgt_row)
            self.target_edits[m] = edit
            self.go_buttons[m] = go
            info = QLabel("未使能")
            info.setStyleSheet(
                f"color: {AT.T('muted')}; font-size: 11px; padding-left: 4px;")
            info.setWordWrap(True)   # 长状态行允许换行，不撑宽右列
            right.addWidget(info)
            self.motor_info[m] = info
        right.addStretch(1)

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
        self.ramp_check.setToolTip("大位移目标按最大速率分步发送，避免舵机全速冲")
        speed_row.addWidget(self.ramp_check)
        speed_row.addWidget(QLabel("最大"))
        self.ramp_rate_spin = QSpinBox()
        self.ramp_rate_spin.setRange(100, 50000)
        self.ramp_rate_spin.setValue(3000)
        self.ramp_rate_spin.setSuffix(" c/s")
        speed_row.addWidget(self.ramp_rate_spin)
        speed_row.addStretch(1)
        lay.addLayout(speed_row)
        servo_speed_note = QLabel(
            "舵机速度：寄存器已烧录 1000 steps/s（2026-11-03 由 600 升档；量程 0-3400）\n"
            "（协议直控命令不含速度字段；实测值看底部舵机表『速度』列）")
        servo_speed_note.setStyleSheet(
            f"color: {AT.T('muted')}; font-size: 11px; padding: 2px;")
        servo_speed_note.setWordWrap(True)
        lay.addWidget(servo_speed_note)
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
        """负反馈闭环面板：ROLL/PITCH 目标角 -> 系数矩阵 -> M27-29（闭环 100Hz）。"""
        box = QGroupBox("负反馈闭环 ROLL/PITCH")
        cl = QVBoxLayout(box)

        # 控制模式：位置（角度闭环）/ 张力·力控（张力闭环 PI → 位置 trim）
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("模式"))
        self.cl_mode_combo = QComboBox()
        self.cl_mode_combo.addItems(["位置模式（角度闭环）",
                                     "张力控制（每缆张力闭环）",
                                     "张紧控制（预紧度闭环）",
                                     "力矩控制（解耦力矩闭环）"])
        self.cl_mode_combo.setToolTip(
            "位置模式：被控量=关节角度（前馈用解析模型绳长 + R·e 校正，需「模型前馈」）。\n"
            "张力控制：被控量=每根缆的张力 N（逐缆 PI→trim），最直观，台架起步用。\n"
            "张紧控制：被控量=预紧程度（沿零空间整体收紧/放松，力矩保持不变）。\n"
            "力矩控制：被控量=关节力矩 τ（论文 v2：TDA 分配+解耦校正），进阶。\n"
            "力控投入后腕停在当前位姿附近，手掰会顺从回力；角度目标被忽略。\n"
            "切换模式会先停止正在运行的闭环。")
        self.cl_mode_combo.currentIndexChanged.connect(self._on_cl_mode_changed)
        mode_row.addWidget(self.cl_mode_combo, 1)
        cl.addLayout(mode_row)
        self._cl_mode = "position"          # 'position'|'tension'|'tight'|'force'
        self._force_state = WristForceV2State()     # 力矩模式（v2）
        self._tension_state = WristTensionState()   # 张力模式
        self._tight_state = WristTightState()       # 张紧模式
        self._pos_pid_state = WristPidState()       # 位置环 PID 状态（两种结构共用）
        self._force_base = None             # 进入力控时刻的电机位置基准
        self._force_trim = [0.0, 0.0, 0.0]  # 上次发送的 trim（变更抑制用）
        self._force_need_send = False       # 重入首拍强制下发 base（防目标跳变）

        self.cl_roll_now = QLabel("ROLL  --.--°→--.--°  编码器 --→--")
        self.cl_roll_now.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #64b5f6; padding: 1px;")
        cl.addWidget(self.cl_roll_now)
        self.cl_pitch_now = QLabel("PITCH --.--°→--.--°  编码器 --→--")
        self.cl_pitch_now.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #81c784; padding: 1px;")
        cl.addWidget(self.cl_pitch_now)

        self._cl_tgt_row_w = QWidget()          # 容器：力控模式下整行隐藏
        tgt_row = QHBoxLayout(self._cl_tgt_row_w)
        tgt_row.setContentsMargins(0, 0, 0, 0)
        tgt_row.addWidget(QLabel("目标°"))
        self.cl_edits["roll_tgt"] = self._cl_edit("ROLL目标°")
        self.cl_edits["pitch_tgt"] = self._cl_edit("PITCH目标°")
        tgt_row.addWidget(self.cl_edits["roll_tgt"], 1)
        tgt_row.addWidget(self.cl_edits["pitch_tgt"], 1)
        # 分轴闭环开关：取消勾选的轴其系数列整体置零（前馈+校正都不作用）
        self.cl_roll_check = QCheckBox("ROLL环")
        self.cl_roll_check.setChecked(True)
        self.cl_roll_check.setToolTip("只闭环 ROLL：kr 系数列置零，Roll 方向不控、随耦合自由漂移")
        tgt_row.addWidget(self.cl_roll_check)
        self.cl_pitch_check = QCheckBox("PITCH环")
        self.cl_pitch_check.setChecked(True)
        self.cl_pitch_check.setToolTip("只闭环 PITCH：kp 系数列置零，Pitch 方向不控、随耦合自由漂移")
        tgt_row.addWidget(self.cl_pitch_check)
        # 自动慢扫掠：闭环目标三角波（标定录数用），须启动闭环后才开始走
        self.sweep_check = QCheckBox("扫掠")
        self.sweep_check.setToolTip(
            "闭环运行中让所选轴在 ±限幅 间按速度做三角波扫掠（目标框被自动改写）。\n"
            "标定录数据：勾选「⏺记录」+ 扫掠 + 慢速（如 0.5°/s）= 高质量 CSV")
        self.sweep_check.toggled.connect(self._on_sweep_toggled)
        tgt_row.addWidget(self.sweep_check)
        self.sweep_axis = QComboBox()
        self.sweep_axis.addItems(["ROLL", "PITCH"])
        # 扫掠中切轴：按新轴目标框重新播种（否则目标跳到上一轴的值）
        self.sweep_axis.currentIndexChanged.connect(self._on_sweep_axis_changed)
        tgt_row.addWidget(self.sweep_axis)
        self.sweep_speed = QDoubleSpinBox()
        self.sweep_speed.setRange(0.1, 5.0)
        self.sweep_speed.setDecimals(1)
        self.sweep_speed.setValue(0.5)
        self.sweep_speed.setSuffix("°/s")
        self.sweep_speed.setToolTip("扫掠速度（三角波用）：标定建议 0.2~0.5°/s（慢到准）")
        tgt_row.addWidget(self.sweep_speed)
        self.sweep_amp = QDoubleSpinBox()
        self.sweep_amp.setRange(0.5, 90.0)
        self.sweep_amp.setDecimals(1)
        self.sweep_amp.setValue(25.0)
        self.sweep_amp.setSuffix("°")
        self.sweep_amp.setToolTip(
            "波形幅值（峰）°：正弦/三角都按它摆；超过「限幅°」时按限幅截断。\n"
            "正弦峰值速度 = 幅值×2πf，超过每拍限幅折算的速度就会削顶。")
        tgt_row.addWidget(self.sweep_amp)
        cl.addWidget(self._cl_tgt_row_w)
        # 波形行（2026-11-10 新增正弦跟随测试）：三角波=录标定（原有），
        # 正弦波=带宽/跟随测试——目标 A·sin(2πft)，A=限幅、f=频率框。
        sweep_row = QHBoxLayout()
        self.sweep_wave_combo = QComboBox()
        self.sweep_wave_combo.addItems(["三角波", "正弦波"])
        self.sweep_wave_combo.setToolTip(
            "三角波：线性往返（录标定数据用，配合慢速）。\n"
            "正弦波：跟随/带宽测试——目标= 限幅×sin(2π·频率×t)，\n"
            "看实际曲线的幅度衰减与相位滞后。峰值速度需求=限幅×2πf，\n"
            "超过每拍限幅速度（5c/拍×100Hz）会削顶=带宽已到。")
        sweep_row.addWidget(self.sweep_wave_combo)
        self.sweep_freq = QDoubleSpinBox()
        self.sweep_freq.setRange(0.05, 2.0)
        self.sweep_freq.setDecimals(2)
        self.sweep_freq.setValue(0.2)
        self.sweep_freq.setSuffix(" Hz")
        self.sweep_freq.setToolTip(
            "正弦频率（仅正弦波用）。0.05~0.2Hz 看低频跟随；\n"
            "0.5Hz 以上逐步逼近带宽极限（幅度会缩、相位会滞后）")
        sweep_row.addWidget(self.sweep_freq)
        sweep_row.addStretch(1)
        cl.addLayout(sweep_row)
        self._sweep_val = 0.0
        self._sweep_dir = 1.0
        self._sweep_phase = 0.0     # 正弦相位（勾选时刻起算）
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(50)   # 20Hz 推进波形
        self._sweep_timer.timeout.connect(self._sweep_tick)
        self._sweep_timer.start()

        # 位置模式只有"模型前馈"一条路：M27/M28/M29 手填系数行已删除
        # （2026-11-03 用户要求）。保留 0 值占位，避免控制律读不到增益。
        self._cl_gain_vals = {m: (0.0, 0.0) for m in SERVO_TARGETS}   # (ROLL系数, PITCH系数)

        self._cl_par_row_w = QWidget()          # 容器：力控模式下隐藏
        par_row = QHBoxLayout(self._cl_par_row_w)
        par_row.setContentsMargins(0, 0, 0, 0)
        par_row.addWidget(QLabel("Kp"))
        self.cl_edits["kp"] = self._cl_edit("比例增益（关节角域，无量纲）", text="0.6")
        par_row.addWidget(self.cl_edits["kp"])
        par_row.addWidget(QLabel("Ki"))
        self.cl_edits["ki"] = self._cl_edit(
            "积分增益 1/s（关节角域）。0=纯PD。\n"
            "稳态误差（模型偏差/重力下垂）靠它吃掉；积分项被钳在「限幅°」×1 以内防 windup。",
            text="0")
        par_row.addWidget(self.cl_edits["ki"])
        par_row.addWidget(QLabel("Kd"))
        self.cl_edits["kd"] = self._cl_edit(
            "微分增益 s。微分作用在**反馈角速度**上（不是误差跳变），\n"
            "所以拖目标框不会砸出尖峰；反馈已过 76ms EMA，Kd 一般 0~0.05 就够。",
            text="0")
        par_row.addWidget(self.cl_edits["kd"])
        par_row.addWidget(QLabel("死区°"))
        self.cl_edits["deadband"] = self._cl_edit("死区°", text="0.3")
        par_row.addWidget(self.cl_edits["deadband"])
        par_row.addWidget(QLabel("限幅°"))
        self.cl_edits["limit"] = self._cl_edit("目标角限幅°", text="25")
        par_row.addWidget(self.cl_edits["limit"])
        par_row.addStretch(1)
        cl.addWidget(self._cl_par_row_w)

        # 每拍限幅（位置模式与力控三模式共用；所有模式都显示这一行）
        self._cl_step_row_w = QWidget()
        step_row = QHBoxLayout(self._cl_step_row_w)
        step_row.setContentsMargins(0, 0, 0, 0)
        step_row.addWidget(QLabel("每拍限幅"))
        self.cl_edits["max_step_f"] = self._cl_edit(
            "每拍最大位置增量 counts，**位置模式与力控三模式共用同一个值**：\n"
            "· 位置模式：绝对目标换算成每拍变化 ≤ 此值\n"
            "· 力控/张紧/张力：增量式限速（每拍最多走这么多）\n"
            "100Hz 下 5 counts/拍 = 500 counts/s。", text="5")
        step_row.addWidget(self.cl_edits["max_step_f"])
        step_hint = QLabel("counts/拍（100Hz）")
        step_hint.setObjectName("muted")
        step_row.addWidget(step_hint)
        step_row.addStretch(1)
        cl.addWidget(self._cl_step_row_w)

        self._cl_model_row_w = QWidget()        # 容器：力控模式下隐藏
        model_row = QHBoxLayout(self._cl_model_row_w)
        model_row.setContentsMargins(0, 0, 0, 0)
        self.cl_load_btn = QPushButton("📥 载入标定")
        self.cl_load_btn.setToolTip(
            "读取 run_data/scope_exports/wrist_calib.json（识别脚本 --write 生成）")
        self.cl_load_btn.clicked.connect(lambda: self._load_wrist_calib())
        model_row.addWidget(self.cl_load_btn)
        # 位置环结构（2026-11-10）：前馈+PID（绝对式）/ 纯PID（增量式）。
        self.pos_loop_combo = QComboBox()
        self.pos_loop_combo.addItems(["前馈+PID", "纯PID"])
        self.pos_loop_combo.setToolTip(
            "位置环两种结构（同一套 PID，只差基准）：\n"
            "· 前馈+PID：绝对式。目标 counts = origin + k·[l(目标)−l(启动位姿)] + J·δθ，\n"
            "  模型算绳长前馈，PID 只补模型误差——到位最快、稳态靠积分。\n"
            "· 纯PID：增量式。目标 counts = 实测位置 + J·δθ，不做前馈、不用模型绳长，\n"
            "  只借当前雅可比 J=−k·R 把角度误差折算成 counts（和三个力控模式同一个\n"
            "  '每拍从实测走一步'语义）。\n"
            "两者都需要载入标定（k 与 R）；运行中切换会先停环。")
        self.pos_loop_combo.currentIndexChanged.connect(self._on_pos_loop_changed)
        model_row.addWidget(self.pos_loop_combo, 1)
        cl.addWidget(self._cl_model_row_w)
        self.cl_calib_label = QLabel("标定：未载入（模型前馈不可用）")
        self.cl_calib_label.setObjectName("muted")
        self.cl_calib_label.setWordWrap(True)
        cl.addWidget(self.cl_calib_label)

        # ---- 力控参数行 ×3 模式 + 公共行（三力控模式共享方向/限幅/下限）----
        # 力矩模式（v2 论文式：τ_d + 预紧 + 解耦校正 + TDA 分配）
        self._cl_force_row_w = QWidget()
        force_row = QHBoxLayout(self._cl_force_row_w)
        force_row.setContentsMargins(0, 0, 0, 0)
        force_row.addWidget(QLabel("τd(N·m)"))
        self.cl_edits["tau_roll"] = self._cl_edit(
            "期望 ROLL 力矩 N·m（正=收ROLL方向）", text="0.0")
        force_row.addWidget(self.cl_edits["tau_roll"])
        self.cl_edits["tau_pitch"] = self._cl_edit(
            "期望 PITCH 力矩 N·m", text="0.0")
        force_row.addWidget(self.cl_edits["tau_pitch"])
        force_row.addWidget(QLabel("预紧N"))
        self.cl_edits["preload"] = self._cl_edit(
            "沿零空间方向的预紧张力 N（TDA 自动分配到三缆）", text="5.0")
        force_row.addWidget(self.cl_edits["preload"])
        force_row.addWidget(QLabel("Kp_τ"))
        self.cl_edits["kp_tau"] = self._cl_edit(
            "力矩P增益（无量纲：u 与 τ 同为 N·m）", text="100")
        force_row.addWidget(self.cl_edits["kp_tau"])
        force_row.addWidget(QLabel("Ki_τ"))
        self.cl_edits["ki_tau"] = self._cl_edit(
            "力矩I增益（1/s）。0=纯P", text="0")
        force_row.addWidget(self.cl_edits["ki_tau"])
        force_row.addWidget(QLabel("trim增益"))
        self.cl_edits["trim_gain"] = self._cl_edit(
            "张力误差→位置微调增益 counts/N", text="50")
        force_row.addWidget(self.cl_edits["trim_gain"])
        force_row.addStretch(1)
        self._cl_force_row_w.setVisible(False)
        cl.addWidget(self._cl_force_row_w)

        # 张力模式（每缆独立张力 PI）
        self._cl_tension_row_w = QWidget()
        tens_row = QHBoxLayout(self._cl_tension_row_w)
        tens_row.setContentsMargins(0, 0, 0, 0)
        tens_row.addWidget(QLabel("f目标N"))
        self.cl_edits["f1_tgt"] = self._cl_edit(
            "C1 张力目标 N", text="2.0")
        tens_row.addWidget(self.cl_edits["f1_tgt"])
        self.cl_edits["f2_tgt"] = self._cl_edit(
            "C2 张力目标 N", text="2.0")
        tens_row.addWidget(self.cl_edits["f2_tgt"])
        self.cl_edits["f3_tgt"] = self._cl_edit(
            "C3 张力目标 N", text="2.0")
        tens_row.addWidget(self.cl_edits["f3_tgt"])
        tens_row.addWidget(QLabel("Kp_f"))
        self.cl_edits["kp_f"] = self._cl_edit(
            "张力P增益 counts/N", text="10")
        tens_row.addWidget(self.cl_edits["kp_f"])
        tens_row.addWidget(QLabel("Ki_f"))
        self.cl_edits["ki_f"] = self._cl_edit(
            "张力I增益 counts/(N·s)。0=纯P", text="10")
        tens_row.addWidget(self.cl_edits["ki_f"])
        tens_row.addStretch(1)
        self._cl_tension_row_w.setVisible(False)
        cl.addWidget(self._cl_tension_row_w)

        # 张紧模式（零空间预紧单旋钮，τ 守恒）
        self._cl_tight_row_w = QWidget()
        tight_row = QHBoxLayout(self._cl_tight_row_w)
        tight_row.setContentsMargins(0, 0, 0, 0)
        tight_row.addWidget(QLabel("张紧N"))
        self.cl_edits["t_tgt"] = self._cl_edit(
            "目标预紧程度 N（沿零空间方向的张力分量，三缆一起紧/松）", text="5.0")
        tight_row.addWidget(self.cl_edits["t_tgt"])
        tight_row.addWidget(QLabel("Kp_t"))
        self.cl_edits["kp_t"] = self._cl_edit(
            "张紧P增益 counts/N", text="50")
        tight_row.addWidget(self.cl_edits["kp_t"])
        tight_row.addWidget(QLabel("Ki_t"))
        self.cl_edits["ki_t"] = self._cl_edit(
            "张紧I增益 counts/(N·s)。0=纯P", text="10")
        tight_row.addWidget(self.cl_edits["ki_t"])
        tight_row.addStretch(1)
        self._cl_tight_row_w.setVisible(False)
        cl.addWidget(self._cl_tight_row_w)

        # 公共行（三力控模式共享：方向符号 / trim 限幅）
        self._cl_force_common_row_w = QWidget()
        fcommon_row = QHBoxLayout(self._cl_force_common_row_w)
        fcommon_row.setContentsMargins(0, 0, 0, 0)
        fcommon_row.addWidget(QLabel("trim方向"))
        self.cl_edits["trim_sign"] = self._cl_edit(
            "trim→张力方向，逐电机逗号分隔（+1=counts增大⇒该缆张力增大，−1=反向）。\n"
            "修正口径（2026-10-29 更正）：三台 counts↑=收绳 → 全 +1。\n"
            "三种力控模式共用；换接线后请点动复核（+100c 看该缆张力升/降）；\n"
            "错填=正反馈飞车（上电前务必核对）",
            text="1,1,1")
        fcommon_row.addWidget(self.cl_edits["trim_sign"])
        fcommon_row.addWidget(QLabel("trim限幅"))
        self.cl_edits["max_trim"] = self._cl_edit(
            "位置微调限幅 counts", text="3000")
        fcommon_row.addWidget(self.cl_edits["max_trim"])
        fcommon_row.addStretch(1)
        self._cl_force_common_row_w.setVisible(False)
        cl.addWidget(self._cl_force_common_row_w)

        # 边界行（三力控模式共用）：逐缆 f 界 + 张紧 t 界 + 双向力矩 τ 界。
        # 留空=0=不启用（t_min/t_max/τr/τp）；fmax 为力控 f_max 唯一来源
        # （观测台守卫框独立服务位置模式观测，互不干扰）。
        self._cl_bound_row_w = QWidget()
        brow = QHBoxLayout(self._cl_bound_row_w)
        brow.setContentsMargins(0, 0, 0, 0)
        brow.addWidget(QLabel("fmin"))
        self.cl_edits["f_min"] = self._cl_edit(
            "逐缆张力下限 N（TDA 分配下界；松绳告警仍由观测台守卫负责）", text="0.5")
        brow.addWidget(self.cl_edits["f_min"])
        brow.addWidget(QLabel("fmax"))
        self.cl_edits["fmax_f"] = self._cl_edit(
            "逐缆张力上限 N（力控过载停环阈值，唯一来源；观测台守卫框只管观测）", text="30")
        brow.addWidget(self.cl_edits["fmax_f"])
        brow.addWidget(QLabel("tmin"))
        self.cl_edits["t_min"] = self._cl_edit(
            "张紧 t 下限 N，低于则⚠预紧丢失（留空=不启用）", text="")
        brow.addWidget(self.cl_edits["t_min"])
        brow.addWidget(QLabel("tmax"))
        self.cl_edits["t_max"] = self._cl_edit(
            "张紧 t 上限 N：超出⚠预紧超限，且张紧目标被钳到此值（留空=不启用）", text="")
        brow.addWidget(self.cl_edits["t_max"])
        brow.addWidget(QLabel("τr上限"))
        self.cl_edits["tau_r_max"] = self._cl_edit(
            "τ ROLL 目标钳制 ±N·m（力矩模式目标框自动压回界内；留空=不启用）", text="")
        brow.addWidget(self.cl_edits["tau_r_max"])
        brow.addWidget(QLabel("τp上限"))
        self.cl_edits["tau_p_max"] = self._cl_edit(
            "τ PITCH 目标钳制 ±N·m（同上）", text="")
        brow.addWidget(self.cl_edits["tau_p_max"])
        brow.addStretch(1)
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
        self.cl_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.cl_btn.clicked.connect(self._toggle_closed_loop)
        cl.addWidget(self.cl_btn)
        self.cl_status = QLabel("未启动（先「载入标定」并勾选「模型前馈」）")
        self.cl_status.setObjectName("muted")
        cl.addWidget(self.cl_status)
        return box

    @staticmethod
    def _cl_edit(tooltip: str, text: str = "0") -> QLineEdit:
        e = QLineEdit(text)
        e.setToolTip(tooltip)
        e.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhLatinOnly)
        e.setMinimumHeight(28)
        return e

    def _cl_fval(self, key: str, default: float, lo: float, hi: float):
        try:
            v = float(self.cl_edits[key].text().strip().replace("−", "-"))
        except ValueError:
            return default
        return max(lo, min(hi, v))

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
                     "force_tau_roll_tgt", "force_tau_pitch_tgt",
                     "force_tau_roll_meas", "force_tau_pitch_meas", "force_alpha",
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
        self.plot_timer = QTimer(self)
        self.plot_timer.setTimerType(Qt.PreciseTimer)
        self.plot_timer.timeout.connect(self._timed_slot("plot", self._plot_tick))
        self.plot_timer.start(PLOT_INTERVAL_MS)
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
        self._ramp_timer.timeout.connect(self._on_ramp_tick)
        # 使能准入确认轮询。
        self._admit_timer = QTimer(self)
        self._admit_timer.timeout.connect(self._on_admit_poll)
        # 负反馈闭环 100Hz。
        self._cl_timer = QTimer(self)
        self._cl_timer.timeout.connect(self._cl_tick)

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
        self._stop_closed_loop("断开连接", hold=False, popup=False)
        if self.rx_thread is not None:
            if self.armed:
                self.rx_thread.send(build_stop_cmd())
                self.armed = False
            # 恢复全开，避免官方上位机后续连接时缺遥测流。
            restore = (bytes([PROTOCOL_HEADER, 1 + 1 + 4, CMD_UPLINK_MASK]) +
                       struct.pack(">I", UPLINK_MASK_ALL_PERIODIC) + bytes([0xFF]))
            self.rx_thread.send(restore)
            self.rx_thread.stop_event.set()
            # 不再同步等 2 s：串口写阻塞时会把 GUI 一起拖死。
            self.rx_thread.join(timeout=0.3)
            self.rx_thread = None
        self.connected = False
        self.armed = False
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
                self.status_info = payload
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
                pen=pg.mkPen(ch.color, width=1),
                name=ch.name,
                # 点数由 _update_plot 自己保峰抽稀控制（见 peak_decimate）；
                # 再让 pyqtgraph 自动降采样只会多一遍 O(n) 处理，白花时间。
                downsample=1,
                autoDownsample=False,
            )
        elif not checked and ch.curve is not None:
            self.plot.removeItem(ch.curve)
            ch.curve = None
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
        budget = 1000.0 / max(5.0, PLOT_HZ)
        cur = getattr(self, "_pts_per_px", 2.0)
        if ema > budget * 0.55 and cur > 0.25:
            cur = max(0.25, cur * 0.85)      # 超预算：更快地降
        elif ema < budget * 0.30 and cur < 3.0:
            cur = min(3.0, cur * 1.05)       # 富余：慢慢加回去
        self._pts_per_px = cur

    def _update_plot(self) -> None:
        self._plot_frames = getattr(self, "_plot_frames", 0) + 1
        tail = float(self.window_combo.currentText().rstrip("s"))
        self._visible_series = {}
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
        self.empty_plot_text.setVisible(not self._visible_series)
        # 每帧重复 enableAutoRange 会反复触发自动量程重算；只在勾选状态变化时开一次。
        if self.yauto_check.isChecked() and not getattr(self, "_yauto_on", False):
            self._yauto_on = True
            self.plot.getViewBox().enableAutoRange(axis=ViewBox.YAxis, x=False)
        if self.xauto_check.isChecked() and self._latest_t is not None:
            # 示波器滚动：X 锁定为 [最新-窗口, 最新]
            vb = self.plot.getViewBox()
            vb.disableAutoRange(axis=ViewBox.XAxis)
            vb.setXRange(max(0.0, self._latest_t - tail), self._latest_t, padding=0)

    def _on_plot_mouse_moved(self, pos) -> None:
        if not hasattr(self, "_visible_series"):
            return
        vb = self.plot.getPlotItem().vb
        if not self.plot.sceneBoundingRect().contains(pos):
            self.cursor_label.setText("")
            return
        mouse_pt = vb.mapSceneToView(pos)
        self.vLine.setPos(mouse_pt.x())
        self.hLine.setPos(mouse_pt.y())
        lines = []
        for name, (t, v) in list(self._visible_series.items())[:5]:
            if t.size == 0:
                continue
            # t 已按时间升序：二分定位比 nanargmin 全量扫描快两个数量级。
            idx = int(np.searchsorted(t, mouse_pt.x()))
            if idx >= t.size:
                idx = t.size - 1
            elif idx > 0 and abs(t[idx - 1] - mouse_pt.x()) < abs(t[idx] - mouse_pt.x()):
                idx -= 1
            val = v[idx]
            if not math.isnan(val):
                lines.append(f"{name}: {val:.1f}")
        txt = f"x={mouse_pt.x():.2f}s" + "\n" + "\n".join(lines)
        self.cursor_label.setText(txt)
        view_range = vb.viewRange()
        self.cursor_label.setPos(view_range[0][0], view_range[1][0])

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
        if checked:
            self._yauto_on = True
            vb.enableAutoRange(axis=ViewBox.YAxis, x=False)
        else:
            self._yauto_on = False
            vb.disableAutoRange(axis=ViewBox.YAxis)

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
        for j in ((axis,) if axis in (16, 17) else (16, 17)):
            self._set_baseline_from_current(j)
        if self.cl_enabled and self._cl_mode == "position":
            # 运行中重新归零：读数平移了，前馈参考与 origin 必须一起跟（否则
            # 稳态按 s/(1−kp) 偏出去）。等价于"从现在这个姿态重新起算"。
            for m in SERVO_TARGETS:
                v = self.channels[f"m{m}_abs"].buf.last()
                if v is not None and not math.isnan(v):
                    self._motor_origin[m] = int(v)
            self._cl_ref_pose = self._wrist_pose_now()
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
        if self.armed:
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

    def _on_enable_direct(self) -> None:
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
        if self._send_bytes(build_reset_cmd()):
            self.estop_latched = False
            self._set_arm_light()
            self._ctrl_status("已发送 RESET（清 E-STOP 锁存/可恢复故障，舵机断扭）")

    def _on_admit_poll(self) -> None:
        """使能后确认 P4 真正进入 RUN_DIRECT，否则显示拒绝原因。"""
        self._admit_poll += 1
        info = self.status_info
        # 直控到位后 P4 会自动 RUN_DIRECT_DONE 回 IDLE，因此以 control_mode 为准。
        if info.get("control_mode") == 1:
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
                QTimer.singleShot(150, self._finish_enable_start_again)
                return
            self._scope_retry = 0
            self._admit_timer.stop()
            self.armed = True
            self.estop_latched = False
            self._set_arm_light()
            # 使能不再重标零位（2026-11-02 用户 BUG 报告；10-29 诊断亦指出使能
            # 确认恰逢上电噪声峰值、是最糟的归零时机）：已有基准（📐 设置或
            # 布局恢复）保持不动；仅基准缺失时自动零一次并落盘防重启丢失。
            auto_zeroed = False
            for j in (16, 17):
                if self.angle_baseline[j] is None:
                    self._set_baseline_from_current(j)
                    auto_zeroed = True
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
                base = self._soft_limit_base(motor)
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
            reason = info.get("direct_reject", 0)
            state = info.get("state")
            if state == 0 and self.estop_latched:
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
        targets = list(self.last_servo_abs_all or [0] * 30)
        online = self.status_info.get("servo_online", 0)
        for i in range(len(targets)):
            if not online >> i & 1:
                targets[i] = 0
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
        QTimer.singleShot(150, lambda m=mask, t=targets: self._finish_enable_start(m, t))

    def _finish_enable_start(self, mask: int, targets) -> None:
        ok = self._send_bytes(build_start_cmd())
        ok = self._send_bytes(build_motor_pos_abs_cmd(targets)) and ok
        if not ok:
            self._ctrl_status("使能发送失败")
            return
        self._enable_mask = mask
        self._admit_poll = 0
        self._admit_timer.start(200)

    def _finish_enable_start_again(self) -> None:
        """活动域重写后的重试 START（沿用当前实测位置，不重算 targets）。"""
        self._finish_enable_start(self._enabled_motor_mask(),
                                  list(self.last_servo_abs_all or [0] * 30))

    def _set_arm_light(self) -> None:
        self._refresh_motor_rows()
        if not self.armed:
            self._pending_target = None
        if self.armed:
            self.arm_light.setText("● 已使能 直控中")
            self.arm_light.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {AT.T('good')}; padding: 2px;")
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
        if not self._motor_enabled(motor):
            text = f"实际 {cur_txt}（☐ 未勾选，不下发命令）"
        elif self.armed:
            text = f"起点 {origin_txt}  实际 {cur_txt}  目标 {tgt_txt}  累计 {off_txt}"
        else:
            text = f"实际 {cur_txt}（未使能）"
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
        if not self.ramp_check.isChecked() or abs(tgt - start) <= self._step() * 2:
            if self._send_bytes(build_motor_pos_abs_one_cmd(motor, tgt)):
                self.targets[motor] = tgt
                self._safety("DIRECT", motor=motor, target=tgt, delta=tgt - start)
            return
        self._ramp_state[motor] = {"target": tgt, "next_due": 0.0}
        if not self._ramp_timer.isActive():
            self._ramp_timer.start(50)

    # ---------- 多电机直控统一出口 ----------
    def _send_direct_targets(self, outs: dict[int, int], why: str) -> bool:
        """多电机直控统一出口：**一帧 0xD3 批量下发**，绝不逐电机连发 0xDE。

        根因（2026-11-03 实机"松绳只有一根动"）：固件
        upperApplySingleMotorTarget() 每帧都 pending_direct_generation+1 并把
        pending_direct_motor_mask 覆盖成**单电机位**；状态机处理排队事件时用
        pendingDirectCommandMatches(generation) 过滤，只有**最新代际**那帧被接受。
        上位机在同一毫秒连发 3 帧 0xDE → 前两帧代际已过期被丢弃 → 只有一根绳动。
        批量帧一帧含全部目标，天然原子，力控/闭环本来就走这条路。
        """
        clean = {int(m): int(v) for m, v in outs.items() if self._motor_enabled(m)}
        if not clean:
            return False
        if not self._send_motor_batch(clean):
            self._warn_batch_skip(f"{why}：批量下发失败")
            return False
        for m, out in clean.items():
            self.targets[m] = out
        self._safety(why, outs=clean)
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

    def _on_ramp_tick(self) -> None:
        """50ms 一拍推进斜坡：**一拍一帧批量**（多电机逐帧 0xDE 会被固件
        代际合并，只有最后一台生效——"只有一根绳动"的另一个来源）。

        2026-11-03 用户定案：直控斜坡**不做张力检测**（张力保护只在闭环）。
        """
        now = time.monotonic()
        step = max(1, int(self.ramp_rate_spin.value() * 0.05))
        active = False
        outs = {}
        done = []
        for motor, st in list(self._ramp_state.items()):
            if not self._motor_enabled(motor):   # 中途取消勾选：剩余分步作废
                del self._ramp_state[motor]
                continue
            if now < st["next_due"]:
                active = True
                continue
            cur = self.targets.get(motor)
            pos = cur if cur is not None else self._soft_limit_base(motor)
            delta = st["target"] - pos
            move = max(-step, min(step, delta))
            nxt = pos + move
            outs[motor] = nxt
            st["next_due"] = now + 0.05
            st["_next"] = nxt
            if abs(st["target"] - nxt) < 1:
                done.append(motor)
            else:
                active = True
        if outs:
            if not self._send_direct_targets(outs, "RAMP"):
                self._ramp_state.clear()
                self._ramp_timer.stop()
                return
            for motor in outs:
                self._update_motor_info(motor)
        for motor in done:
            self._ramp_state.pop(motor, None)
        if not active and not self._ramp_state:
            self._ramp_timer.stop()

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
        base_val = self.channels[f"m{motor}_abs"].buf.last()
        base = self.targets[motor] if base_val is None or math.isnan(base_val) else int(base_val)
        cur = self.targets[motor] if self.targets[motor] is not None else base
        tgt = cur + delta
        self._send_motor_target(motor, tgt)
        self._ctrl_status(f"M{motor} → {tgt:+d} (Δ{delta:+d})", log=False)

    def _send_manual_target(self, motor: int, edit) -> None:
        """输入语义：整数 N = 从【当前位置】相对走 N（无软件限位，仅斜坡限速）。"""
        if self.cl_enabled:
            self._reject("手动目标", "闭环运行中：先停止闭环再手动",
                         recheck=lambda: ("闭环运行中：先停止闭环再手动"
                                          if self.cl_enabled else None))
            return
        text = edit.text().strip().replace("−", "-").replace("＋", "+")
        if not text:
            self._reject("手动目标",
                         f"M{motor}：请输入相对当前位置的位移（如 500 或 -300）")
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
        base = self._motor_pos_now(motor)
        self._send_motor_target(motor, base + rel)
        self._ctrl_status(f"M{motor} 当前 {base:+d} 相对 {rel:+d} → {base + rel:+d}")

    # ---------- 张力链（ZNSV 变送器直连：观测台 = 唯一 UI，驱动直持串口） ----------
    def _toggle_tension_port(self) -> None:
        """观测台「连接」：直连变送器并启动张力轮询（节奏由 TENSION_POLL_HZ=250 锚定）；已连则断开。

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
            self.tension_status.setText(f"张力：连接失败（{exc}）")
            return
        self._tension_sensor = sensor
        self._tension_port_name = f"{port}@{baud}"
        self._tension_poll_timer.setInterval(1)   # 起连先 1ms，之后由 _tension_poll 按需排程
        self._tension_poll_timer.start()
        self._tension_status_refresh()

    def _tension_poll(self) -> None:
        """按需排程驱动 ZnsvTransmitter 状态机；新 8 通道帧 → _tension_feed。

        定时器不再固定 1kHz 空转（2026-11-03）：传输中保持 1ms 让字节及时读走，
        空闲期按 driver.next_poll_delay() 精确排到下一个请求时隙。这样唤醒次数
        约减半，采样率不变——实测把间隔直接拉到 2ms 会在 RTT>2ms 时把 250Hz
        掉到 167Hz（完成检测被量化），见 tools/perf/probe_tension_poll_rate.py。
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
        """停轮询、关串口、复位按钮与状态行。观测台未开时控件为 None，须防 AttributeError。"""
        self._tension_poll_timer.stop()
        sensor, self._tension_sensor = self._tension_sensor, None
        if sensor is not None:
            sensor.disconnect()
        if self.tension_btn is not None:
            self.tension_btn.setText("连接")
        if self.tension_status is not None:
            note = f"（{reason}）" if reason else ""
            self.tension_status.setText(f"张力：已断开{note}")

    def _tension_feed(self, raws) -> None:
        """每帧回调：按当前通道映射 × 系数 → _on_tension_sample（守卫/τ/CSV 自动接上）；
        同时记 8 通道原始帧与三缆张力历史（观测台走势图用）。"""
        try:
            fvals = [raws[ch - 1] * TENSION_N_PER_RAW[i]
                     for i, ch in enumerate(self._tension_ch_map)]
        except IndexError:
            return   # 映射越界：丢帧保运行（映射来自 UI 下拉，1..8 恒合法，防御性保留）
        self._tension_raws_last = tuple(raws)
        zero = self._tension_zero
        self._tension_feed_count += 1
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
        self._tension_ch_map[cable_idx] = ch
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
        self.tension_status.setText(f"张力：已排队 CH{ch} 零点校准（须空载，帧间隙发送）")

    def _tension_tare_ch(self, ch: int) -> None:
        sensor = self._tension_sensor
        if sensor is None or not sensor.connected:
            self.tension_status.setText("张力：请先连接变送器")
            return
        sensor.submit_channel_command(ch, 2, f"CH{ch} 去皮")
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
        self.tension_status.setText("张力：已排队 全部去皮归零")

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
        last = self._tension_last
        age = f"{(time.monotonic() - last[0]) * 1000:.0f}ms" if last is not None else "—"
        temp = s.temp_c
        chs = "/".join(f"CH{c}" for c in self._tension_ch_map)
        extra = f"  ⚠{s.error}" if s.error else ""
        write = (f"  写:{s.last_write[0]}→{s.last_write[1]}" if s.last_write else "")
        self.tension_status.setText(
            f"张力：{self._tension_port_name} {chs}→C1/C2/C3"
            f"  龄{age} 累计{s.sequence} 超时{s.timeouts} 错帧{s.protocol_errors}"
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
                self._ctrl_status("🪢 恢复完成：三缆进界并稳定 300ms，"
                                  "闭环继续持有预紧（手动停止请按停止闭环）",
                                  log=False)
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
                              math.radians(roll_deg + dr),
                              math.radians(pitch_model_deg(pitch_deg) + dp))
        if ev.flags & TENSION_OVERLOAD:
            cables = "+".join(f"C{i+1}" for i, v in enumerate(ev.overload) if v)
            self._stop_closed_loop(f"张力过载 {cables} ≥ {cfg.f_max_n:g}N")
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
                            "tight": 2, "force": 3}.get(self._cl_mode, -1))
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

    def _load_wrist_calib(self, quiet: bool = False) -> None:
        """载入 wrist_calib.json -> self.wrist_calib；失败显式提示原因。

        quiet=True 供启动自动载入：不写状态行，免得盖掉开机提示。
        """
        data = load_named_json("wrist_calib.json")
        if not data:
            self.cl_calib_label.setText("标定：读取失败/不存在（先跑识别脚本 --write 生成）")
            return
        calib, err = parse_wrist_calib(data)
        if calib is None:
            self.wrist_calib = None
            self.cl_calib_label.setText(f"标定：无效 — {err}")
            return
        self.wrist_calib = calib
        k = calib.k_counts_per_m
        d = calib.zero_offset_deg
        # k 是**结构常数**（绕线半径 5 mm、4096 counts/圈 → 4096/(2π·0.005)=130380 c/m），
        # 不是拟合结果；2026-11-10 用户确认"K 就是那个值、固定"。旧文案一律标"草稿：
        # 预估/未识别"，把正确值说成没标定，已改正。符号另属方向约定，用 ±|k| 判定。
        nominal = all(abs(abs(v) - 130380.0) < 1.0 for v in k)
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
            + ("（标称 k：绕线半径 5mm + 4096 c/圈，固定值）" if nominal
               else "（已识别）") + f"  {sign_txt}"
            + (f"<br><b style='color:#f87171'>{warn}</b>" if warn else ""))
        if warn and not quiet:
            self._ctrl_status(f"⚠ 符号自检：{warn}")
        if not quiet:
            self._ctrl_status(
                "📥 已载入腕部标定：位置环两种结构都可用（%s）；"
                "需与「trim方向」满足 sign(trim_sign)=−sign(k)" % sign_txt)

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
        """当前位姿的几何 R 求值。

        返回 (roll_deg, pitch_deg, WristModelOut, roll_rad, pitch_rad) | None——
        rad 为 θ_model（已加 δ），供 positive_null_direction 等复用。
        """
        pose = self._wrist_pose_now()
        if pose is None:
            return None
        roll_deg, pitch_deg = pose
        dr, dp = (self.wrist_calib.zero_offset_deg
                  if self.wrist_calib is not None else (0.0, 0.0))
        rr = math.radians(roll_deg + dr)
        pr = math.radians(pitch_model_deg(pitch_deg) + dp)
        out = wrist_eval(rr, pr)
        if not out.math_valid:
            return None
        return roll_deg, pitch_deg, out, rr, pr

    # ---------- 自动慢扫掠（闭环目标三角波；标定录数用） ----------
    def _sweep_key(self) -> str:
        return "roll_tgt" if self.sweep_axis.currentIndex() == 0 else "pitch_tgt"

    def _on_sweep_toggled(self, on: bool) -> None:
        if not on:
            self._ctrl_status("扫掠已停（目标保持当前值）")
            return
        try:
            self._sweep_val = float(
                self.cl_edits[self._sweep_key()].text().strip().replace("−", "-"))
        except ValueError:
            self._sweep_val = 0.0
        self._sweep_dir = 1.0 if self._sweep_val <= 0 else -1.0
        self._sweep_phase = 0.0   # 正弦从相位 0 重新起算
        self._sweep_ts = None     # 下一拍按标称步长起算
        if not self.cl_enabled:
            self._ctrl_status("扫掠已就绪：启动闭环后开始走波形（三角=录标定 / 正弦=跟随测试）")
        else:
            self._ctrl_status("扫掠运行中：目标框被自动改写，取消勾选停止")

    def _on_sweep_axis_changed(self, _index: int) -> None:
        """扫掠中切轴：按新轴目标框重新播种 + 相位归零（2026-11-10 修复）。"""
        try:
            self._sweep_val = float(
                self.cl_edits[self._sweep_key()].text().strip().replace("−", "-"))
        except ValueError:
            self._sweep_val = 0.0
        self._sweep_dir = 1.0 if self._sweep_val <= 0 else -1.0
        self._sweep_phase = 0.0
        self._sweep_ts = None

    def _sweep_tick(self, dt: float | None = None) -> None:
        """20Hz：闭环运行且勾选扫掠时推进所选轴目标波形（±幅值内）。

        三角波：按速度°/s 线性往返（录标定用，慢到准）。
        正弦波：目标 = A·sin(2πf·t)，A=「幅值°」框（默认跟随限幅）、f=频率框、
        相位从勾选时刻起算。峰值速度需求 = A·2πf——超过每拍限幅折算的速度
        上限（max_step_f×100Hz）就会削顶/滞后，正是带宽测试要观察的现象。

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
        amp = min(self.sweep_amp.value(), lim)
        if self.sweep_wave_combo.currentIndex() == 1:      # 正弦波
            self._sweep_phase = (self._sweep_phase
                                 + 2.0 * math.pi * self.sweep_freq.value() * dt)
            self._sweep_phase %= 2.0 * math.pi
            v = amp * math.sin(self._sweep_phase)
        else:                                              # 三角波（原有）
            v = self._sweep_val + self._sweep_dir * self.sweep_speed.value() * dt
            if v >= amp:
                v, self._sweep_dir = amp, -1.0
            elif v <= -amp:
                v, self._sweep_dir = -amp, 1.0
        self._sweep_val = v
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
        if self._cl_mode == "position" and self.wrist_calib is None:
            # 2026-11-10：位置环两种结构都要标定——前馈+PID 用 k·Δl 做前馈，
            # 纯PID 也要 k 与 R 当"角度→counts"的换算（J = −k·R）。
            # 没有标定时输出恒等于基准，启动时 targets 也等于基准，变更抑制会把
            # 每一帧都滤掉——现象就是「点了启动，一动不动」。宁可直接拒绝。
            return ("位置模式需要标定：先点「📥 载入标定」"
                    "（前馈与角度→counts 换算都要 k 和 R）")
        if self._cl_mode in ("force", "tension", "tight"):
            last = self._tension_last
            if last is None or (time.monotonic() - last[0]) > 0.5:
                return "力控启动失败：无新鲜张力数据（先在观测台连接张力串口）"
            # 参数合法性按模式各自校验（(0,0) 占位快检；逐拍还有真位姿检查）
            pre = {"force": lambda: self._force_params_v2(0.0, 0.0),
                   "tension": lambda: self._tension_params(),
                   "tight": lambda: self._tight_params(0.0, 0.0, quiet=True)}[
                self._cl_mode]()
            if pre is None:
                return "力控启动失败：力控参数非法（含 trim方向格式）"
        motors = self._enabled_motors()
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
        auto_zeroed = False
        for j in (16, 17):
            if self.angle_baseline[j] is None:
                self._set_baseline_from_current(j)
                auto_zeroed = True
        # 这次启动做了自动归零 → 立即落盘，保证重启可恢复（BUG1）；
        # 已有基准（含 _load_layout 恢复的）不动、不覆盖。
        if auto_zeroed:
            self._save_layout()
        if self._cl_mode == "position":
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
            # 2026-11-10 修复①续：前馈参考必须和 origin 同一个姿态（启动瞬间的读数）。
            # 否则前馈按"零位→目标"算、origin 却在别的姿态，稳态偏 −θ_e/(1+kp)。
            self._cl_ref_pose = self._wrist_pose_now()
            # 2026-11-10 修复②：空框=走默认值（死区 0.3° 等），界面上看不出来。
            # 启动时把生效值写回框里，所见即所算。
            for key, default in (("kp", 0.6), ("ki", 0.0), ("kd", 0.0),
                                 ("deadband", 0.3), ("limit", 25.0),
                                 ("max_step_f", 5.0)):
                e = self.cl_edits.get(key)
                if e is not None and not e.text().strip():
                    e.setText(f"{default:g}")
            self._pos_pid_state.reset()     # PID 状态每轮从零起（积分/微分不跨轮）
        if self._cl_mode in ("force", "tension", "tight"):
            # 位置基准 = 电机**实测**当前位置（不是上次指令）；按缆序映射
            # （与 _apply_force_step 同序，MOTOR_FOR_CABLE 换序时基准跟着换）。
            # 旧实现取 targets（上次指令），但力控下发不写 targets，重启会把
            # 基准退回力控前的旧目标 → 第一拍目标跳变（trim 被整段丢掉）。
            self._force_base = [self._motor_pos_now(m) for m in MOTOR_FOR_CABLE]
            self._force_state.reset()
            self._tension_state.reset()
            self._tight_state.reset()
            self._force_trim = [0.0, 0.0, 0.0]
            self._force_need_send = True   # 首拍把 base+0 发下去，先按住当前位置
        # 本轮闭环实际驱动的电机快照（运行中改勾选会先停闭环，见 _on_cable_enable_toggled）
        motors = self._enabled_motors()
        self._cl_motor_on = frozenset(motors)
        self.cl_enabled = True
        self.cl_btn.setText("■ 停止闭环")
        self.cl_btn.setStyleSheet(
            f"font-weight: bold; padding: 6px; color: white; background-color: {AT.T('good')};")
        self._refresh_motor_rows()   # 点动/输入框/Go 按勾选×使能×闭环统一收口
        # 起点可能刚被刷新 → 参数缓存（含 origin）必须立刻失效，否则首拍仍用旧起点，
        # 会先朝旧位置走几拍（≤5 拍 × max_step）再被拉回来。
        self._cl_param_cache = None
        self._cl_timer.start(10)  # 100Hz（与 P4 内环 100Hz、队列排空 100Hz 对齐）
        self._apply_run_prio()    # 跑环即降档：主图 3:1、表格/观测台 15Hz
        self._cl_tick_ts = None  # 首拍 dt 用默认 0.01
        if self._cl_mode == "force":
            mode = "力矩控制"
        elif self._cl_mode == "tension":
            mode = "张力控制"
        elif self._cl_mode == "tight":
            mode = "张紧控制"
        else:
            # 手填系数行已删（2026-11-03）：位置模式 = 前馈+PID 或 纯PID
            mode = "位置·" + self._pos_loop_name()
        off = [m for m in SERVO_TARGETS if m not in self._cl_motor_on]
        scope_note = f"，驱动 {self._motor_list_text(motors)}"
        if off:
            scope_note += f"，未勾选 {self._motor_list_text(off)} 不下发"
            if self._cl_mode == "position":
                scope_note += "（缺绳纠偏不全，盯紧软限位）"
        sign_warn = self._sign_invariant_note()
        self._ctrl_status(f"✅ 闭环运行（{mode}{scope_note}）：改目标框实时跟踪，停止请按急停或停止闭环"
                          + (f"  ⚠ {sign_warn}" if sign_warn else ""))
        _fmn, _fmx, _ = self._effective_flimits()
        # origins 落进安全日志：位置环的绝对目标 = origin + k·Δl，出问题先查这三个起点
        _log = dict(mode=self._cl_mode, motors=list(motors),
                    origins={m: self._motor_origin.get(m) for m in SERVO_TARGETS},
                    fmin=_fmn, fmax=_fmx)
        if sign_warn:
            _log["sign_warn"] = sign_warn
        if self._cl_mode == "position":
            _log["pos_loop"] = "ff_pid" if self._pos_loop_is_ff() else "pid_only"
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

    def _stop_closed_loop(self, reason: str, *, hold: bool = True,
                          popup: bool = True) -> None:
        """停止闭环。默认当场"刹住"（hold=True）：丢队列 + 抢占下发保持当前位。

        急停/断开时传 hold=False：那两条路径自己会发 0xCD（断力矩），
        若再发一帧"保持当前位"等于把刚断的力矩又按回去。
        popup=True 且停止的是一键紧绳会话（_tighten_cl_active）→ 弹窗告知
        停止原因（2026-11-09 用户需求：恢复中被过载/越界/丢数据打断要弹窗）。
        用户主动路径（手动停止/急停/切模式/勾选变更/断开/紧绳回滚）传
        popup=False——操作者已知原因，不再打扰；回滚有自己的专属弹窗。
        """
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
        self._cl_ref_pose = None             # 前馈参考只在本轮有效（下次启动重取）
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
        self.cl_enabled = False
        self._apply_run_prio()       # 停环恢复全速（主图 33FPS、表格 30Hz、观测台 20Hz）
        self._want_closed_loop = False
        self.cl_btn.setText("▶ 启动闭环")
        self.cl_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._refresh_motor_rows()   # 输入框/Go/点动按勾选×使能恢复
        self._finalize_calib_rec()   # 闭环停止即收尾落盘（若在记录）
        self.cl_status.setText(f"已停止（{reason}）")
        self._ctrl_status(f"闭环已停止：{reason}")
        self._safety("CL_STOP", reason=reason)
        if was_tighten:
            self._notify_cl_stop(reason)     # 记账完毕、状态已收敛，再弹窗

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
        mode = ("position", "tension", "tight", "force")[index]
        if mode == self._cl_mode:
            return
        if self.cl_enabled:
            self._stop_closed_loop("切换控制模式", popup=False)   # 运行中切模式 → 先停
        self._cl_mode = mode
        self._apply_cl_mode_visibility()
        self._save_layout()

    def _apply_cl_mode_visibility(self) -> None:
        """分模式显示切换。力控三模式隐藏角度目标/参数/标定/手填行，
        各自显示专属参数行 + 共用 trim方向/限幅/fmin 行。"""
        force = self._cl_mode in ("force", "tension", "tight")
        if getattr(self, "_cl_tgt_row_w", None) is None:
            return
        self._cl_tgt_row_w.setVisible(not force)
        self._cl_par_row_w.setVisible(not force)
        self._cl_model_row_w.setVisible(not force)
        self.cl_calib_label.setVisible(not force)
        self._cl_force_row_w.setVisible(self._cl_mode == "force")
        self._cl_tension_row_w.setVisible(self._cl_mode == "tension")
        self._cl_tight_row_w.setVisible(self._cl_mode == "tight")
        self._cl_force_common_row_w.setVisible(force)
        self._cl_bound_row_w.setVisible(force)
        if force:
            self.sweep_check.setChecked(False)      # 扫掠是位置模式专属
            self.sweep_check.setEnabled(False)
        else:
            self.sweep_check.setEnabled(True)

    # ---------- 位置环两种结构（2026-11-10） ----------
    def _pos_loop_is_ff(self) -> bool:
        """当前位置环是不是「前馈+PID」（False = 纯PID 增量式）。"""
        combo = getattr(self, "pos_loop_combo", None)
        return True if combo is None else combo.currentIndex() == 0

    def _pos_loop_name(self) -> str:
        return "前馈+PID" if self._pos_loop_is_ff() else "纯PID"

    def _on_pos_loop_changed(self, index: int) -> None:
        """切换位置环结构：运行中先停环（要换的是控制结构，不能热切）。"""
        if self.cl_enabled:
            self._stop_closed_loop("切换位置环结构", popup=False)
        self._pos_pid_state.reset()
        self._cl_param_cache = None        # origin/增益快照跟着失效
        self._ctrl_status(
            "位置环 = 前馈+PID（模型绳长前馈 + 关节 PID，绝对式）"
            if index == 0 else
            "位置环 = 纯PID（无前馈，增量式：基准=实测位置）")
        self._save_layout()

    def _force_geo(self, roll, pitch):
        """当前位姿的 (wrist_eval, n̂)，带 0.1° 网格缓存（三力控模式共用）。

        角度加 δ（与张力守卫/τ 观测同一条 θ_model 链）。R 无效返回 None。"""
        dr, dp = (self.wrist_calib.zero_offset_deg
                  if self.wrist_calib is not None else (0.0, 0.0))
        rr = math.radians(roll + dr)
        pr = math.radians(pitch_model_deg(pitch) + dp)
        key = (round(roll + dr, 1), round(pitch_model_deg(pitch) + dp, 1))
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
            if widget is not None:
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

    def _force_trim_sign(self):
        """trim方向框 → [3]±1 | None（非法 None=参数拒绝启动）。"""
        try:
            sign_txt = self.cl_edits["trim_sign"].text().strip().replace("，", ",")
            return [int(s.strip()) for s in sign_txt.split(",") if s.strip()]
        except (ValueError, KeyError, AttributeError):
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

    def _force_params_v2(self, roll, pitch):
        """读力控 UI + 动态 R(q) → WristForceV2Params | None（力矩模式）。"""
        geo = self._force_geo(roll, pitch)
        if geo is None:
            return None
        out, nd = geo
        r_max = self._cl_fval("tau_r_max", 0.0, 0.0, 100.0)
        p_max = self._cl_fval("tau_p_max", 0.0, 0.0, 100.0)
        tau_r = self._cl_fval("tau_roll", 0.0, -100.0, 100.0)
        tau_p = self._cl_fval("tau_pitch", 0.0, -100.0, 100.0)
        if r_max > 0.0:
            tau_r = max(-r_max, min(r_max, tau_r))
        if p_max > 0.0:
            tau_p = max(-p_max, min(p_max, tau_p))
        try:
            return WristForceV2Params(
                tau_d=(tau_r, tau_p),
                preload_n=self._cl_fval("preload", 5.0, 0.0, 100.0),
                kp=self._cl_fval("kp_tau", 100.0, 0.0, 10000.0),
                ki=self._cl_fval("ki_tau", 0.0, 0.0, 10000.0),
                trim_gain=self._cl_fval("trim_gain", 50.0, 0.0, 10000.0),
                trim_sign=self._force_trim_sign(),
                max_trim=self._cl_fval("max_trim", 3000.0, 1.0, 50000.0),
                f_max=self._force_fmax(),
                f_min=self._effective_flimits()[0],
                deadband=0.01,
                r_m=out.r_m, null_dir=nd,
                max_step=self._cl_fval("max_step_f", 5.0, 0.1, 2000.0))
        except (ValueError, KeyError):
            return None

    def _clamp_per_tick(self, outs: dict[int, int]) -> dict[int, int]:
        """闭环**每拍限幅**：与力控三模式共用同一个 `max_step_f`。

        力控模式每拍增量由 `_incr_step(..., max_step)` 限幅；位置模式的输出是
        绝对目标，所以这里换算成"每拍变化 ≤ max_step_f"，两种模式对舵机的
        实际限制才一致（100Hz 下 5 counts/拍 = 500 counts/s）。
        """
        if not outs or not self._safety_on():
            return outs
        slew = int(self._cl_fval("max_step_f", 5.0, 0.1, 2000.0))
        limited = {}
        for m, out in outs.items():
            prev = self.targets.get(m)
            limited[m] = out if prev is None else max(prev - slew, min(prev + slew, int(out)))
        return {m: v for m, v in limited.items() if v != self.targets.get(m)}

    def _tension_params(self):
        """读力控 UI → WristTensionParams | None（张力模式，每缆独立）。"""
        try:
            return WristTensionParams(
                f_target=(self._cl_fval("f1_tgt", 2.0, 0.0, 50.0),
                          self._cl_fval("f2_tgt", 2.0, 0.0, 50.0),
                          self._cl_fval("f3_tgt", 2.0, 0.0, 50.0)),
                kp=self._cl_fval("kp_f", 10.0, 0.0, 10000.0),
                ki=self._cl_fval("ki_f", 10.0, 0.0, 10000.0),
                max_step=self._cl_fval("max_step_f", 5.0, 0.1, 2000.0),
                trim_sign=self._force_trim_sign(),
                max_trim=self._cl_fval("max_trim", 3000.0, 1.0, 50000.0),
                f_max=self._force_fmax(),
                deadband=0.05)
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
        t_min_req = fmin_eff / min(nd)
        t_max_allow = fmax_eff / max(nd)
        t_min = self._cl_fval("t_min", 0.0, 0.0, 200.0)
        t_max = self._cl_fval("t_max", 0.0, 0.0, 200.0)
        if t_min > 0.0 and t_max > 0.0 and t_max <= t_min:
            return None
        t_tgt = self._cl_fval("t_tgt", 5.0, 0.0, 200.0)
        if t_max > 0.0:
            t_tgt = min(t_tgt, t_max)
        if t_tgt < t_min_req:
            if not quiet:
                self._ctrl_status(
                    f"张紧：t={t_tgt:g}N 低于可行下界 {t_min_req:.2f}N"
                    "（fmin/min(n̂)，再低会有缆达不到 fmin）", log=False)
            return None
        if t_tgt > t_max_allow:
            if not quiet:
                self._ctrl_status(
                    f"张紧：t={t_tgt:g}N 超出可行上界 {t_max_allow:.2f}N"
                    "（fmax/max(n̂)，再高会有缆超 fmax）", log=False)
            return None
        try:
            return WristTightParams(
                t_target=t_tgt,
                kp=self._cl_fval("kp_t", 50.0, 0.0, 10000.0),
                ki=self._cl_fval("ki_t", 10.0, 0.0, 10000.0),
                trim_sign=self._force_trim_sign(),
                max_trim=self._cl_fval("max_trim", 3000.0, 1.0, 50000.0),
                f_max=fmax_eff,
                deadband=0.05,
                null_dir=nd,
                max_step=self._cl_fval("max_step_f", 5.0, 0.1, 2000.0),
                f_min=fmin_eff)
        except (ValueError, KeyError):
            return None

    def _cl_tick_force(self, roll: float, pitch: float) -> None:
        """100Hz 力矩环：τ 外环 PI → TDA 分配 f_d → 腱张力内环 PI → 位置 trim。

        注意命名（2026-11-10 校正）：这是「TDA + 腱空间力内环 + 关节力矩外环」，
        **不是**论文 §7 的 P⁻ᵀ 关节空间解耦律；R·Rᵀ 耦合仍在（见 COMPARE 文档 §4.1）。
        """
        p = self._force_params_v2(roll, pitch)
        if p is None:
            self._stop_closed_loop("力控：参数非法或该位姿 R(q) 无效")
            return
        if abs(roll) > 30.0 or pitch < -30.0 or pitch > 50.0:
            self._stop_closed_loop(
                f"力控：关节越界 ROLL{roll:+.1f}° PITCH{pitch:+.1f}°")
            return
        last = self._tension_last
        if last is None:
            self._stop_closed_loop("力控：张力数据丢失")
            return
        age_ms = (time.monotonic() - last[0]) * 1000.0
        trim, flags, alpha = wrist_force_v2_step(p, self._force_state, last[1],
                                                 age_ms, self._cl_dt, tda_solve)
        if flags & FORCE_OVERLOAD:
            self._stop_closed_loop(
                "力控：张力过载 [" + "/".join(f"{v:.1f}" for v in last[1])
                + f"] N > f_max={p.f_max:g}")
            return
        if flags & FORCE_TDA_INFEASIBLE:
            self._stop_closed_loop("力控：TDA 不可行（该位姿无全正预紧或超界）")
            return
        if trim is None:
            self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
            if self._cl_tick_count % 6 == 0:
                self.cl_status.setText("力控：张力数据过期 → 冻结（电机保持）")
            return
        # 力控曲线通道：α + τ 目标（曲线由样本入口统一推实测 τ）
        now_rel = self._latest_t if self._latest_t is not None else 0.0
        self.channels["force_alpha"].buf.append(now_rel, alpha)
        tau = self._tau_meas(roll, pitch, last[1])   # 与张力/张紧模式同一入口（含几何缓存）
        tau_r = tau[0] if tau else 0.0
        tau_p = tau[1] if tau else 0.0
        self.channels["force_tau_roll_tgt"].buf.append(now_rel, p.tau_d[0])
        self.channels["force_tau_pitch_tgt"].buf.append(now_rel, p.tau_d[1])
        self._apply_force_step(trim, p.max_trim)
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        if self._cl_tick_count % 6 == 0:
            fvals = last[1]
            tb = self._t_bound_note()
            self.cl_status.setText(
                "力矩控  τ=[%+.4f,%+.4f]→[%+.3f,%+.3f]N·m  f=[%s]N  trim=[%s]c%s"
                % (tau_r, tau_p, p.tau_d[0], p.tau_d[1],
                   "/".join(f"{v:.2f}" for v in fvals),
                   "/".join(f"{v:+.0f}" for v in self._force_trim),
                   ("" if alpha >= 0.999 else f"  α={alpha:.2f}↓")
                   + (f"  {tb}" if tb else "")))

    def _tau_meas(self, roll, pitch, fvals):
        """实测关节力矩 τ=R(q)·f（N·m）——传感器只给张力，真实力矩经 R 换算。

        R 与力控律同一条 θ_model 链（含 δ、0.1° 缓存）；R 无效返回 None。"""
        geo = self._force_geo(roll, pitch)
        if geo is None:
            return None
        out, _ = geo
        return (sum(out.r_m[0][i] * fvals[i] for i in range(3)),
                sum(out.r_m[1][i] * fvals[i] for i in range(3)))

    def _warn_batch_skip(self, reason: str) -> None:
        """批量下发被跳过时限频提示，避免静默不动。"""
        now = time.monotonic()
        if now - getattr(self, "_batch_warn_t", 0.0) < 1.0:
            return
        self._batch_warn_t = now
        self._ctrl_status(f"批量下发跳过：{reason}", log=False)

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
        """三力控模式统一出口（增量式，2026-11-02 全模式定案）：

        out = 实测当前位置 + 本拍整数步长；max_trim 夹"相对进入点的累计
        行程"，堵转/丢帧时目标不漂。三根绳的目标合并成一帧 0xD3 下发。"""
        origins = [self._motor_origin.get(m) for m in MOTOR_FOR_CABLE]
        if any(o is None for o in origins):
            self._stop_closed_loop("缺少电机起点")
            return
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
            self.cl_status.setText(f"{name}：张力数据过期 → 冻结（电机保持）")

    def _cl_tick_tension(self, roll: float, pitch: float) -> None:
        """100Hz 张力控制：每缆独立张力 PI → 相对位置增量（out=实测位置+步长）。"""
        p = self._tension_params()
        if p is None:
            self._stop_closed_loop("张力控制：参数非法（含 trim方向格式）")
            return
        last = self._force_tick_prelude(roll, pitch, "张力控制")
        if last is None:
            return
        age_ms = (time.monotonic() - last[0]) * 1000.0
        trim, flags = wrist_tension_step(p, self._tension_state, last[1],
                                         age_ms, self._cl_dt)
        if flags & FORCE_OVERLOAD:
            self._stop_closed_loop(
                "张力控制：张力过载 [" + "/".join(f"{v:.1f}" for v in last[1])
                + f"] N > f_max={p.f_max:g}")
            return
        if trim is None:
            self._force_tick_freeze("张力控制")
            return
        tau = self._tau_meas(roll, pitch, last[1])   # 状态行用；曲线由样本入口统一推
        self._apply_force_step(trim, p.max_trim)
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        if self._cl_tick_count % 6 == 0:
            tb = self._t_bound_note()
            self.cl_status.setText(
                "张力控  f=[%s]→[%s]N  τ=R·f=[%+.4f,%+.4f]N·m  trim=[%s]c%s"
                % ("/".join(f"{v:.2f}" for v in last[1]),
                   "/".join(f"{v:.1f}" for v in p.f_target),
                   tau[0] if tau else 0.0, tau[1] if tau else 0.0,
                   "/".join(f"{v:+.0f}" for v in self._force_trim),
                   f"  {tb}" if tb else ""))

    def _cl_tick_tight(self, roll: float, pitch: float) -> None:
        """100Hz 张紧控制：预紧 f·n̂ 单 PI → Δf=e·n̂ 分配（τ 守恒）→ trim。"""
        p = self._tight_params(roll, pitch)
        if p is None:
            self._stop_closed_loop("张紧控制：参数非法或该位姿 R(q) 无效")
            return
        last = self._force_tick_prelude(roll, pitch, "张紧控制")
        if last is None:
            return
        age_ms = (time.monotonic() - last[0]) * 1000.0
        trim, flags = wrist_tight_step(p, self._tight_state, last[1],
                                       age_ms, self._cl_dt)
        if flags & FORCE_NO_NULL:
            self._stop_closed_loop("张紧控制：该位姿无全正预紧方向（不可张紧）")
            return
        if flags & FORCE_OVERLOAD:
            self._stop_closed_loop(
                "张紧控制：张力过载 [" + "/".join(f"{v:.1f}" for v in last[1])
                + f"] N > f_max={p.f_max:g}")
            return
        if trim is None:
            self._force_tick_freeze("张紧控制")
            return
        tau = self._tau_meas(roll, pitch, last[1])   # 状态行用；曲线由样本入口统一推
        self._apply_force_step(trim, p.max_trim)
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        if self._cl_tick_count % 6 == 0:
            t_meas = sum(last[1][j] * p.null_dir[j] for j in range(3))
            tb = self._t_bound_note()
            self.cl_status.setText(
                "张紧控  t=%.2f→%.1fN  τ=R·f=[%+.4f,%+.4f]N·m（守恒监视）  trim=[%s]c%s"
                % (t_meas, p.t_target,
                   tau[0] if tau else 0.0, tau[1] if tau else 0.0,
                   "/".join(f"{v:+.0f}" for v in self._force_trim),
                   f"  {tb}" if tb else ""))

    def _read_cl_params(self):
        """20Hz 节流读 UI 参数（原 _cl_tick 内联段原样搬移，100Hz→20Hz）。"""
        prm = WristControlParams()
        prm.kp = self._cl_fval("kp", 0.6, 0.0, 5.0)
        prm.ki = self._cl_fval("ki", 0.0, 0.0, 100.0)
        prm.kd = self._cl_fval("kd", 0.0, 0.0, 10.0)
        prm.deadband_deg = self._cl_fval("deadband", 0.3, 0.0, 10.0)
        prm.target_limit_deg = self._cl_fval("limit", 25.0, 1.0, 90.0)
        prm.i_limit_deg = prm.target_limit_deg   # 积分项最多等效"一个满量程角"
        prm.soft_limit = MOTOR_SOFT_LIMIT
        for i, m in enumerate(SERVO_TARGETS):
            origin = self._motor_origin.get(m)
            if origin is None:
                return None
            prm.origin[i] = origin
            kr, kp = self._cl_gain_vals.get(m, (0.0, 0.0))
            prm.gain_roll[i] = kr if self.cl_roll_check.isChecked() else 0.0
            prm.gain_pitch[i] = kp if self.cl_pitch_check.isChecked() else 0.0
        return prm

    def _cl_tick(self) -> None:
        """100Hz：读 J16/J17 -> 控制律（wrist_control_law）-> M27-29。

        控制数学全部在 wrist_control_law.py（无 UI 依赖，可逐行译成 C）。
        输出有变化抑制：目标不变时不重发，稳态零流量。
        P4 端 MotionControl 也是 100Hz，两者同拍。
        """
        now_pc = time.perf_counter()
        prev = getattr(self, "_cl_tick_ts", None)
        self._cl_tick_ts = now_pc
        self._cl_dt = 0.01 if prev is None else min(max(now_pc - prev, 0.001), 0.05)
        self._cl_beat = getattr(self, "_cl_beat", 0) + 1
        if self._cl_beat % 50 == 0:      # ~2Hz 取证快照（张力+目标+模式），出事可回放
            self._safety("CL_TICK")
        if not self.armed or not self.connected:
            self._stop_closed_loop("连接/使能丢失")
            return
        raw16 = self._enc_filt_raw[16]
        raw17 = self._enc_filt_raw[17]
        if raw16 is None or raw17 is None:
            self._stop_closed_loop("磁编无数据")
            return

        # 参数解析节流：字符串→float 每拍 13 次是纯浪费（100Hz 下每秒 1300 次）。
        # 参数框是低频变更对象，20Hz 刷新一次足够；真实输入变化最迟 50ms 生效。
        now_pc = time.perf_counter()
        if now_pc - getattr(self, "_cl_param_ts", 0.0) > 0.05 or not hasattr(self, "_cl_param_cache"):
            self._cl_param_ts = now_pc
            self._cl_param_cache = self._read_cl_params()
        prm = self._cl_param_cache
        if prm is None:
            self._stop_closed_loop("缺少电机起点")
            return
        roll = self._angle_delta(self._axis_deg(16, raw16), self.angle_baseline[16])
        pitch = self._angle_delta(self._axis_deg(17, raw17), self.angle_baseline[17])
        roll_tgt = self._cl_fval("roll_tgt", 0.0, -90.0, 90.0)    # 目标框即时生效（输入路径）
        pitch_tgt = self._cl_fval("pitch_tgt", 0.0, -90.0, 90.0)
        # 界面 pitch 的可用行程（按 PITCH_MODEL_SIGN 镜像）∩ 限幅：先夹一次，
        # 免得状态行显示"→+30"而实际被模型钳到 +25（所见即所算）。
        _lo_p, _hi_p = pitch_ui_range()
        _lo_p = max(_lo_p, -prm.target_limit_deg)
        _hi_p = min(_hi_p, prm.target_limit_deg)
        pitch_tgt = max(_lo_p, min(_hi_p, pitch_tgt))
        if self.cl_record_check.isChecked():
            self._record_calib_row(roll, pitch)

        # 张力守卫（阈值已填且有样本才判定；过载在内部停闭环）
        tens_ev, tens_txt = self._tension_guard(roll, pitch)
        tens_note = ""
        if tens_ev is not None:
            if tens_ev.flags & TENSION_STALE:
                tens_note = "  τ:样本过期"
            else:
                tens_note = (f"  τ={tens_ev.tau_roll_nm:+.3f}/{tens_ev.tau_pitch_nm:+.3f}N·m"
                             + (f" {tens_txt}" if tens_txt else "")
                             + ("  ⚠松绳" if tens_ev.flags & TENSION_SLACK else ""))
            if tens_ev.flags & TENSION_OVERLOAD:
                return
        elif tens_txt:
            tens_note = f"  {tens_txt}"   # 阈值非法守卫未启用：显式示警，不再静默

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
            self._stop_closed_loop("位置模式：未载入标定（k 与 R 缺失）")
            return
        ff = self._pos_loop_is_ff()
        ref = self._cl_ref_pose
        # 纯PID 的基准必须是**本拍实测 counts**（增量式语义，与三个力控模式同款）；
        # 前馈+PID 用 origin 当基准，不需要实测。
        base = None if ff else [self._motor_pos_now(m) for m in SERVO_TARGETS]
        outputs, flags = wrist_control_step_pid(
            prm, self.wrist_calib, self._pos_pid_state,
            roll, pitch_model_deg(pitch),
            roll_tgt, pitch_model_deg(pitch_tgt),
            self._cl_dt,
            feedforward=ff,
            base_counts=base,
            roll_enabled=self.cl_roll_check.isChecked(),
            pitch_enabled=self.cl_pitch_check.isChecked(),
            ref_roll_deg=(None if (not ff or ref is None) else ref[0]),
            ref_pitch_deg=(None if (not ff or ref is None)
                           else pitch_model_deg(ref[1])))
        if outputs is not None:
            now_rel = self._latest_t if self._latest_t is not None else 0.0
            raw = {}
            for m, out in zip(SERVO_TARGETS, outputs):
                if m in self._cl_motor_on:
                    raw[m] = out        # 未勾选的缆不推曲线（看着动、实际不下发）
                    self.channels[f"m{m}_tgt"].buf.append(now_rel, float(out))
            # 变更抑制 + 逐绳开关 + 与力控共用的每拍限幅
            outs = self._clamp_per_tick(raw)
            if self._send_motor_batch(outs):
                for m, out in outs.items():
                    self.targets[m] = out
        # outputs=None（非有限/几何无效/基准缺失）：保持上一目标不发送，本拍跳过
        self._cl_tick_count = getattr(self, "_cl_tick_count", 0) + 1
        if self._cl_tick_count % 6 == 0:
            warns = "".join(name for bit, name in CL_FLAG_NAMES if flags & bit)
            state = ("保持(硬错误)" if outputs is None
                     else "跟踪中" + (f" ⚠{warns}" if warns else ""))
            both = self.cl_roll_check.isChecked() and self.cl_pitch_check.isChecked()
            only = ("" if both else
                    (" [仅ROLL环]" if self.cl_roll_check.isChecked() else
                     (" [仅PITCH环]" if self.cl_pitch_check.isChecked() else
                      " [两轴均关：不动]")))
            self.cl_status.setText(
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

    def _release_step(self) -> None:
        """执行一步松绳（一帧 0xD3 批量；不看张力）。"""
        plan = getattr(self, "_release_plan", None)
        if not plan:
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
        QTimer.singleShot(self.RELEASE_STEP_MS, self._release_step)

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
        t_tgt_raw = self._cl_fval("t_tgt", 5.0, 0.0, 200.0)
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
            self.cl_mode_combo.setCurrentIndex(3)      # 力矩模式
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
            self.cl_mode_combo.setCurrentIndex(
                {"position": 0, "tension": 1, "tight": 2, "force": 3}[m])
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
        if self.connected and self.rx_thread is not None:
            drop = getattr(self.rx_thread, "drop_pending_tx", None)
            if callable(drop):
                dropped = drop()
            try:
                self.rx_thread.send(build_stop_cmd(), priority=True)
            except TypeError:
                # 兼容不支持 priority 的旧实现/测试替身；急停路径绝不允许抛异常
                self.rx_thread.send(build_stop_cmd())
        self._stop_closed_loop("急停", hold=False, popup=False)
        self._zero_timer.stop()
        self._ramp_timer.stop()
        self._admit_timer.stop()
        self._ramp_state.clear()
        self.armed = False
        self.estop_latched = True
        self._set_arm_light()
        for m in SERVO_TARGETS:
            self.targets[m] = None
        self._safety("ESTOP", dropped_tx=dropped)
        self._ctrl_status(
            f"⛔ 已发送 STOP（抢占下发，丢弃 {dropped} 帧待发指令）："
            f"固件关闭舵机力矩，腕部会松开/下垂")

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
        for ch in self.channels.values():
            ch.buf.clear()
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
            r_tgt = self._cl_fval("roll_tgt", 0.0, -999.0, 999.0)
            p_tgt = self._cl_fval("pitch_tgt", 0.0, -999.0, 999.0)
            if pose is not None:
                c = 16384.0 / 360.0  # counts/°
                r_raw = self._enc_filt_raw.get(16)
                p_raw = self._enc_filt_raw.get(17)
                rb = self._angle_baseline_raw.get(16)
                pb = self._angle_baseline_raw.get(17)
                r_traw = (rb if rb is not None else 0) + r_tgt * c
                p_traw = (pb if pb is not None else 0) + p_tgt * c
                r_now = f"{r_raw:.0f}" if r_raw is not None else "--"
                p_now = f"{p_raw:.0f}" if p_raw is not None else "--"
                self.cl_roll_now.setText(
                    f"ROLL  {pose[0]:+6.2f}°→{r_tgt:+6.2f}°  编码器 {r_now}→{r_traw:.0f}")
                self.cl_pitch_now.setText(
                    f"PITCH {pose[1]:+6.2f}°→{p_tgt:+6.2f}°  编码器 {p_now}→{p_traw:.0f}")
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
        for r, m in enumerate(SERVO_TARGETS):
            buf = self.channels[f"m{m}_abs"].buf
            _, hist = buf.series(BUFFER_SECONDS)
            vals = [
                buf.last(),
                float(np.nanmin(hist)) if hist.size else math.nan,
                float(np.nanmax(hist)) if hist.size else math.nan,
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
            if isinstance(data.get("tension_trend"), bool):
                self._tension_trend_on = data["tension_trend"]
            if isinstance(data.get("tension_len_folded"), bool):
                self._tension_len_folded = data["tension_len_folded"]
            mode = data.get("cl_mode")
            _MODE_IDX = {"position": 0, "tension": 1, "tight": 2, "force": 3}
            if mode in _MODE_IDX:
                self._cl_mode = mode
                self.cl_mode_combo.blockSignals(True)
                self.cl_mode_combo.setCurrentIndex(_MODE_IDX[mode])
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
            watch_saved = data.get("watch_params") or data.get("watch_last")
            if watch_saved:
                self._saved_watch_params = [k for k in watch_saved if isinstance(k, str)]
            if "cl_roll_on" in data:
                self.cl_roll_check.setChecked(bool(data["cl_roll_on"]))
            if "cl_pitch_on" in data:
                self.cl_pitch_check.setChecked(bool(data["cl_pitch_on"]))
            # 位置环结构：新键 pos_loop（0=前馈+PID / 1=纯PID）；
            # 旧布局只有 cl_model_on（布尔），按它迁移：True→前馈+PID、False→纯PID。
            pos_idx = data.get("pos_loop")
            if isinstance(pos_idx, int) and 0 <= pos_idx <= 1:
                self.pos_loop_combo.blockSignals(True)
                self.pos_loop_combo.setCurrentIndex(pos_idx)
                self.pos_loop_combo.blockSignals(False)
            elif isinstance(data.get("cl_model_on"), bool):
                self.pos_loop_combo.blockSignals(True)
                self.pos_loop_combo.setCurrentIndex(0 if data["cl_model_on"] else 1)
                self.pos_loop_combo.blockSignals(False)
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
            # 位置环结构随布局持久化（2026-11-10：取代旧的 cl_model_on 勾选）；
            # 旧键仍写一份（= 是否前馈），老版本读回时不会串味。
            "pos_loop": self.pos_loop_combo.currentIndex(),
            "cl_model_on": self._pos_loop_is_ff(),
            "cl_mode": self._cl_mode,
            # force_params 已删：力控参数全在 cl_edits，cl_params 一处覆盖。
            # 旧条目引用 f1_tgt 等已删字段，v2 升级后每次保存 KeyError 全局丢档
            # （2026-11-02 修复，用户报"重启都归 0"的真凶）。
            "tension_guard": dict(self._tension_guard_saved),
            "tension_link": dict(self._tension_link_saved),
            "tension_trend": self._tension_trend_on,
            "tension_len_folded": self._tension_len_folded,
            "tension_ch_map": list(self._tension_ch_map),
            "theme": AT.current_name(),
            "custom_theme": getattr(self, "_custom_theme", None),
            "angle_baseline_raw": {str(j): self._angle_baseline_raw[j] for j in (16, 17)},
            "ylimits": [self.ymin_spin.value(), self.ymax_spin.value()],
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

