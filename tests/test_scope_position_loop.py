"""位置环（绳长前馈×k_ff + PI，每拍步长限幅）在 ScopeWindow 里的接线测试。

2026-11-23：`chord_from_fb` 恢复开启，前馈按 `k_ff`（0~1）缩放；用例固定
`k_ff=0.3`，期望值 = 实测 + 0.3·k·[l(θ*)−l(θ_now)] + J·δθ。

不起真串口：把 `_send_motor_batch` 换成记录器，只验证「什么基准、下发了什么」：
  1. 误差 0 → 前馈/ PI 都为 0 → 原地保持（不回 origin）；
  2. 每拍 = k_ff 份前馈 + PI，数值对上模型；
  3. kp=0 时只剩前馈；k_ff=0 且 kp=0 才完全不发；
  4. 两轴全关时状态行明说；
  5. 没标定拒启。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

from wrist_force_law import STALE_MS
import time

import pytest

import mmhand_scope as scope
from wrist_control_law import WristCalib
from wrist_model import PITCH, ROLL, wrist_eval


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


def _prep(w, measured=(1100, 2100, 3100), roll_tgt="0.0", max_step="500"):
    """把窗口摆到"闭环运行中、腕已偏离使能原点"的状态。"""
    w.connected = True
    w.armed = True
    w.rx_thread = _FakeSerial()
    w.last_servo_abs_all = [0] * 30
    w._cl_mode = "position"
    # 合成标定：三路同号（k=+130380，counts↑=放绳），只验证接线与方向跟随，
    # 与 run_data/scope_exports/wrist_calib.json 的真实逐路 k 无关。
    w.wrist_calib = WristCalib([130380.0] * 3, [0.0, 0.0])
    w._pos_pid_state.reset()
    w._cl_param_cache = None
    w._cl_param_ts = 0.0
    w._cl_tick_count = 0   # 与 __init__ 一致；真实路径靠 __init__/start 初始化（回归见 test_tick_without_preset）
    w._cl_tick_ts = None
    w._cl_motor_on = frozenset(scope.SERVO_TARGETS)
    w.cl_edits["k_ff"].setText("0.3")   # 前馈系数固定，用例里按 0.3 算期望
    w.cl_ff_check.setChecked(True)      # 前馈总开关默认开
    w._cl_snap = None                   # 强制 _cl_flag 读控件而不是旧快照
    w._motor_origin = {27: 1000, 28: 2000, 29: 3000}
    # 反馈：J16/J17 都在基准 0°（误差只由目标框决定）
    w._enc_filt_raw[16] = 8000.0
    w._enc_filt_raw[17] = 9000.0
    w.angle_baseline[16] = scope.ScopeWindow._axis_deg(16, 8000.0)
    w.angle_baseline[17] = scope.ScopeWindow._axis_deg(17, 9000.0)
    # 电机实测（比使能原点各多 100 counts ⇒ 模拟启动后被挪动），
    # 上一帧指令仍停在 origin
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


def test_zero_error_holds_measured(win):
    """误差 0：弦=0、δθ=0 ⇒ 目标就是本拍实测（不回 origin）。"""
    sent = _prep(win)
    win._cl_tick()
    assert sent, "应当有下发"
    assert (sent[27], sent[28], sent[29]) == (1100, 2100, 3100), sent


def test_moves_toward_target(win):
    """+2° 目标 ⇒ C2 的 counts 减小、C3 增大（方向随 k 的符号）。

    2026-11-19：UI/硬件 roll 与模型 roll 方向相反（`MODEL_AXIS_SIGN[ROLL] = -1`），
    所以 UI 的 +2° 对应模型 −2°，三缆方向随之镜像。本用例用合成标定
    k=+130380（全正，老写法的"counts↑=放绳"）。
    """
    sent = _prep(win, roll_tgt="2.0")
    win._cl_tick()
    assert sent[28] < 2100 and sent[29] > 3100, sent


def test_feedforward_scaled_matches_model(win):
    """每拍 = 实测 + k_ff·k·[l(θ*)−l(θ_now)] + J·(kp·e)，k_ff=0.3。

    前馈按系数缩放（模型不可信时只借一部分），限幅在 `_clamp_per_tick`
    （本用例把它 stub 成直通，只看律的输出）。
    """
    sent = _prep(win, roll_tgt="2.0")
    win.cl_edits["kp"].setText("0.3")
    win._cl_param_cache = None
    win._cl_tick()
    k = 130380.0
    kp = 0.3
    k_ff = 0.3
    m_t = wrist_eval(math.radians(-2.0), 0.0)
    m_f = wrist_eval(0.0, 0.0)
    e_deg = -2.0                      # UI +2° ⇒ 模型 −2°
    exp = []
    for i, base in enumerate((1100, 2100, 3100)):
        dl = m_t.s_m[ROLL][i] - m_f.s_m[ROLL][i]
        J = -k * m_f.r_m[ROLL][i] * math.pi / 180.0
        exp.append(base + k_ff * k * dl + J * (kp * e_deg))
    assert [sent[27], sent[28], sent[29]] == pytest.approx(exp, abs=1.0), sent


def test_pitch_control_direction_follows_target(win):
    """pitch 回原约定（`AXIS_SIGN[17]=-1`, `PITCH_MODEL_SIGN=+1`）：界面 +2° ⇒ 模型 +2°。"""
    sent = _prep(win, roll_tgt="0.0")
    win.cl_edits["pitch_tgt"].setText("2.0")
    win.cl_edits["kp"].setText("0.3")
    win._cl_param_cache = None
    win._cl_tick()
    k = 130380.0
    kp = 0.3
    k_ff = 0.3
    m_t = wrist_eval(0.0, math.radians(2.0))
    m_f = wrist_eval(0.0, 0.0)
    e_deg = 2.0
    exp = []
    for i, base in enumerate((1100, 2100, 3100)):
        dl = m_t.s_m[PITCH][i] - m_f.s_m[PITCH][i]
        J = -k * m_f.r_m[PITCH][i] * math.pi / 180.0
        exp.append(base + k_ff * k * dl + J * (kp * e_deg))
    assert [sent[27], sent[28], sent[29]] == pytest.approx(exp, abs=1.0), sent


def test_tick_without_preset_tick_count(win):
    """回归 2026-11-23：真实运行没有预置 `_cl_tick_count`，首拍不能抛异常。

    位置诊断记录曾在自增之前读 `self._cl_tick_count` → 首拍 AttributeError，
    控制线程当场退出（界面还显示运行中，只动一下）。
    """
    _prep(win, roll_tgt="2.0")
    del win._cl_tick_count          # 模拟真实启动：__init__ 给过，但这里强行抹掉
    win._cl_tick()                  # 必须不抛（用 getattr 兜底）
    assert win._cl_tick_count >= 0


def test_feedforward_switch_off_means_pure_pid(win):
    """取消「前馈」勾选 ⇒ 纯 PID：输出只剩 J·(kp·e)，与 k_ff 无关。"""
    sent = _prep(win, roll_tgt="2.0")
    win.cl_edits["kp"].setText("0.3")
    win.cl_ff_check.setChecked(False)
    win._cl_param_cache = None
    win._cl_tick()
    k = 130380.0
    kp = 0.3
    m_f = wrist_eval(0.0, 0.0)
    e_deg = -2.0
    exp = []
    for i, base in enumerate((1100, 2100, 3100)):
        J = -k * m_f.r_m[ROLL][i] * math.pi / 180.0
        exp.append(base + J * (kp * e_deg))
    assert [sent[27], sent[28], sent[29]] == pytest.approx(exp, abs=1.0), sent


def test_kp_zero_is_feedforward_only(win):
    """kp=0：只剩 k_ff 份前馈，步长仍非零；k_ff=0 时才是"什么都不动"。"""
    s_ff = _prep(win, roll_tgt="2.0")
    win.cl_edits["kp"].setText("0")
    win._cl_param_cache = None
    win._cl_tick()
    assert abs(s_ff[28] - 2100) > 10, s_ff
    s_zero = _prep(win, roll_tgt="2.0")
    win.cl_edits["kp"].setText("0")
    win.cl_edits["k_ff"].setText("0")
    win._cl_param_cache = None
    win._cl_tick()
    assert (s_zero[27], s_zero[28], s_zero[29]) == (1100, 2100, 3100), s_zero


def test_target_does_not_accumulate_when_measured_is_stuck(win):
    """实测不动时，目标也不能每拍 +max_step 一路累加（2026-11-23 现场）。

    限幅加在"本拍走多少"（out − 实测）上：step 恒被削到 max_step，
    目标 = 实测 + step 也就恒定；实测动起来目标才跟着走。
    """
    sent = _prep(win, roll_tgt="10.0", max_step="20")
    win._cl_tick()
    first = dict(sent)
    for _ in range(5):
        win._cl_tick()
    assert dict(sent) == first, (first, sent)
    for m, base in zip(scope.SERVO_TARGETS, (1100, 2100, 3100)):
        assert abs(sent[m] - base) <= 20, sent


def test_axis_both_off_says_so(win):
    """两个轴都取消：不再假装在控，状态行明说。"""
    _prep(win)
    win.cl_roll_check.setChecked(False)
    win.cl_pitch_check.setChecked(False)
    for _ in range(7):
        win._cl_tick()
    assert "两轴均关" in win.cl_status.text(), win.cl_status.text()
    win.cl_roll_check.setChecked(True)
    win.cl_pitch_check.setChecked(True)


def test_position_gate_requires_calib(win):
    """没标定就拒启（k 与 R 是角度→counts 的唯一来源）。"""
    _prep(win)
    win.wrist_calib = None
    reason = win._start_cl_gate_reason()
    assert reason and "标定" in reason, reason


def test_no_variant_switch_left(win):
    """旧的两档已移除：界面上不再有位置环结构下拉框。"""
    assert not hasattr(win, "pos_loop_combo")
    assert win._pos_loop_name() == "PID+前馈"


def test_default_calibration_when_file_missing(win, monkeypatch):
    """没有 wrist_calib.json 时用内建默认：k=−K_NOMINAL_ABS（trim方向=1,1,1）。"""
    monkeypatch.setattr(scope, "load_named_json", lambda name: None)
    win.cl_edits["trim_sign"].setText("1,1,1")
    win._load_wrist_calib(quiet=True)
    assert win.wrist_calib is not None
    for got, nom in zip(win.wrist_calib.k_counts_per_m, scope.K_NOMINAL_ABS):
        assert got == pytest.approx(-nom)
    assert win.wrist_calib.zero_offset_deg == [0.0, 0.0]


def test_default_calibration_follows_trim_sign(win, monkeypatch):
    """符号由「trim方向」反推：sign(k) = −sign(trim_sign)，逐路。"""
    monkeypatch.setattr(scope, "load_named_json", lambda name: None)
    win.cl_edits["trim_sign"].setText("-1,1,-1")
    win._load_wrist_calib(quiet=True)
    signs = [1.0 if v > 0 else -1.0 for v in win.wrist_calib.k_counts_per_m]
    assert signs == [1.0, -1.0, 1.0]


@pytest.fixture
def c1_position(win):
    sent = _prep(win)
    win.cl_mode_combo.setCurrentIndex(win.cl_mode_combo.findData("c1_position"))
    win.wrist_calib = WristCalib([-108649.77, -118527.03, -118527.03], [0.0, 0.0])
    win._c1_position_state.reset()
    win._c1_angle_state.reset()
    win._c1_diag_rows.clear()
    fields = {"roll_tgt": "0", "pitch_tgt": "0", "pos_kp": "0.2",
              "pos_ki": "0", "pos_kd": "0", "pos_ff": "0", "pos_step": "5",
              "c1_pos_target": "5", "c1_pos_kp": "15", "c1_pos_ki": "0", "c1_pos_kd": "0",
              "c1_pos_ff": "0", "c1_pos_step": "50", "c1_pos_max_n": "25"}
    for key, value in fields.items():
        win._c1_position_edits[key].setText(value)
    now = time.monotonic()
    win.t0 = now
    for j in (16, 17):
        win.channels[f"enc_raw_{j}"].buf.append(0.0, win._enc_filt_raw[j])
    win._tension_last = (now, [5.0, math.nan, math.nan])
    yield win, sent
    win.cl_mode_combo.setCurrentIndex(win.cl_mode_combo.findData("position"))


def test_c1_position_displays_all_three_tensions(c1_position):
    """混合模式也必须显示三缆真值（2026-11-23 撤销"C2/C3 置 NaN"）。

    控制仍只用 C1，但缆卡 / τ=R·f / 张紧 t / 曲线吃的是三缆真值；
    再置 NaN 会把 C1 的好数据一起毒成 NaN，观测台就只剩 C1 可看。
    """
    w, _ = c1_position
    w._tension_feed((-1000, -2000, -3000, 0, 0, 0, 0, 0))
    f1, f2, f3 = w._tension_last[1]
    assert all(math.isfinite(v) for v in (f1, f2, f3))
    assert f1 > 0.0 and f2 > 0.0 and f3 > 0.0      # 受拉为正
    # 三缆都进了通道缓冲（观测台走势图/曲线数据源）
    for i, expect in enumerate((f1, f2, f3), start=1):
        assert w.channels[f"tension_f{i}"].buf.last() == pytest.approx(expect)


@pytest.mark.parametrize("c1", [4.0, 6.0])
def test_c1_position_tension_controls_only_c1(c1_position, c1):
    w, sent = c1_position
    w._tension_last = (time.monotonic(), [c1, math.nan, math.nan])
    assert w._start_cl_gate_reason() is None
    w._cl_tick()
    expected = 1100 + round(15 * (5.0 - c1))
    assert sent == {27: expected, 28: 2100, 29: 3100}


@pytest.mark.parametrize(("axis", "c2_direction", "c3_direction"),
                         [("roll", 1, -1), ("pitch", 1, 1)])
def test_c1_position_angle_targets_control_only_c2_c3(c1_position, axis,
                                                     c2_direction, c3_direction):
    w, sent = c1_position
    w._c1_position_edits[f"{axis}_tgt"].setText("2.0")
    w._cl_tick()
    assert sent[27] == 1100
    assert (sent[28] - 2100) * c2_direction > 0
    assert (sent[29] - 3100) * c3_direction > 0


@pytest.mark.parametrize(("sample_age", "c1", "reason"),
                         [(STALE_MS / 1000.0 + 0.5, 5.0, "过期"),
                          (0.0, math.nan, "无效"), (0.0, 30.0, "过载")])
def test_c1_position_stops_before_sending_on_bad_tension(c1_position, monkeypatch,
                                                         sample_age, c1, reason):
    w, sent = c1_position
    w._tension_last = (time.monotonic() - sample_age, [c1, math.nan, math.nan])
    stopped = []
    monkeypatch.setattr(w, "_stop_closed_loop", stopped.append)
    assert reason in w._start_cl_gate_reason()
    w._cl_tick()
    assert stopped and reason in stopped[0]
    assert not sent


def test_c1_position_rejects_stale_motor_feedback(c1_position, monkeypatch):
    w, sent = c1_position
    w.channels["m28_abs"].buf.append(-(STALE_MS / 1000.0 + 0.5), 2100)
    stopped = []
    monkeypatch.setattr(w, "_stop_closed_loop", stopped.append)
    w._cl_tick()
    assert stopped and "m28_abs" in stopped[0] and "过期" in stopped[0]
    assert not sent


def test_c1_position_can_start_and_stop_from_panel(c1_position, monkeypatch):
    w, sent = c1_position

    class OneTick:
        def __init__(self, window, period_s):
            self.window = window

        def start(self):
            self.window._cl_tick()

        def stop(self):
            pass

        def wait(self, timeout):
            return True

    monkeypatch.setattr(scope, "_ClLoopThread", OneTick)
    w._tension_last = (time.monotonic(), [4.0, math.nan, math.nan])
    w.cl_btn.click()
    try:
        assert w.cl_enabled
        assert w._c1_position_params.c1.target_n == 5.0
        assert sent == {27: 1115}
        assert w.targets[28] == 2100 and w.targets[29] == 3100
    finally:
        if w.cl_enabled:
            w.cl_btn.click()
    assert not w.cl_enabled


def test_c1_position_ignores_other_modes_tuning(c1_position):
    w, sent = c1_position
    w._c1_position_edits["roll_tgt"].setText("2")
    w.cl_edits["roll_tgt"].setText("-10")
    w.cl_edits["kp"].setText("0")
    w.cl_edits["max_step_f"].setText("200")
    w.cl_edits["k_ff"].setText("1")
    w.cl_ff_check.setChecked(True)
    w._cl_tick()
    assert sent == {27: 1100, 28: 2105, 29: 3095}
    assert not w._pos_pid_state.primed
    assert w._c1_angle_state.primed


def test_c1_position_feedforward_channels_are_independent(c1_position):
    w, sent = c1_position
    w._c1_position_edits["pos_kp"].setText("0")
    w._c1_position_edits["pos_ff"].setText("0.25")
    w._c1_position_edits["pitch_tgt"].setText("2")
    w._cl_tick()
    assert sent == {27: 1100, 28: 2105, 29: 3105}
    assert w._c1_diag_rows[-1][14] == 0.0       # C1 FF 关闭

    w._c1_position_edits["pos_ff"].setText("0")
    w._c1_position_edits["c1_pos_ff"].setText("0.5")
    w._enc_filt_raw[17] -= 2.0                   # 模型 pitch 变大，C1 绳路变长
    sent.clear()
    w._cl_tick()
    assert sent[27] < 1100                       # counts 减小为放绳
    assert sent[28] == 2100 and sent[29] == 3100
    assert w._c1_diag_rows[-1][14] < 0.0


def test_c1_position_exports_its_own_diagnostics(c1_position, monkeypatch):
    w, _ = c1_position
    w._cl_tick()
    w._cl_tick()
    exported = {}

    def capture(name, **kwargs):
        exported.update(name=name, **kwargs)
        return name

    monkeypatch.setattr(scope, "dump_csv", capture)
    w._export_diag_csv()
    assert exported["name"].startswith("diag_c1_position_")
    assert len(exported["header"]) == len(exported["columns"])
    columns = dict(zip(exported["header"], exported["columns"]))
    assert columns["c1_n"] == columns["c1_target_n"] == [5.0, 5.0]
    assert columns["c1_ff_c"] == [0.0, 0.0]


def test_c1_position_layout_keeps_separate_gains(c1_position, monkeypatch):
    w, _ = c1_position
    w.cl_edits["kp"].setText("0.7")
    w._c1_position_edits["pos_kp"].setText("0.31")
    w._c1_position_edits["c1_pos_ff"].setText("0.2")
    saved = {}
    monkeypatch.setattr(scope, "save_layout_json", saved.update)
    monkeypatch.delenv("QT_QPA_PLATFORM")
    w._save_layout()
    assert saved["cl_params"]["kp"] == "0.7"
    assert "c1_pos_ff" not in saved["cl_params"]
    assert saved["c1_position_params"]["pos_kp"] == "0.31"
    assert saved["c1_position_params"]["c1_pos_ff"] == "0.2"

    w._c1_position_edits["pos_kp"].setText("0")
    monkeypatch.setattr(scope, "load_layout_json", lambda: saved)
    w._load_layout()
    assert w._read_c1_position_params().angles.kp == pytest.approx(0.31)
    assert w._read_c1_position_params().c1.ff_gain == pytest.approx(0.2)
