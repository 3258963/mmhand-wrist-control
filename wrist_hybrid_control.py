"""混合模式专用参数和 C1 张力 PID。角度 PID 复用现有控制律。"""

from dataclasses import dataclass
import math

from wrist_control_law import WristControlParams


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
    c1: C1TensionParams


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
    i_next = max(-params.i_limit, min(params.i_limit, state.i_counts + params.ki * error * dt))
    pd = params.kp * error - params.kd * state.force_rate
    pid_counts = tighten_sign * (pd + i_next)
    raw = pid_counts + ff_counts + state.residual
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
