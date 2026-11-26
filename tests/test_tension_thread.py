"""张力轮询线程（2026-11-25）的生命周期测试。

背景：张力轮询原来跑在 GUI 线程的 QTimer 里，被 60 Hz 绘图 + CSV 写盘拖到
~15 Hz（裸串口实测 249.9 Hz、帧间隔 4.0 ms）。现在搬进 `_TensionPollThread`。

这里只测线程本体（不碰真串口）：
  1. 能按驱动接口把每一帧交给 `_tension_feed`
  2. `stop()` 后能在超时内退出
  3. 串口异常、持续无帧及端口延迟出现时可取消或恢复
"""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtWidgets import QApplication

import mmhand_scope as scope
import mmhand_scope_export
from desktop.core import session_log


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeSensor:
    """最小 ZnsvTransmitter 替身：前 n 次 poll 返回帧，之后返回 None。"""

    def __init__(self, frames=50, raise_at=None, delay=0.0005):
        self.frames = frames
        self.raise_at = raise_at
        self.delay = delay
        self.calls = 0
        self.connects = 0        # connect() 调用次数（重连测试用）
        self.disconnects = 0
        self.timeouts = self.protocol_errors = 0
        self.error = ""

    def connect(self, port, baud):     # 自动重连会调它
        self.connects += 1
        self.calls = 0                 # 重连后计数归零，模拟"链路恢复"

    def disconnect(self):
        self.disconnects += 1

    def poll(self):
        self.calls += 1
        if self.raise_at is not None and self.calls >= self.raise_at:
            raise IOError("模拟串口掉线")
        if self.calls <= self.frames:
            return (1, 2, 3, 0, 0, 0, 0, 0)
        return None

    def next_poll_delay(self):
        return self.delay


class _FakeWin:
    def __init__(self):
        self.fed = 0

    def _tension_feed(self, raws):
        assert len(raws) == 8
        self.fed += 1


def _wait_until(pred, timeout=2.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


def test_thread_feeds_every_frame(app):
    win = _FakeWin()
    sensor = _FakeSensor(frames=50)
    th = scope._TensionPollThread(win, sensor)
    th.start()
    try:
        assert _wait_until(lambda: win.fed >= 50), f"只喂了 {win.fed} 帧"
    finally:
        th.stop()
        assert th.wait(1500), "线程未在 1.5 s 内退出"
    assert win.fed == 50


def test_stop_exits_promptly(app):
    win = _FakeWin()
    sensor = _FakeSensor(frames=10 ** 9, delay=0.002)  # 永远有活干
    th = scope._TensionPollThread(win, sensor)
    th.start()
    assert _wait_until(lambda: win.fed > 0)
    t0 = time.perf_counter()
    th.stop()
    assert th.wait(1500)
    assert time.perf_counter() - t0 < 1.0, "退出太慢"


def test_poll_exception_without_port_reports_exit_reason(app):
    win = _FakeWin()
    sensor = _FakeSensor(frames=3, raise_at=4)
    th = scope._TensionPollThread(win, sensor)
    th.start()
    try:
        assert th.wait(1500)
        assert "采集异常" in th.stop_reason
        assert sensor.disconnects == 1
    finally:
        th.stop()
        th.wait(1500)


def test_poll_exception_reconnects_when_port_known(app):
    """给了端口 → 异常时先重连，成功后计数 +1、继续喂帧。"""
    win = _FakeWin()
    sensor = _FakeSensor(frames=3, raise_at=4)
    th = scope._TensionPollThread(win, sensor, port="COMTEST", baud=600000)
    th.start()
    try:
        assert _wait_until(lambda: th._reconnects >= 1, 3.0), \
            "没有尝试重连（_reconnects 未增加）"
        assert sensor.connects >= 1, "connect() 没有被调用"
    finally:
        th.stop()
        th.wait(1500)


class _RecoveringSensor(_FakeSensor):
    """模拟 pyserial 出错后关闭句柄，然后 poll 只返回 None。"""

    def __init__(self, failures=(), silent=False):
        super().__init__()
        self.failures = list(failures)
        self.silent = silent
        self.connected = True
        self.timeouts = self.protocol_errors = 0
        self.error = ""

    def connect(self, port, baud):
        super().connect(port, baud)
        if self.failures and self.failures.pop(0):
            raise OSError("COM 口尚未出现")
        self.connected = True

    def disconnect(self):
        super().disconnect()
        self.connected = False

    def poll(self):
        if not self.connected:
            return None
        self.calls += 1
        if self.silent:
            if self.connects and self.connects >= 2:
                return (1,) * 8
            self.timeouts += 1
            self.error = "收到 0/37 字节"
            return None
        if self.connects == 0 and self.calls == 1:
            return (1,) * 8
        if self.connects < 2:
            self.disconnect()
            raise OSError("读串口失败")
        return (2,) * 8


@pytest.mark.parametrize("sensor", [
    pytest.param(lambda: _RecoveringSensor(silent=True), id="open-port-no-valid-frames"),
    pytest.param(_RecoveringSensor, id="io-error-again-on-reopen"),
    pytest.param(lambda: _RecoveringSensor(failures=[True] * 6), id="device-returns-late"),
])
def test_stream_recovers_without_manual_replug(app, sensor):
    win, driver = _FakeWin(), sensor()
    th = scope._TensionPollThread(win, driver, "COMTEST", 600000)
    th._no_frame_s = 0.04
    th._retry_initial_s = th._retry_max_s = 0.01
    th.start()
    try:
        assert _wait_until(lambda: driver.connects >= 2 and win.fed > 1, 1.3)
    finally:
        th.stop()
        assert th.wait(1500)


def test_stop_cancels_backoff_before_reopen(app):
    driver = _RecoveringSensor()
    th = scope._TensionPollThread(_FakeWin(), driver, "COMTEST", 600000)
    th._retry_initial_s = 5
    th.start()
    try:
        assert _wait_until(lambda: "重试" in th.link_status)
    finally:
        th.stop()
        assert th.wait(500)
    assert not driver.connected and driver.connects == 0


def test_scope_keeps_port_owner_until_blocked_read_finishes(app, monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()

    class SlowSensor(_FakeSensor):
        received_at = temp_c = last_write = None
        sequence = 0

        def poll(self):
            entered.set()
            release.wait(5)
            return None

    sensor = SlowSensor()
    monkeypatch.setattr(mmhand_scope_export, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(session_log, "close_session_log", lambda: None)
    monkeypatch.setattr(scope.ScopeWindow, "_list_ports", staticmethod(lambda: ["COMTEST"]))
    monkeypatch.setattr(scope, "ZnsvTransmitter", lambda **kw: sensor)
    win = scope.ScopeWindow()
    try:
        win._toggle_rt_window()
        win._toggle_tension_port()
        assert entered.wait(1)
        win._toggle_tension_port()
        assert win._tension_sensor is sensor and sensor.disconnects == 0
        assert "正在关闭" in win.tension_status.text()
        assert "实收0Hz" in win.tension_status.text()
        release.set()
        assert win._tension_thread.wait(1000)
        app.processEvents()
        assert win._tension_thread is None and win._tension_sensor is None
        assert sensor.disconnects == 1 and win.tension_btn.text() == "连接"
    finally:
        release.set()
        win.close()
        app.processEvents()
