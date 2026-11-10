"""calibration_lut.py - MMHand Desktop 模块契约。

职责：校验单关节腱绳 LUT 并提取各执行器绝对行程区间。
线程：除 comm_layer 的串口收发线程外不主动创建 GUI 线程；共享状态必须按既有锁读取。
输入：P4 字节流、上层类型化命令、配置和持久化数据。
输出：线程安全的 HandModel 快照、协议帧、ACK 和后端操作结果。
状态所有权：通信对象拥有串口与解析缓存；HandModel 的写入只允许在核心同步边界内发生。
禁止依赖：禁止依赖 Qt/UI、app、ROS2 或 Replay 页面，禁止把控件和展示规则带入核心层。
"""
from __future__ import annotations

from .motor_mapping import MOTOR_TO_JOINT_INDEX
from .protocol import (
    DUAL_TENDON_JOINT_INDICES,
    TENDON_LUT_MAX_SAMPLES,
    tendon_lut_field,
)


def joint_calib_result_has_valid_tendon_lut(item, joint_idx: int) -> bool:
    """按当前电机映射校验单关节标定结果中的腱绳 LUT。"""
    if not isinstance(item, dict) or not bool(item.get("success", False)):
        return False
    if not bool(tendon_lut_field(item, "tendonLutValid", False)):
        return False
    try:
        count = int(tendon_lut_field(item, "tendonLutCount", 0))
    except (TypeError, ValueError):
        return False
    if count < 3 or count > TENDON_LUT_MAX_SAMPLES:
        return False
    expected_count = 2 if int(joint_idx) in DUAL_TENDON_JOINT_INDICES else 1
    expected_motors = [
        motor_idx
        for motor_idx, mapped_joint in enumerate(MOTOR_TO_JOINT_INDEX)
        if int(mapped_joint) == int(joint_idx)
    ]
    motors = tendon_lut_field(item, "tendonLutMotor", [])
    if len(expected_motors) != expected_count or not isinstance(motors, list):
        return False
    if len(motors) < 2:
        return False
    try:
        if any(int(motors[i]) != expected_motors[i] for i in range(expected_count)):
            return False
        if expected_count == 1 and int(motors[1]) != 0xFF:
            return False
    except (TypeError, ValueError):
        return False
    motor_abs = tendon_lut_field(item, "tendonLutMotorAbs", [])
    return bool(
        isinstance(motor_abs, list)
        and len(motor_abs) >= 2
        and all(
            isinstance(row, list) and len(row) >= count
            for row in motor_abs[:expected_count]
        )
    )


def joint_calib_result_tendon_lut_abs_ranges(
    item, joint_idx: int
) -> list[tuple[int, int, int]]:
    """返回有效 LUT 各执行器的 ``(motor, min_abs, max_abs)``。"""
    if not joint_calib_result_has_valid_tendon_lut(item, joint_idx):
        return []
    count = int(tendon_lut_field(item, "tendonLutCount", 0))
    motors = tendon_lut_field(item, "tendonLutMotor", [])
    motor_abs = tendon_lut_field(item, "tendonLutMotorAbs", [])
    actuator_count = 2 if int(joint_idx) in DUAL_TENDON_JOINT_INDICES else 1
    ranges: list[tuple[int, int, int]] = []
    try:
        for actuator in range(actuator_count):
            values = [int(value) for value in motor_abs[actuator][:count]]
            ranges.append((int(motors[actuator]), min(values), max(values)))
    except (TypeError, ValueError):
        return []
    return ranges
