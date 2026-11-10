"""逐帧记录 P4/S3 原始载荷，并在 writer 线程生成无 UI 抽样的控制总表。

职责：解析控制 trace 原始帧并写入会话 CSV，同时产出可离线分析的控制总表。
线程：解析在调用线程执行，文件写入在记录 writer 线程执行。
输入：P4/S3 上行控制 trace 载荷、时间戳和会话目录。
输出：原始 trace CSV 与按关节展开的控制总表行。
状态所有权：只拥有本会话的记录缓冲和文件句柄，不拥有设备状态。
禁止依赖：禁止导入 Qt/UI 和串口通信实现，避免记录层反向依赖界面。
"""
from __future__ import annotations

from ..protocol import (
    PACKET_TYPE_CONTROL_TRACE, PACKET_TYPE_CONTROL_TRACE_DETAIL,
    MOTOR_COUNT, ENCODER_COUNT, split_p4_timestamp,
    parse_control_trace_packet, parse_control_trace_detail_packet,
)


class PacketRecorder:
    def __init__(self, write):
        self.write = write
        self.details = {}
        self.previous = None

    def _consume_detail(self, payload, stamp):
        fragment = parse_control_trace_detail_packet(payload)
        if fragment is None or stamp is None:
            return
        key = (stamp, fragment["sequence"])
        metadata = tuple(fragment[field] for field in ("servo_timestamp", "control_dt_us",
                         "servo_valid_mask", "recovery_applied_mask", "p4_trace_dropped"))
        entry = self.details.setdefault(key, {"metadata": metadata, "values": {}, "invalid": False})
        if entry["metadata"] != metadata:
            entry["invalid"] = True
        for motor, values in enumerate(fragment["values"], fragment["first_motor"]):
            if motor in entry["values"] and entry["values"][motor] != values:
                entry["invalid"] = True
            entry["values"][motor] = values
        while len(self.details) > 32:
            self.details.pop(next(iter(self.details)))

    def consume(self, source, packets, received_at):
        for packet_type, raw in packets:
            payload, stamp = split_p4_timestamp(packet_type, raw) if source == "p4" else (raw, None)
            self.write("packet_frames", {
                "host_time": received_at, "p4_time_ms": stamp,
                "source": source, "packet_type": packet_type, "payload_hex": raw.hex(),
            })
            if source != "p4":
                continue
            if packet_type == PACKET_TYPE_CONTROL_TRACE_DETAIL:
                self._consume_detail(payload, stamp)
                continue
            if packet_type != PACKET_TYPE_CONTROL_TRACE:
                continue
            trace = parse_control_trace_packet(payload)
            if trace is None or stamp is None:
                continue
            key = (stamp, trace["sequence"])
            entry = self.details.pop(key, None)
            detail = None
            if entry and not entry["invalid"] and len(entry["values"]) == MOTOR_COUNT:
                detail = dict(zip(("servo_timestamp", "control_dt_us", "servo_valid_mask",
                                   "recovery_applied_mask", "p4_trace_dropped"), entry["metadata"]))
                for index, field in enumerate(("actual_abs", "pid_counts", "recovery_counts")):
                    detail[field] = [entry["values"][motor][index] for motor in range(MOTOR_COUNT)]
            if key == self.previous:
                continue
            delta = (trace["sequence"] - self.previous[1]) & 0xFFFFFFFF if self.previous else 0
            row = {
                "host_time": received_at, "p4_time_ms": stamp,
                "control_trace_sequence": trace["sequence"], "target_token": trace["target_token"],
                "command_age_ms": (stamp - trace["target_accepted_ms"]) & 0xFFFFFFFF,
                "feedback_age_ms": (stamp - trace["encoder_timestamp_ms"]) & 0xFFFFFFFF,
                "trace_period_ms": (stamp - self.previous[0]) & 0xFFFFFFFF if self.previous else "",
                "trace_sequence_gap": max(0, delta - 1) if delta < 0x80000000 else 0,
                "motor_command_mask": f'0x{trace["motor_command_mask"]:08X}',
                "trace_detail_valid": int(detail is not None),
            }
            if detail:
                row.update({k: detail[k] for k in ("control_dt_us", "servo_valid_mask", "recovery_applied_mask", "p4_trace_dropped")})
                row["servo_feedback_age_ms"] = (stamp - detail["servo_timestamp"]) & 0xFFFFFFFF
            for i in range(ENCODER_COUNT):
                valid = bool(trace["valid_joint_mask"] & (1 << i))
                row.update({f"J{i:02d}_target_deg": trace["target_deg"][i],
                            f"J{i:02d}_current_deg": trace["actual_deg"][i] if valid else "",
                            f"J{i:02d}_current_valid": int(valid),
                            f"J{i:02d}_active": int(bool(trace["active_joint_mask"] & (1 << i)))})
            for i in range(MOTOR_COUNT):
                row[f"M{i:02d}_cmd_abs"] = trace["motor_command_abs"][i] if trace["motor_command_mask"] & (1 << i) else ""
                if detail:
                    for field in ("actual_abs", "pid_counts", "recovery_counts"):
                        row[f"M{i:02d}_{field}"] = detail[field][i] if detail["servo_valid_mask"] & (1 << i) else ""
            self.write("joint_wide", row)
            self.previous = key
