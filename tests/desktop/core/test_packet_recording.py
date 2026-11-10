import csv
import struct
import time

from desktop.core.data_recording.packet_recorder import PacketRecorder
from desktop.core.data_recording.recorder import DataSessionRecorder
from desktop.core.data_recording.topic_schema import CSV_TOPIC_FILENAMES
from desktop.core.protocol import PACKET_TYPE_CONTROL_TRACE, PACKET_TYPE_CONTROL_TRACE_DETAIL, MOTOR_COUNT


def frames(sequence, stamp):
    base = (struct.pack(">7I", sequence, 2, stamp - 2, stamp - 1, 1, 1, (1 << MOTOR_COUNT)-1)
            + struct.pack(">21h", *range(21)) * 2 + struct.pack(f">{MOTOR_COUNT}i", *range(MOTOR_COUNT)))
    packets = []
    for first in range(0, MOTOR_COUNT, 27):
        count = min(27, MOTOR_COUNT - first)
        detail = (struct.pack(">6IBB", sequence, stamp - 3, 10000, (1 << MOTOR_COUNT)-1, 1, 0, first, count)
                  + b"".join(struct.pack(">ihh", 100+i, i, i) for i in range(first, first+count)))
        assert len(detail) + 8 <= 256
        packets.append((PACKET_TYPE_CONTROL_TRACE_DETAIL, detail + struct.pack(">I", stamp)))
    packets.append((PACKET_TYPE_CONTROL_TRACE, base + struct.pack(">I", stamp)))
    return packets


def test_five_frames_in_one_batch_have_five_original_timestamps():
    rows = []
    recorder = PacketRecorder(lambda topic, row: rows.append((topic, row)))
    packets = sum((frames(i + 1, 1000 + i * 10) for i in range(5)), [])
    recorder.consume("p4", packets, 1.0)
    joints = [r for t, r in rows if t == "joint_wide"]
    assert [r["p4_time_ms"] for r in joints] == [1000, 1010, 1020, 1030, 1040]
    assert len([r for t, r in rows if t == "packet_frames"]) == 15
    assert all(r["trace_detail_valid"] == 1 for r in joints)
    assert all(r["M00_actual_abs"] == 100 for r in joints)
    assert joints[-1]["trace_sequence_gap"] == 0


def test_old_firmware_missing_detail_gap_and_retry():
    rows = []
    recorder = PacketRecorder(lambda topic, row: rows.append((topic, row)))
    recorder.consume("p4", [frames(1, 1000)[-1], frames(3, 1020)[-1], frames(3, 1020)[-1]], 1)
    joints = [r for t, r in rows if t == "joint_wide"]
    assert len(joints) == 2
    assert joints[1]["trace_sequence_gap"] == 1
    assert joints[1]["trace_detail_valid"] == 0
    assert "M00_actual_abs" not in joints[1]


def test_stop_drains_batch_and_keeps_s3_payload(tmp_path):
    recorder = DataSessionRecorder()
    recorder.start(str(tmp_path), session_name="batch")
    recorder.record_packets("p4", sum((frames(i + 1, 1000 + i * 10) for i in range(5)), []))
    recorder.record_packets("s3", [(99, b"\x01\x02")])
    recorder.stop()
    with (tmp_path / "batch" / CSV_TOPIC_FILENAMES["joint_wide"]).open(encoding="utf-8-sig") as file:
        assert len(list(csv.DictReader(file))) == 5
    with (tmp_path / "batch" / CSV_TOPIC_FILENAMES["packet_frames"]).open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
        assert rows[-1]["source"] == "s3" and rows[-1]["payload_hex"] == "0102"


def test_periodic_flush_without_ten_rows(tmp_path):
    recorder = DataSessionRecorder()
    recorder.start(str(tmp_path), session_name="flush")
    try:
        recorder.record_packets("p4", frames(1, 1000))
        path = tmp_path / "flush" / CSV_TOPIC_FILENAMES["joint_wide"]
        deadline = time.monotonic() + 2
        found = False
        while time.monotonic() < deadline:
            with path.open(encoding="utf-8-sig") as file:
                found = len(list(csv.DictReader(file))) == 1
            if found:
                break
            time.sleep(0.02)
        assert found
    finally:
        recorder.stop()


def test_overflow_reports_incomplete_instead_of_discarding_oldest():
    recorder = DataSessionRecorder(max_queue=100)
    recorder._running = True
    recorder._selected_topics = {"event_log"}
    for i in range(101):
        recorder.write("event_log", {"detail": str(i)})
    assert not recorder.is_running()
    assert "overflow" in recorder.consume_error()
    assert recorder._queue.qsize() == 100
    assert recorder._queue.get_nowait()[1]["detail"] == "0"
