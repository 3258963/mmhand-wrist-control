"""点动叠加和 P4 过载停机，经过示波器的协议解码与收包队列。"""
import os
import struct
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import mmhand_scope as scope
from desktop.core import session_log


@pytest.fixture
def win(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(scope, "load_layout_json", lambda: {})
    monkeypatch.setattr(scope, "safety_log", lambda *a, **kw: None)
    monkeypatch.setattr(session_log, "close_session_log", lambda: None)
    w = scope.ScopeWindow(default_port="COM_TEST")
    w.connected = w.armed = True
    # 只使用解码和队列，不启动串口线程。
    w.rx_thread = scope.SerialRxThread("COM_TEST", w.rx_queue)
    w.last_servo_abs_all = [0] * 30
    w.targets = {27: 100, 28: 200, 29: 300}
    for m, pos in w.targets.items():
        w.channels[f"m{m}_abs"].buf.append(0, pos)
    yield w
    w.rx_thread = None
    w.close()
    app.processEvents()


def status(state, faults=0, pending=82, applied=82, reject=0):
    body = bytearray(84)
    body[:4] = bytes((state, int(state == 6), int(state == 6), 1))
    struct.pack_into(">I", body, 5, faults)
    struct.pack_into(">I", body, 17, 0x38000000)
    struct.pack_into(">I", body, 26, 0x38000000)
    struct.pack_into(">IIIIB", body, 67, 0, 0, pending, applied, reject)
    return bytes(body)


@pytest.mark.parametrize("jog_first", [True, False])
def test_repeated_2000_accumulates_and_obeys_ramp(win, jog_first):
    win.step_combo.setCurrentText("2000")
    win.ramp_check.setChecked(True)
    win.ramp_rate_spin.setValue(1000)
    win.target_edits[27].setText("2000")
    def press(jog):
        if jog:
            win._jog(27, 2000)
        else:
            win._send_manual_target(27, win.target_edits[27])

    press(jog_first)
    win._on_ramp_tick()
    press(not jog_first)
    assert win._ramp_state[27]["target"] == 4100
    for _ in range(79):
        win._on_ramp_tick()
    for pos in range(150, 4101, 50):
        targets = [0] * 27 + [pos, 200, 300]
        assert win.rx_thread.tx_queue.get_nowait() == scope.build_motor_pos_abs_cmd(targets)
    assert win.rx_thread.tx_queue.empty()
    assert not win._ramp_timer.isActive()


@pytest.mark.parametrize("fault_first", [True, False])
def test_latched_overload_disarms_and_cancels_motion(win, fault_first):
    win._jog(27, 2000)
    win.cl_enabled = True
    win._release_plan = {"items": []}
    win.rx_thread.send(scope.build_motor_pos_abs_cmd([100] * 30))
    loads = [0] * 30
    loads[27], loads[29] = 1000, -1000
    packets = [
        (scope.PACKET_TYPE_FAULT_STATUS, struct.pack(">I30h", 0x28000000, *loads)),
        (scope.PACKET_TYPE_SYSTEM_STATUS, status(0, faults=4, pending=194, reject=1)),
    ]
    for typ, body in packets if fault_first else reversed(packets):
        win.rx_thread._dispatch(typ, body)
        win._drain_queue()
    assert not win.armed and not win.cl_enabled
    assert not win._ramp_state and win._release_plan is None
    assert not win._ramp_timer.isActive()
    assert all(v is None for v in win.targets.values())
    assert win.status_info["direct_reject"] == 1
    assert "M27(+1000)" in win.arm_light.text()
    assert "M29(-1000)" in win.arm_light.text()
    win.target_edits[27].setText("2000")
    win._send_manual_target(27, win.target_edits[27])
    win._on_admit_poll()
    assert not win.armed and win._pending_target is None
    assert win.rx_thread.tx_queue.empty() and win.rx_thread.tx_priority.empty()


def test_normal_direct_done_allows_next_jog_but_fault_state_cannot_arm(win):
    win.armed = False
    win._admit_sent_at = time.monotonic() - 0.2
    win._prior_applied_generation = 81
    for body in (status(0), status(1, pending=81, applied=81), status(1, reject=1)):
        win.rx_thread._dispatch(scope.PACKET_TYPE_SYSTEM_STATUS, body)
        win._drain_queue()
        win._on_admit_poll()
        assert not win.armed
    win.rx_thread._dispatch(scope.PACKET_TYPE_SYSTEM_STATUS, status(1))
    win._drain_queue()
    win._on_admit_poll()
    assert win.armed
    win.ramp_check.setChecked(False)
    win._jog(27, 2000)
    assert win.rx_thread.tx_queue.get_nowait()[2] == 0xD3


def test_explicit_reenable_after_overload_only_holds_current_position(win):
    rx = win.rx_thread
    rx._dispatch(scope.PACKET_TYPE_SYSTEM_STATUS, status(0, faults=4, pending=194, reject=1))
    win._drain_queue()
    win.target_edits[27].setText("2000")
    win._send_manual_target(27, win.target_edits[27])
    assert rx.tx_queue.empty()

    win._on_enable_direct()
    assert rx.tx_queue.get_nowait() == scope.build_stop_cmd()
    assert rx.tx_queue.get_nowait() == scope.build_reset_cmd()
    assert rx.tx_queue.get_nowait() == scope.build_active_scope_cmd(0x38000000, 0, False)
    win._enable_delay.stop()
    win.last_servo_abs_all[27:] = [100, 200, 300]
    win._finish_enable_start()
    assert rx.tx_queue.get_nowait() == scope.build_start_cmd()
    assert rx.tx_queue.get_nowait() == scope.build_motor_pos_abs_cmd(win.last_servo_abs_all)
    win._admit_sent_at -= 0.2
    rx._dispatch(scope.PACKET_TYPE_SYSTEM_STATUS, status(1, pending=84, applied=84))
    win._drain_queue()
    win._on_admit_poll()
    assert win.armed and not win.cl_enabled
    assert not win._ramp_state and rx.tx_queue.empty()
