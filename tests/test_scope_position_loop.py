"""位置环两种结构（前馈+PID / 纯PID）在 ScopeWindow 里的接线测试。

不起真串口：把 `_send_motor_batch` 换成记录器，只验证「哪条律、什么基准、
下发了什么」。重点验证三件事：
  1. 下拉框切结构 → `_cl_tick` 走不同的基准（origin vs 本拍实测）；
  2. 纯PID 误差为 0 时"原地保持"（不回 origin）；
  3. 两轴全关时不再假装在控（状态行明说"两轴均关"）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import time

import pytest

import mmhand_scope as scope
from wrist_control_law import WristCalib


class _FakeSerial:
    def __init__(self):
        self.frames = []
        self.tx_queue = __import__("queue").Queue()
        self.stop_event = __import__("threading").Event()

    def send(self, data, priority=False):
        self.frames.append(bytes(data))
        return True

    def join(self, timeout=None):
        return None


@pytest.fixture(scope="module")
def win():
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}      # 干净布局，不读用户存档
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = scope.ScopeWindow(default_port="COM_TEST")
    yield w
    w._admit_timer.stop()
    w._zero_timer.stop()
    w._ramp_timer.stop()
    w._cl_timer.stop()
    w.close()
    scope.load_layout_json = real_load
    app.processEvents()


def _prep(w, variant: int, measured=(1100, 2100, 3100), roll_tgt="0.0",
          max_step="500"):
    """把窗口摆到"闭环运行中、腕已偏离使能原点"的状态。"""
    w.connected = True
    w.armed = True
    w.rx_thread = _FakeSerial()
    w.last_servo_abs_all = [0] * 30
    w._cl_mode = "position"
    # 与 run_data/scope_exports/wrist_calib.json 一致：k=+130380（counts↑=放绳）。
    # 位置环方向由 J=−k·R 自动跟随，所以这里用出厂符号来测。
    w.wrist_calib = WristCalib([130380.0] * 3, [0.0, 0.0])
    w.pos_loop_combo.blockSignals(True)
    w.pos_loop_combo.setCurrentIndex(variant)
    w.pos_loop_combo.blockSignals(False)
    w._pos_pid_state.reset()
    w._cl_param_cache = None
    w._cl_param_ts = 0.0
    w._cl_tick_count = 0
    w._cl_tick_ts = None
    w._cl_motor_on = frozenset(scope.SERVO_TARGETS)
    w._motor_origin = {27: 1000, 28: 2000, 29: 3000}
    # 反馈：J16/J17 都在基准 0°（误差只由目标框决定）
    w._enc_filt_raw[16] = 8000.0
    w._enc_filt_raw[17] = 9000.0
    w.angle_baseline[16] = scope.ScopeWindow._axis_deg(16, 8000.0)
    w.angle_baseline[17] = scope.ScopeWindow._axis_deg(17, 9000.0)
    w._cl_ref_pose = (0.0, 0.0)
    # 电机实测（比使能原点各多 100 counts ⇒ 模拟启动后被挪动），
    # 上一帧指令仍停在 origin（真实场景：漂了但还没下发纠正）
    for m, v in zip(scope.SERVO_TARGETS, measured):
        w.channels[f"m{m}_abs"].buf.append(0.0, float(v))
        w.targets[m] = w._motor_origin[m]
    w.cl_edits["roll_tgt"].setText(roll_tgt)
    w.cl_edits["pitch_tgt"].setText("0.0")
    w.cl_edits["max_step_f"].setText(max_step)
    w.cl_edits["kp"].setText("0.6")
    w.cl_edits["ki"].setText("0")
    w.cl_edits["kd"].setText("0")
    w.cl_edits["deadband"].setText("0.3")
    w.cl_edits["limit"].setText("25")
    w._tension_last = None                   # 守卫不参与
    sent = {}
    w._send_motor_batch = lambda outs: (sent.update(outs), True)[1]
    w._clamp_per_tick = lambda raw: dict(raw)   # 这里不测限幅，直接看律的输出
    return sent


def test_ff_variant_base_is_origin(win):
    """前馈+PID：误差 0 时目标 = origin + k·Δl(0→0) = origin（绝对式基准）。"""
    sent = _prep(win, variant=0)
    win._cl_tick()
    assert sent, "应当有下发"
    assert (sent[27], sent[28], sent[29]) == (1000, 2000, 3000), sent


def test_pure_pid_base_is_measured(win):
    """纯PID：误差 0 时目标 = 本拍实测位置（原地保持，不回 origin）。"""
    sent = _prep(win, variant=1)
    win._cl_tick()
    assert sent, "应当有下发"
    assert (sent[27], sent[28], sent[29]) == (1100, 2100, 3100), sent


def test_pure_pid_moves_toward_target(win):
    """纯PID：+2° 目标 ⇒ C2 的 counts 增大、C3 减小（k>0=放绳约定下 C2 要放、C3 要收）。"""
    sent = _prep(win, variant=1, roll_tgt="2.0")
    win._cl_tick()
    assert sent[28] > 2100 and sent[29] < 3100, sent


def test_pure_pid_single_tick_step_is_bounded_by_kp(win):
    """纯PID 单拍位移 ≈ kp × 全行程（P-on-e，不是一拍到位）。"""
    sent = _prep(win, variant=1, roll_tgt="2.0")
    win._cl_tick()
    # 全行程 = |J|·2°≈？先算一拍的 kp=0.6 位移，应显著小于"全行程"
    full = abs(sent[28] - 2100)
    assert 0 < full < 200, sent          # 不可能一拍就走完 2°（约 70 counts）
    # 再和 kp=1.0 比较：应该更大
    sent2 = _prep(win, variant=1, roll_tgt="2.0")
    win.cl_edits["kp"].setText("1.0")
    win._cl_param_cache = None
    win._cl_tick()
    assert abs(sent2[28] - 2100) > full


def test_axis_both_off_says_so(win):
    """两个轴都取消：不再假装在控，状态行明说。"""
    _prep(win, variant=0)
    win.cl_roll_check.setChecked(False)
    win.cl_pitch_check.setChecked(False)
    for _ in range(7):
        win._cl_tick()
    assert "两轴均关" in win.cl_status.text(), win.cl_status.text()
    win.cl_roll_check.setChecked(True)
    win.cl_pitch_check.setChecked(True)


def test_switching_variant_while_running_stops_loop(win):
    """运行中切结构必须先停环（换的是控制结构，不能热切）。"""
    _prep(win, variant=0)
    win.cl_enabled = True
    win.pos_loop_combo.setCurrentIndex(1)
    assert win.cl_enabled is False
    assert "切换位置环结构" in win.cl_status.text()
    win.cl_enabled = False


def test_position_gate_requires_calib(win):
    """没标定时两种结构都拒启（k 与 R 是角度→counts 的唯一来源）。"""
    _prep(win, variant=1)
    win.wrist_calib = None
    reason = win._start_cl_gate_reason()
    assert reason and "标定" in reason, reason
