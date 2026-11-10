"""逐绳使能开关（cable_enable_checks）门禁测试：离屏实例化 ScopeWindow。

覆盖 2026-11-02 需求"每根绳一个开关，勾选才可以使能"：
- 默认全勾选，掩码 = M27|M28|M29；
- 全不勾 → 拒绝使能、不发任何帧；
- 使能时 ACTIVE_SCOPE 掩码只含勾选绳，在线检查也只查勾选绳；
- 未勾选电机：点动/回零/力控 trim 一律不下发；
- 布局 JSON 的 cable_enable 恢复（blockSignals，不触发半程保存）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading

import pytest

import mmhand_scope as scope
from desktop.core.protocol import (
    build_active_scope_cmd,
    build_motor_pos_abs_cmd,
    build_motor_pos_abs_one_cmd,
    build_servo_reset_zero_cmd,
)

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
    # 布局加载读用户真实存档：测试必须以空档启动，保证勾选态确定。
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}
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


def _set_online(w, motors):
    w.status_info["servo_online"] = sum(1 << m for m in motors)


def _arm_env(w):
    """使能前置环境：已连接、三机在线、路由空闲、ABS 快照、多圈已知。"""
    w.connected = True
    w.rx_thread = _FakeSerial()
    _set_online(w, (27, 28, 29))
    w.route_info["scan_state"] = 0
    w.last_servo_abs_all = [100] * 30
    w.status_info["multiturn_unknown"] = 0
    w.status_info["state"] = 1
    w.estop_latched = False


def test_default_all_enabled(win):
    assert win._enabled_motors() == [27, 28, 29]
    assert win._enabled_motor_mask() == ALL_MASK
    # 标签按 MOTOR_FOR_CABLE 动态算：恒等映射 → M27·C1 / M28·C2 / M29·C3
    assert win.cable_enable_checks[27].text() == "M27·C1"
    assert win.cable_enable_checks[28].text() == "M28·C2"
    assert win.cable_enable_checks[29].text() == "M29·C3"


def test_enable_refuses_when_none_checked(win):
    _arm_env(win)
    for cb in win.cable_enable_checks.values():
        cb.setChecked(False)
    win._on_enable_direct()
    assert "未勾选任何绳" in win.ctrl_status.text()
    assert win.rx_thread.frames == []
    for cb in win.cable_enable_checks.values():
        cb.setChecked(True)


def test_enable_scope_mask_follows_checks(win):
    _arm_env(win)
    win.cable_enable_checks[28].setChecked(False)
    win._on_enable_direct()
    frames = win.rx_thread.frames
    assert build_active_scope_cmd((1 << 27) | (1 << 29), 0, False) in frames
    win._admit_timer.stop()
    win.cable_enable_checks[28].setChecked(True)


def test_online_check_only_considers_enabled(win):
    _arm_env(win)
    win.cable_enable_checks[28].setChecked(False)
    _set_online(win, (27, 29))          # M28 离线但未勾选 → 不应拦截
    win._on_enable_direct()
    assert "离线" not in win.ctrl_status.text()
    assert build_active_scope_cmd((1 << 27) | (1 << 29), 0, False) in win.rx_thread.frames
    win._admit_timer.stop()
    _set_online(win, (27, 29, 28))
    win.cable_enable_checks[28].setChecked(True)
    _set_online(win, (29,))             # M27 勾选且离线 → 必须拦截
    win._on_enable_direct()
    assert "离线" in win.ctrl_status.text()
    assert "M27" in win.ctrl_status.text()
    _set_online(win, (27, 28, 29))


def test_multiturn_zero_uses_enabled_mask(win):
    _arm_env(win)
    win.cable_enable_checks[28].setChecked(False)
    win.status_info["multiturn_unknown"] = ALL_MASK
    win._on_enable_direct()
    assert build_servo_reset_zero_cmd((1 << 27) | (1 << 29)) in win.rx_thread.frames
    win._zero_timer.stop()
    win.status_info["multiturn_unknown"] = 0
    win.cable_enable_checks[28].setChecked(True)


def test_send_motor_target_gated(win):
    _arm_env(win)
    win.ramp_check.setChecked(False)    # 关斜坡：直发单帧便于断言
    win.cable_enable_checks[29].setChecked(False)
    win._send_motor_target(29, 12345)
    assert win.rx_thread.frames == []
    win._send_motor_target(27, 456)
    assert win.rx_thread.frames == [build_motor_pos_abs_one_cmd(27, 456)]
    win.ramp_check.setChecked(True)
    win.cable_enable_checks[29].setChecked(True)


def test_goto_zero_skips_unchecked(win):
    _arm_env(win)
    win.ramp_check.setChecked(False)
    win.armed = True
    win.cable_enable_checks[29].setChecked(False)
    win._do_goto_zero({"motors": {"27": 1000, "28": 2000, "29": 3000}})
    frames = win.rx_thread.frames
    # 回零已改成**一帧 0xD3 批量**（逐帧 0xDE 会被固件按代际合并，只执行最后一台）
    expect = [100] * 30          # _arm_env 的 ABS 快照基底
    expect[27], expect[28] = 1000, 2000
    assert build_motor_pos_abs_cmd(expect) in frames   # M29 未勾选 → 保持 100
    assert not any(f[2] == 0xDE for f in frames if len(f) > 2)   # 不应再有单电机帧
    assert "未勾选" in win.ctrl_status.text()
    win.armed = False
    win.ramp_check.setChecked(True)
    win.cable_enable_checks[29].setChecked(True)


def test_force_step_skips_unchecked(win):
    """增量出口门禁（0xD3 批量帧版）：未勾选电机不出现在批量目标里。"""
    _arm_env(win)
    win._motor_origin = {27: 0, 28: 0, 29: 0}
    win._force_base = [0, 0, 0]
    win._force_trim = [0.0, 0.0, 0.0]
    win.targets = {m: None for m in (27, 28, 29)}   # 实测位置回退起点=0（免顺序污染）
    win._cl_motor_on = frozenset({27, 28})
    win._apply_force_step([500, 600, 700], 3000)
    frames = win.rx_thread.frames
    # 出口已合并为一帧 0xD3（30 路绝对目标）：只应有批量帧
    batch = [f for f in frames if f not in
             (build_active_scope_cmd(0, 0, False),)]  # 排除使能流程帧
    assert batch, "应有 0xD3 批量帧"
    expect = [100] * 30          # _arm_env 的 ABS 快照基底
    expect[27], expect[28] = 500, 600
    assert build_motor_pos_abs_cmd(expect) in batch  # M29 未勾选 → 保持 100
    win._cl_motor_on = frozenset((27, 28, 29))


def test_layout_roundtrip(win, monkeypatch):
    saved = {}

    def fake_save(data):
        saved.update(data)
        return True

    # 写入函数已替换 → 临时摘掉 offscreen 守卫也不会触盘，只为走完数据组装分支
    monkeypatch.setattr(scope, "save_layout_json", fake_save)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    win.cable_enable_checks[28].setChecked(False)
    win._save_layout()
    assert saved.get("cable_enable") == {"27": True, "28": False, "29": True}

    # 直接调 _load_layout 恢复：不走 __init__，避开用户真实存档
    monkeypatch.setattr(scope, "load_layout_json",
                        lambda: {"cable_enable": {"27": True, "28": False, "29": True}})
    win._load_layout()
    assert win._motor_enabled(28) is False
    assert win._enabled_motor_mask() == (1 << 27) | (1 << 29)
    win.cable_enable_checks[28].setChecked(True)
    assert win._enabled_motor_mask() == ALL_MASK
