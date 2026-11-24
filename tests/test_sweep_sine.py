"""扫掠正弦波（跟随测试）测试——2026-11-10 新增。

三角波行为不变；正弦波目标 = A·sin(2πf·t)，A=限幅、相位从勾选起算；
未启动闭环时不推进。
"""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(app):
    import mmhand_scope as scope
    # 临时禁写布局；**必须还原**——原来直接给类属性赋值且不还原，后面跑的
    # 测试模块里 _save_layout 全变成 no-op（2026-11-24 发现，会让依赖存档的
    # 用例按运行顺序时好时坏）。
    real_save = scope.ScopeWindow._save_layout
    scope.ScopeWindow._save_layout = lambda self: None
    w = scope.ScopeWindow(default_port="COM_TEST")
    try:
        yield w
    finally:
        w.close()
        scope.ScopeWindow._save_layout = real_save


class TestSweepSine:
    def test_gated_when_loop_not_running(self, win):
        before = win.cl_edits["roll_tgt"].text()
        win.sweep_check.setChecked(True)          # cl_enabled=False → 不应推进
        win._sweep_tick(0.05)
        assert win.cl_edits["roll_tgt"].text() == before

    def test_sine_follows_formula(self, win):
        win.cl_enabled = True
        win.sweep_check.setChecked(True)
        win.sweep_wave_combo.setCurrentIndex(1)   # 正弦波
        win.sweep_freq.setValue(0.5)              # 0.5Hz → 2s 一整周期
        win.cl_edits["limit"].setText("10")       # A=10°
        win.sweep_axis.setCurrentIndex(0)         # ROLL
        win._sweep_phase = 0.0
        vals = []
        for _ in range(40):                       # 40 拍 × 50ms = 2s = 一个周期
            win._sweep_tick(0.05)
            vals.append(float(win.cl_edits["roll_tgt"].text()))
        for k, v in enumerate(vals, start=1):
            expect = 10.0 * math.sin(2 * math.pi * 0.5 * 0.05 * k)
            assert v == pytest.approx(expect, abs=0.02), f"tick {k}"
        assert max(vals) == pytest.approx(10.0, abs=0.5)   # 峰值≈A

    def test_triangle_unchanged(self, win):
        win.cl_enabled = True
        win.sweep_check.setChecked(True)
        win.sweep_wave_combo.setCurrentIndex(0)   # 三角波
        win.sweep_speed.setValue(1.0)
        win.cl_edits["limit"].setText("25")
        win._sweep_val = 0.0
        win._sweep_dir = 1.0
        win._sweep_tick(0.05)
        assert float(win.cl_edits["roll_tgt"].text()) == pytest.approx(0.05)

    def test_phase_resets_on_toggle(self, win):
        win.sweep_wave_combo.setCurrentIndex(1)
        win._sweep_phase = 1.234
        win.sweep_check.setChecked(False)
        win.sweep_check.setChecked(True)          # 重新勾选 → 相位归零
        assert win._sweep_phase == 0.0

    def test_dual_sine_writes_both_axes(self, win):
        """双轴正弦：同一相位、各自幅值，围绕勾选时的中心摆动。"""
        win.cl_enabled = True
        win.cl_edits["roll_tgt"].setText("0")
        win.cl_edits["pitch_tgt"].setText("0")
        win.sweep_axis.setCurrentIndex(2)          # 双轴正弦
        win.sweep_check.setChecked(True)           # 播种中心 (0,0)
        win.cl_edits["limit"].setText("10")
        win.sweep_amp.setValue(8.0)
        win.sweep_amp_p.setValue(4.0)
        win.sweep_freq.setValue(0.5)
        win._sweep_phase = math.pi / 2
        win._sweep_tick(0.05)
        s = math.sin(math.pi / 2 + 2 * math.pi * 0.5 * 0.05)
        assert float(win.cl_edits["roll_tgt"].text()) == pytest.approx(8.0 * s, abs=0.05)
        assert float(win.cl_edits["pitch_tgt"].text()) == pytest.approx(4.0 * s, abs=0.05)

    def test_dual_sine_centers_on_current_targets(self, win):
        """取消「过零对称」时，中心 = 勾选时两个目标框的值。"""
        win.cl_enabled = True
        win.cl_edits["roll_tgt"].setText("-5")
        win.cl_edits["pitch_tgt"].setText("7")
        win.cl_edits["limit"].setText("25")       # 用户布局可能是 10，会截断 7+5
        win.sweep_axis.setCurrentIndex(2)
        win.sweep_center0.setChecked(False)
        win.sweep_check.setChecked(True)
        win.sweep_amp.setValue(5.0)
        win.sweep_amp_p.setValue(5.0)
        win._sweep_phase = math.pi / 2
        win._sweep_tick(0.0)                       # dt=0 → 相位不变，sin=1
        assert float(win.cl_edits["roll_tgt"].text()) == pytest.approx(0.0, abs=0.05)
        assert float(win.cl_edits["pitch_tgt"].text()) == pytest.approx(12.0, abs=0.05)

    def test_dual_sine_zero_center_option(self, win):
        """勾「过零对称」：即使目标框偏正，中心也强制 (0,0)，正负都扫到。"""
        win.cl_enabled = True
        win.cl_edits["roll_tgt"].setText("7")
        win.cl_edits["pitch_tgt"].setText("7")
        win.sweep_axis.setCurrentIndex(2)
        win.sweep_check.setChecked(True)
        win.sweep_center0.setChecked(True)
        assert win._sweep_center == (0.0, 0.0)

    def test_sine_writes_pitch_axis(self, win):
        win.cl_enabled = True
        win.sweep_check.setChecked(True)
        win.sweep_wave_combo.setCurrentIndex(1)
        win.sweep_axis.setCurrentIndex(1)         # PITCH
        win.cl_edits["limit"].setText("5")
        win._sweep_phase = math.pi / 2            # sin(π/2)=1 → 峰值
        win._sweep_tick(0.05)
        assert float(win.cl_edits["pitch_tgt"].text()) == pytest.approx(
            5.0 * math.sin(math.pi / 2 + 2 * math.pi * 0.2 * 0.05), abs=0.05)
