"""绳驱二轴腕部几何核心 —— H7 包 wrist_r.c 的 Python 镜像（纯函数，无状态）。

无 Qt / 串口 / 全局可变状态 / 动态分配；STM32 侧直接复用 H7 包
src/wrist_r.c + src/wrist_default_model.c（本模块是其数学镜像，用于
PC 侧闭环与离线对拍，两者以同一组常数为基准）。

公式（算法说明.md 固件稳定投影式，与解析式 (22)(23) 等价）：
    v'1 = v1·cosθ − v2·sinθ
    v'2 = v1·sinθ + v2·cosθ
    d1 = v'1 − u1,  d2 = v'2 − u2
    s  = √(d1² + d2² + h²)          段长，m
    r  = (d1·v'2 − d2·v'1) / s      有效力臂 = −dl/dθ，m（rad 求导，SI 无量纲）

roll 三段用 θr 求值、pitch 三段用 θp；R = [[roll 行],[pitch 行]] × [C1,C2,C3]。
输入 rad；张力 N × R(m) → 关节力矩 N·m。

对应 C 结构（H7 包 wrist_r.h，已存在，勿重复实现）：
    wrist_compute_R_rad(&ctx, roll_rad, pitch_rad, &state)  → state.R_m[2][3]
"""
from __future__ import annotations

import math

ROLL = 0
PITCH = 1
N_CABLES = 3

# 每段五个几何投影数 (u1, u2, v1, v2, h)，单位 m。行=轴(ROLL/PITCH)，列=绳(C1/C2/C3)。
# 来源：H7 包 src/wrist_default_model.c（由 data/geometry_source.json 自动生成，
# geometry source_sha256=952e9c40…，C2/C3 P03/P04 已修正版，未经实机标定）。
# 禁止手改数值：几何变更须改 geometry_source.json 后由 tools/generate_model.py
# 重新生成，并重跑网格对拍测试。
SEG_PROJ_M = (
    (  # ROLL 行（θr 求值，P4–P5 段）
        (5.000000000e-04, -5.000000000e-03, 2.500000000e-03, -1.800000000e-02, 3.000000000e-03),   # C1
        (-2.700000000e-02, -5.000000000e-03, -3.250000000e-02, -1.800000000e-02, 4.000000000e-03),  # C2
        (2.700000000e-02, -5.000000000e-03, 3.750000000e-02, -1.800000000e-02, 4.000000000e-03),    # C3
    ),
    (  # PITCH 行（θp 求值，P6–P7 段）
        (6.000000000e-03, -5.800000000e-02, 3.247216913e-02, -5.300000002e-02, -1.785426117e-04),  # C1
        (6.000000000e-03, 1.200000000e-02, 2.200000000e-02, 1.250000000e-02, 2.835870693e-04),      # C2
        (6.000000000e-03, 1.200000000e-02, 2.200000000e-02, 1.249999999e-02, 6.283587067e-03),      # C3
    ),
)

# 工作角范围（deg）与低置信分区。低 pitch 区来自当前 CAD 几何关注区
# （C1 pitch 段在 −25° 仅 3.9 mm），不是数学奇异边界。
RANGE_DEG = {ROLL: (-25.0, 25.0), PITCH: (-25.0, 45.0)}
LOW_PITCH_LIMIT_DEG = -24.0

# 仅浮点数值退化下限（与 H7 numerical_min_length_m 一致），不是工程安全门限。
NUMERICAL_MIN_LENGTH_M = 1e-8

# 与 H7 wrist_default_config 一致的数值阈值（数值语义，非工程判定）。
_RELATIVE_RANK_EPS = 1e-6
_POSITIVE_NULL_EPS = 1e-6


def _segment_length_and_arm(theta_rad: float, axis: int, cable: int) -> tuple[float, float]:
    """单段求值：返回 (s 段长 m, r 有效力臂 m)。axis∈{ROLL,PITCH}，cable∈0..2。"""
    u1, u2, v1, v2, h = SEG_PROJ_M[axis][cable]
    c = math.cos(theta_rad)
    sn = math.sin(theta_rad)
    vp1 = v1 * c - v2 * sn
    vp2 = v1 * sn + v2 * c
    d1 = vp1 - u1
    d2 = vp2 - u2
    seg = math.sqrt(d1 * d1 + d2 * d2 + h * h)
    return seg, (d1 * vp2 - d2 * vp1) / seg


class WristModelOut:
    """wrist_eval 结果快照。r_m/s_m[轴][绳]；标志语义见 wrist_r.h。"""

    __slots__ = ("r_m", "s_m", "math_valid", "low_pitch_zone", "angle_in_range")

    def __init__(self) -> None:
        self.r_m = [[0.0] * N_CABLES, [0.0] * N_CABLES]
        self.s_m = [[0.0] * N_CABLES, [0.0] * N_CABLES]
        self.math_valid = False
        self.low_pitch_zone = False
        self.angle_in_range = False


def _axis_in_range(axis: int, theta_rad: float) -> bool:
    lo, hi = RANGE_DEG[axis]
    return math.radians(lo) <= theta_rad <= math.radians(hi)


def wrist_eval(roll_rad: float, pitch_rad: float) -> WristModelOut:
    """一次求值 6 段：R 矩阵 + 段长 + 诊断标志。输入 rad，输出 m。

    math_valid=False 时 r_m/s_m 内容不可用（调用方必须检查，不得沿用旧帧语义
    由调用方保证）。越界角度仍给出数学结果（离线可核对），angle_in_range=False。
    """
    out = WristModelOut()
    valid = True
    for axis, theta in ((ROLL, roll_rad), (PITCH, pitch_rad)):
        for cable in range(N_CABLES):
            s, r = _segment_length_and_arm(theta, axis, cable)
            out.s_m[axis][cable] = s
            out.r_m[axis][cable] = r
            if (not math.isfinite(s)) or (not math.isfinite(r)) or s <= NUMERICAL_MIN_LENGTH_M:
                valid = False
    out.math_valid = valid
    out.angle_in_range = _axis_in_range(ROLL, roll_rad) and _axis_in_range(PITCH, pitch_rad)
    out.low_pitch_zone = pitch_rad <= math.radians(LOW_PITCH_LIMIT_DEG)
    return out


def positive_null_direction(roll_rad: float, pitch_rad: float,
                            out_model: "WristModelOut | None" = None) -> tuple[float, float, float] | None:
    """单位右零空间方向（取向全正）；该姿态无全正内部预紧方向时返回 None。

    out_model：调用方已求过同一 (roll_rad, pitch_rad) 的 wrist_eval 结果时
    传入复用，省掉内部一次重复求值（张力守卫 100Hz 等高频路径用）；缺省
    行为与原版完全一致。

    与 H7 analyze_matrix 同口径：两行归一化叉积，秩阈/正分量阈 1e-6；
    存在 α≠0 使 α·n 全正当且仅当 n 全正或全负（允许统一翻转符号）。
    仅表示内部预紧方向存在，不表示任意张力/负载可实现。
    """
    out = out_model if out_model is not None else wrist_eval(roll_rad, pitch_rad)
    if not out.math_valid:
        return None
    a = out.r_m[ROLL]
    b = out.r_m[PITCH]
    na = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    nb = math.sqrt(b[0] * b[0] + b[1] * b[1] + b[2] * b[2])
    if na <= 0.0 or nb <= 0.0:
        return None
    a = [x / na for x in a]
    b = [x / nb for x in b]
    w = (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
    nw = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
    if (not math.isfinite(nw)) or nw <= _RELATIVE_RANK_EPS:
        return None
    n = (w[0] / nw, w[1] / nw, w[2] / nw)
    if all(x > _POSITIVE_NULL_EPS for x in n):
        return n
    if all(x < -_POSITIVE_NULL_EPS for x in n):
        return (-n[0], -n[1], -n[2])
    return None
