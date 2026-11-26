"""混合模式专用参数和复位绳张力 PID。角度 PID 复用现有控制律。"""

from dataclasses import dataclass
import math

from wrist_control_law import WristControlParams


def coupling_ratios(null_dir, return_cable=0):
    """复位绳与另外两根绳的稳态耦合比。以下以选择 C1 为例。

    ## 从 P 矩阵直接推出来的

    静力学：`τ = R·f`（R 为 2×3），内部预紧 `t = n̂ᵀf`，且
    `P = [R; n̂ᵀ]`、`f = P⁻¹·[τ; t]`，满足 `R·P⁻¹ = [I₂ 0]`、`n̂ᵀP⁻¹ = [0 0 1]`。

    对 `f = P⁻¹[τ;t]` 求「力矩不变、只改 t」的导数：

        ∂f/∂t = P⁻¹ 的第 3 列

    该列同时满足 `R·(∂f/∂t) = 0`（力矩不变）与 `n̂ᵀ(∂f/∂t) = 1`（t 变化 1）。
    两条约束把方向锁死 ⟹ **∂f/∂t = n̂ / (n̂ᵀn̂)**，取 |n̂|=1 即 `∂f/∂t = n̂`。

    于是「C1 每 +1 N，其余两缆跟着变多少」= 该方向对 f1 归一化：

        s = n̂ / n̂[0]   ⟹   s2 = n̂[1]/n̂[0],  s3 = n̂[2]/n̂[0]

    **不需要求逆**，也不需要 R：耦合比完全由零空间方向定。

    `n̂[0]` 本身就是「C1 在预紧方向里的份额」：
      · `n̂[0] → 1`：C1 几乎是纯预紧缆，加张力不产生力矩、不打扰 C2/C3（理想）；
      · `n̂[0] → 0`：C1 几乎纯造力矩，加 1 N 会逼出 C2/C3 几 N（恶劣）。

    Args:
        null_dir: 全正零空间方向 `(n1, n2, n3)`（可未归一化）
        return_cable: 所选复位绳的索引，0/1/2 对应 C1/C2/C3。

    Returns:
        所选绳的份额，以及另外两根绳按编号顺序相对所选绳的比值。
        所选绳的份额太小时返回 `None`。
    """
    try:
        values = tuple(float(null_dir[i]) for i in range(3))
        n1 = values[return_cable]
        n2, n3 = (value for i, value in enumerate(values) if i != return_cable)
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(v) for v in (n1, n2, n3)):
        return None
    if abs(n1) < 1e-9:
        return None
    return n1, n2 / n1, n3 / n1


def c1_share_of_preload(null_dir):
    """C1 的预紧份额 `|n̂[0]| / |n̂|`（0~1，越大越"纯预紧"）。"""
    c = coupling_ratios(null_dir)
    if c is None:
        return 0.0
    try:
        norm = math.sqrt(sum(float(v) ** 2 for v in null_dir[:3]))
    except (TypeError, ValueError, IndexError):
        return 0.0
    if norm <= 0.0:
        return 0.0
    return abs(float(null_dir[0])) / norm


@dataclass(frozen=True)
class C1TensionParams:
    target_n: float
    kp: float
    ki: float
    kd: float
    ff_gain: float
    max_step: int
    travel: int
    i_limit: float
    min_n: float
    max_n: float


@dataclass(frozen=True)
class HybridWristParams:
    angles: WristControlParams
    roll_target_deg: float
    pitch_target_deg: float
    c1: C1TensionParams  # 复位绳张力参数，沿用原存档字段口径
    return_cable: int = 0


class C1TensionState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.i_counts = 0.0
        self.residual = 0.0
        self.last_force = None
        self.force_rate = 0.0
        self.last_length = None


@dataclass(frozen=True)
class C1TensionOutput:
    counts: int
    pid_counts: float
    ff_counts: float
    step_limited: bool
    travel_limited: bool


def c1_tension_target(params: C1TensionParams, state: C1TensionState, *,
                      force_n: float, force_time: float, length_m: float,
                      counts: int, origin: int, spool_k: float,
                      dt: float) -> C1TensionOutput | None:
    """从本拍电机实测位置出发，合成张力 PID 和绳路变化补偿。"""
    low = max(-params.max_step, origin - params.travel - counts)
    high = min(params.max_step, origin + params.travel - counts)
    if low > high:
        return None

    # 微分只随新张力样本更新，改目标时不产生微分突跳。
    if state.last_force is not None:
        old_time, old_force = state.last_force
        sample_dt = force_time - old_time
        if sample_dt > 0.0:
            alpha = -math.expm1(-sample_dt / 0.05)
            rate = (force_n - old_force) / sample_dt
            state.force_rate += alpha * (rate - state.force_rate)
    state.last_force = (force_time, force_n)

    ff_counts = 0.0
    if state.last_length is not None:
        ff_counts = params.ff_gain * spool_k * (length_m - state.last_length)
    state.last_length = length_m

    error = params.target_n - max(0.0, force_n)
    if abs(error) <= 0.05:
        error = 0.0
    if error == 0.0 or params.ki == 0.0:
        state.i_counts = 0.0
    else:
        state.i_counts = max(-params.i_limit, min(params.i_limit, state.i_counts))
    tighten_sign = -1 if spool_k > 0.0 else 1
    i_next = max(-params.i_limit, min(params.i_limit, state.i_counts + params.ki * (error * dt)))
    pd = params.kp * error - params.kd * state.force_rate
    pid_counts = tighten_sign * (pd + i_next)
    raw = pid_counts + ff_counts + state.residual
    if not math.isfinite(raw):
        return None
    step_limited = abs(raw) > params.max_step
    travel_limited = not (origin - params.travel <= counts + raw <= origin + params.travel)

    # 仅在积分会把输出推得更远时冻结，保留反向退出饱和的能力。
    i_delta = tighten_sign * (i_next - state.i_counts)
    if (raw > high and i_delta > 0.0) or (raw < low and i_delta < 0.0):
        pid_counts -= i_delta
        raw -= i_delta
    else:
        state.i_counts = i_next
    bounded = max(low, min(high, raw))
    step = round(bounded)
    state.residual = bounded - step
    return C1TensionOutput(counts + step, pid_counts, ff_counts, step_limited, travel_limited)
