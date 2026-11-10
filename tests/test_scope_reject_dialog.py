"""门禁拒绝可见化（_reject / RejectDialog）测试：离屏实例化 ScopeWindow。

覆盖 2026-11-09 定案：
- 拒绝三连：ctrl_status 立显 + 控制日志持久化 + GATE_REJECT 取证；
- 弹窗语义：居中弹出不自动消失；「知道了」只关窗清零，不触发任何控制；
- 急停按钮：与主窗 _on_stop 同路，按完自动关窗；
- 合并防风暴：未关期间的新拒绝并入同一弹窗（计数 + 末 3 条），不叠窗；
- 1Hz 复查（PLAN ①）：recheck 返回原因/None 时状态行 ✅/❌ 切换，
  复查抛异常时报一次即停表；
- 门禁抽取回归：紧绳/松绳/启动闭环/使能各分支 reason 与原文案一致；
- 拒绝不留痕：被拒的启动闭环不再停斜坡/自动归零（门禁先于副作用）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time

import pytest

import mmhand_scope as scope

ALL_MASK = (1 << 27) | (1 << 28) | (1 << 29)


class _FakeSerial:
    """收集发往 P4 的帧；send 永远成功；带 tx_queue 供批量出口查积压。"""

    def __init__(self):
        self.frames = []
        self.stop_event = threading.Event()
        self.tx_queue = __import__("queue").Queue()

    def send(self, data):
        self.frames.append(bytes(data))
        return True

    def join(self, timeout=None):
        return None


@pytest.fixture(scope="module")
def win():
    # 布局加载读用户真实存档：测试必须以空档启动，保证状态确定。
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = scope.ScopeWindow(default_port="COM_TEST")
    yield w
    if w._reject_dlg is not None:
        w._reject_dlg._recheck_timer.stop()
    w._admit_timer.stop()
    w._zero_timer.stop()
    w._ramp_timer.stop()
    w._cl_timer.stop()
    w.close()
    scope.load_layout_json = real_load
    app.processEvents()


@pytest.fixture(autouse=True)
def _clean_state(win):
    """每测复位：弹窗关掉、连接/使能/闭环/位姿状态归零，测试间零污染。"""
    yield
    if win._reject_dlg is not None:
        win._reject_dlg._dismiss()
    win.connected = False
    win.armed = False
    win.cl_enabled = False
    win._cl_mode = "position"
    win._release_plan = None
    win._tension_last = None
    win.angle_baseline[16] = None
    win.angle_baseline[17] = None
    win._enc_filt_raw[16] = None
    win._enc_filt_raw[17] = None
    win._want_closed_loop = False
    win._want_goto_zero = False
    win._pending_target = None


@pytest.fixture(autouse=True)
def cap_safety(monkeypatch):
    """拦截 _safety 落盘（autouse，本模块全测试密闭：不污染真实取证日志）。

    REVIEW Important#3：connected=True 的测试经 _safety→safety_log 真写
    run_data/运行日志/safety_*.log，混进假 GATE_REJECT 会毁掉事故复盘材料。"""
    calls = []
    monkeypatch.setattr(scope, "safety_log",
                        lambda action, **fields: calls.append((action, fields)))
    return calls


def _arm_env(w):
    """使能/力控前置环境：已连接、三机在线、路由空闲、ABS 快照、多圈已知。"""
    w.connected = True
    w.rx_thread = _FakeSerial()
    w.status_info["servo_online"] = ALL_MASK
    w.route_info["scan_state"] = 0
    w.last_servo_abs_all = [100] * 30
    w.status_info["multiturn_unknown"] = 0
    w.status_info["state"] = 1
    w.status_info["active_motor_mask"] = 0   # 0=未知不判（与真机未上电极性同）
    w.estop_latched = False


def _fresh_tension(w, vals=(1.0, 1.0, 1.0)):
    w._tension_last = (time.monotonic(), list(vals))


def _pose_env(w):
    """J16/J17 有数据且已归零 → _wrist_pose_now 可用。"""
    w._enc_filt_raw[16] = 16000.0
    w._enc_filt_raw[17] = 16000.0
    w._set_baseline_from_current(16)
    w._set_baseline_from_current(17)


# ---------------------------------------------------------------- 基础三连
def test_reject_three_writes(win, cap_safety):
    win.connected = True            # _safety 只在连接时取证
    win._reject("测试门", "测试原因A")
    dlg = win._reject_dlg
    assert dlg is not None and not dlg.isHidden()
    assert "测试原因A" in win.ctrl_status.text()
    assert "测试原因A" in win.ctrl_log.toPlainText()      # 持久化（旧版不进日志）
    gate_calls = [f for a, f in cap_safety if a == "GATE_REJECT"]
    assert gate_calls and gate_calls[0]["gate"] == "测试门"
    assert gate_calls[0]["reason"] == "测试原因A"


def test_dismiss_only_closes(win):
    """「知道了」只关窗清零：不触发控制、状态不变、重开计数归 1。"""
    win._reject("测试门", "原因1")
    dlg = win._reject_dlg
    dlg._know_btn.click()
    assert dlg.isHidden()
    assert dlg._count == 0 and dlg._items == []
    win._reject("测试门", "原因2")
    assert dlg._count == 1 and "原因2" in dlg._body.text()


def test_estop_button_routes_to_on_stop(win, monkeypatch):
    fired = []
    monkeypatch.setattr(win, "_on_stop", lambda: fired.append(True))
    win._reject("测试门", "原因1")
    win._reject_dlg._estop_btn.click()
    assert fired == [True]
    assert win._reject_dlg.isHidden()        # 急停后自动关窗


def test_merge_no_second_dialog(win):
    """未关期间的新拒绝并入同一弹窗：不叠窗、计数、末 3 条可见。"""
    win._reject("门A", "原因A")
    dlg = win._reject_dlg
    for r in ("原因B", "原因C", "原因D"):    # D 应挤掉 A（只留末 3 条）
        win._reject("门B", r)
    assert win._reject_dlg is dlg            # 单实例，没有第二个窗
    assert dlg._count == 4
    assert "共 4 次" in dlg._title.text()
    assert "原因D" in dlg._body.text() and "原因A" not in dlg._body.text()


# ---------------------------------------------------------------- 1Hz 复查
def test_recheck_fail_then_pass(win):
    """recheck 有原因=❌仍不满足；条件修复后同窗变 ✅可重试。"""
    state = {"ok": False}
    win._reject("门A", "原因A",
                recheck=lambda: None if state["ok"] else "还没改好")
    dlg = win._reject_dlg
    dlg._recheck_tick()
    assert "仍不满足" in dlg._status.text() and "还没改好" in dlg._status.text()
    state["ok"] = True
    dlg._recheck_tick()
    assert "已满足" in dlg._status.text()


def test_recheck_exception_stops_timer(win):
    boom = {"n": 0}

    def bad():
        boom["n"] += 1
        raise RuntimeError("炸了")

    win._reject("门A", "原因A", recheck=bad)
    dlg = win._reject_dlg
    assert not dlg._recheck_timer.isActive()    # 首查即炸 → 停表
    assert "复查异常" in dlg._status.text()
    dlg._recheck_tick()                          # 再手动触发也不再调用
    assert boom["n"] == 1


def test_recheck_none_hides_status(win):
    win._reject("门A", "原因A")                   # 无 recheck（如轮询拒绝）
    assert win._reject_dlg._status.isHidden()
    assert not win._reject_dlg._recheck_timer.isActive()


# ------------------------------------------------------------ 门禁抽取回归
def test_enable_gate_branches(win):
    _arm_env(win)
    assert win._enable_gate_check()[0] is None
    win.connected = False
    assert win._enable_gate_check()[0] == "未连接"
    win.connected = True
    for cb in win.cable_enable_checks.values():
        cb.setChecked(False)
    reason, clear_pending = win._enable_gate_check()
    assert "未勾选任何绳" in reason and clear_pending
    # 走按钮路径：拒绝弹窗可见 + 预埋意图被清
    win._want_closed_loop = True
    win._on_enable_direct()
    assert not win._reject_dlg.isHidden()
    assert win._want_closed_loop is False
    assert win.rx_thread.frames == []
    for cb in win.cable_enable_checks.values():
        cb.setChecked(True)
    win.status_info["servo_online"] = 1 << 27
    assert "离线" in win._enable_gate_check()[0]


def test_start_cl_gate_branches(win):
    # J16/J17 无数据（显式清基准：不依赖模块级窗口的先前状态，乱序也稳）
    win.angle_baseline[16] = None
    win.angle_baseline[17] = None
    win._enc_filt_raw[16] = None
    win._enc_filt_raw[17] = None
    assert "J16/J17 无数据" in win._start_cl_gate_reason()
    _pose_env(win)
    # 力控三模式：无新鲜张力
    win._cl_mode = "tension"
    assert "无新鲜张力数据" in win._start_cl_gate_reason()
    _fresh_tension(win)
    assert win._start_cl_gate_reason() is None
    # 未勾任何绳
    for cb in win.cable_enable_checks.values():
        cb.setChecked(False)
    assert "未勾选任何绳" in win._start_cl_gate_reason()
    for cb in win.cable_enable_checks.values():
        cb.setChecked(True)


def test_recheck_does_not_touch_status_line(win):
    """回归（审阅 Important#2）：复查路径不得改写主状态行。

    旧版 _tight_params 在可行域越界时 _ctrl_status(log=False)，1Hz 复查会把
    状态行（包括急停后的 ⛔ 消息）顶成"张紧：t=… 超出可行上界…"。"""
    _arm_env(win)
    win.armed = True
    _pose_env(win)
    _fresh_tension(win)
    win._cl_mode = "tight"
    win.cl_edits["t_tgt"].setText("150")     # 超可行上界 → 旧版此处在写状态行
    win._start_closed_loop()
    assert not win.cl_enabled
    dlg = win._reject_dlg
    assert not dlg.isHidden() and "力控参数非法" in dlg._body.text()
    before = win.ctrl_status.text()
    dlg._recheck_tick()
    dlg._recheck_tick()
    assert win.ctrl_status.text() == before   # 状态行纹丝不动
    win.cl_edits["t_tgt"].setText("5.0")


def test_start_cl_reject_leaves_no_side_effects(win):
    """门禁先于副作用：被拒的启动不再停斜坡/自动归零（2026-11-09 抽取裁定）。"""
    win._tension_last = None
    win._cl_mode = "tension"          # 无张力 → 必拒
    win._ramp_state[27] = {"target": 999, "next_due": 0.0}
    win._ramp_timer.start(50)
    win._start_closed_loop()
    assert not win.cl_enabled
    assert not win._reject_dlg.isHidden()
    assert win._ramp_timer.isActive()          # 斜坡没被停
    assert 27 in win._ramp_state
    win._ramp_timer.stop()
    win._ramp_state.clear()


def test_release_gate_branches(win):
    _arm_env(win)
    win.armed = True
    win._release_plan = None
    assert win._release_gate_reason() is None
    win.cl_enabled = True
    assert "闭环运行中" in win._release_gate_reason()
    win.cl_enabled = False
    win._release_plan = {"items": []}
    assert "还在执行" in win._release_gate_reason()
    win._release_plan = None
    win.cl_edits["trim_sign"].setText("1,1")
    assert "trim方向非法" in win._release_gate_reason()
    win.cl_edits["trim_sign"].setText("1,1,1")


def test_tighten_gate_branches(win):
    # 未使能
    assert win._tighten_gate_check() == ("一键紧绳：未使能/未连接", {})
    _arm_env(win)
    win.armed = True
    # 无新鲜张力
    reason, ctx = win._tighten_gate_check()
    assert reason == "一键紧绳：无新鲜张力数据（先连观测台张力串口）" and ctx == {}
    _fresh_tension(win, (1.0, 1.0, 40.0))     # 超过 fmax 默认 30 → 已过载
    assert "已过载" in win._tighten_gate_check()[0]
    _fresh_tension(win)
    # 无位姿（显式清基准与滤波值：模块级窗口可能被早前测试设过）
    win.angle_baseline[16] = None
    win.angle_baseline[17] = None
    win._enc_filt_raw[16] = None
    win._enc_filt_raw[17] = None
    assert "无位姿" in win._tighten_gate_check()[0]
    _pose_env(win)
    # 全条件满足 → 通过且 ctx 齐全
    reason, ctx = win._tighten_gate_check()
    assert reason is None
    assert ctx["t_use"] > 0 and len(ctx["nd"]) == 3
    assert ctx["fmin"] > 0 and ctx["fmax"] > ctx["fmin"]


def test_tighten_reject_dialog_and_recheck(win):
    """按钮路径：无张力被拒 → 弹窗可见；补上新鲜张力后复查变 ✅。"""
    _arm_env(win)
    win.armed = True
    _pose_env(win)                    # 位姿先备好：张力是唯一不满足项
    win._on_tighten_rope()
    dlg = win._reject_dlg
    assert not dlg.isHidden() and "无新鲜张力数据" in dlg._body.text()
    assert "仍不满足" in dlg._status.text()
    _fresh_tension(win)
    dlg._recheck_tick()
    assert "已满足" in dlg._status.text()
    assert win.cl_enabled is False            # 拒绝路径绝不启动闭环
    assert win.rx_thread.frames == []         # 也不发任何帧


# ------------------------------------------- 一键紧绳会话：故障停环弹窗
def test_tighten_session_fault_stop_pops(win, cap_safety):
    """恢复中/持有中被故障打断 → 弹窗（动词=已停止），取证仍是 CL_STOP。"""
    _arm_env(win)                     # connected=True：_safety 才取证
    win.cl_enabled = True
    win._tighten_cl_active = True
    reason = "力控：张力过载 [12.0/1.0/1.0] N > f_max=30"
    win._stop_closed_loop(reason)
    dlg = win._reject_dlg
    assert not dlg.isHidden()
    assert "已停止" in dlg._title.text() and "一键紧绳" in dlg._title.text()
    assert reason in dlg._body.text()
    assert any(a == "CL_STOP" for a, _ in cap_safety)
    # 停环弹窗不写 GATE_REJECT（那是门禁拒绝专用事件）
    assert not any(a == "GATE_REJECT" for a, _ in cap_safety)
    assert win._tighten_cl_active is False
    assert win.cl_enabled is False
    # R2-FindingA 回归：弹窗在 cl_enabled=False 之后才 push → 首次复查
    # 不得报"闭环运行中"（停止弹窗自称已停止，复查却说在运行=自相矛盾）
    assert "闭环运行中" not in dlg._status.text()


def test_tighten_session_manual_stop_no_dialog(win):
    """用户主动停止（手动/急停/切模式/勾选变更/断开/回滚）不弹窗。"""
    win.cl_enabled = True
    win._tighten_cl_active = True
    win._stop_closed_loop("手动停止", popup=False)
    assert win._reject_dlg is None or win._reject_dlg.isHidden()
    assert win._tighten_cl_active is False


def test_normal_loop_fault_stop_no_dialog(win):
    """非紧绳会话的普通闭环故障停止不弹窗（需求只覆盖一键紧绳）。"""
    win.cl_enabled = True
    win._tighten_cl_active = False
    win._stop_closed_loop("力控：TDA 不可行（该位姿无全正预紧或超界）")
    assert win._reject_dlg is None or win._reject_dlg.isHidden()


def test_tighten_stop_dialog_recheck_ready(win):
    """停止弹窗的复查=紧绳门禁：故障清除后自动转 ✅可重试。"""
    _arm_env(win)
    win.armed = True
    _pose_env(win)
    win.cl_enabled = True
    win._tighten_cl_active = True
    win._stop_closed_loop("力控：张力数据丢失")
    dlg = win._reject_dlg
    dlg._recheck_tick()
    assert "仍不满足" in dlg._status.text()      # 无张力 → 紧绳门禁仍不满足
    _fresh_tension(win)
    dlg._recheck_tick()
    assert "已满足" in dlg._status.text()        # 故障清除 → 可重试
