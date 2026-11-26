"""闭环参数控件「多模式共用 / 单一模式可调」的两处修补（2026-11-26）。

背景（实机扫出来的两个坑）：

1. **阻抗的死区**原来读的是位置模式那个 `deadband` 框，而它所在的「角度参数」行
   在阻抗模式下整行隐藏 → 阻抗死区**根本改不了**。现在阻抗行有了自己的
   `imp_deadband`，留空 = 沿用位置模式的值（旧行为逐位不变）。
2. **位置模式每拍都跑 `_tension_guard`**（张力过载 → 停环），阈值是 `f_min` /
   `fmax_f`，但它们原来藏在只有力控可见的「边界」行里 → **位置模式改不了过载阈值**。
   现在单独一行 `_cl_flim_row_w`，位置模式与四个力控都可见。

另外顺带修了初始化：`_build_cl_box` 结束时按当前模式刷一次可见性，
避免「布局里没有 cl_mode」时各行停在构造默认值（fmin 就因此不显示过）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import mmhand_scope as scope


@pytest.fixture(scope="module")
def win():
    real_load = scope.load_layout_json
    scope.load_layout_json = lambda: {}
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    w = scope.ScopeWindow(default_port="COM_TEST")
    yield w
    try:
        w._admit_timer.stop()
        w._zero_timer.stop()
        w._ramp_timer.stop()
    except Exception:
        pass
    scope.load_layout_json = real_load
    w.close()


def _set_mode(w, mode):
    w.cl_mode_combo.setCurrentIndex(w.cl_mode_combo.findData(mode))


def _eff_visible(widget):
    """真正看得见：沿父链检查，遇到顶层窗口就停（窗口本身没 show 不算隐藏）。"""
    p = widget
    while p is not None and not p.isWindow():
        if p.isHidden():
            return False
        p = p.parentWidget()
    return True


# ---------------- 1. 阻抗死区 ----------------

def test_imp_deadband_empty_falls_back_to_position_deadband(win):
    _set_mode(win, "impedance")
    win.cl_edits["deadband"].setText("0.35")
    win.cl_edits["imp_deadband"].setText("")
    assert win._imp_deadband() == pytest.approx(0.35)


def test_imp_deadband_overrides(win):
    _set_mode(win, "impedance")
    win.cl_edits["deadband"].setText("0.35")
    win.cl_edits["imp_deadband"].setText("0.8")
    assert win._imp_deadband() == pytest.approx(0.8)


def test_imp_deadband_zero_means_no_deadband(win):
    _set_mode(win, "impedance")
    win.cl_edits["deadband"].setText("0.35")
    win.cl_edits["imp_deadband"].setText("0")
    assert win._imp_deadband() == pytest.approx(0.0)


def test_imp_deadband_garbage_falls_back(win):
    _set_mode(win, "impedance")
    win.cl_edits["deadband"].setText("0.2")
    win.cl_edits["imp_deadband"].setText("abc")
    assert win._imp_deadband() == pytest.approx(0.2)


def test_impedance_params_uses_imp_deadband(win):
    """端到端：`_impedance_params` 必须走 `_imp_deadband`（不是裸读 deadband）。"""
    _set_mode(win, "impedance")
    win.cl_edits["deadband"].setText("0.1")
    win.cl_edits["imp_deadband"].setText("0.9")
    p = win._impedance_params(0.0, 0.0)
    assert p is not None
    assert p.deadband_deg == pytest.approx(0.9)


# ---------------- 2. fmin/fmax 在位置模式可见 ----------------

def test_flim_row_visible_in_position(win):
    _set_mode(win, "position")
    assert _eff_visible(win.cl_edits["f_min"])
    assert _eff_visible(win.cl_edits["fmax_f"])


def test_flim_row_visible_in_force_family(win):
    for mode in ("force", "tension", "tight", "impedance"):
        _set_mode(win, mode)
        assert _eff_visible(win.cl_edits["f_min"]), mode
        assert _eff_visible(win.cl_edits["fmax_f"]), mode


def test_flim_row_hidden_in_mixed(win):
    """混合模式用自己的 C1 上下限，不显示 fmin/fmax。"""
    _set_mode(win, "c1_position")
    assert not _eff_visible(win.cl_edits["f_min"])
    assert not _eff_visible(win.cl_edits["fmax_f"])


def test_bound_row_still_force_only(win):
    """边界行（tmin/tmax/τ上限/τ方向）仍然只在力控家族显示。"""
    _set_mode(win, "position")
    assert not _eff_visible(win.cl_edits["tau_r_max"])
    _set_mode(win, "force")
    assert _eff_visible(win.cl_edits["tau_r_max"])


# ---------------- 3. 初始化就按当前模式刷可见性 ----------------

def test_visibility_correct_without_saved_mode(win):
    """布局里没有 cl_mode（首次启动）时，也不能让 fmin 停在构造默认的隐藏态。"""
    # 构造时已调用 _apply_cl_mode_visibility；这里再确认一遍幂等
    _set_mode(win, "position")
    win._apply_cl_mode_visibility()
    assert _eff_visible(win.cl_edits["f_min"])

# ---------------- 4. 扫掠：只剩正弦（2026-11-26 去掉三角波） ----------------

def test_sweep_has_no_triangle_wave(win):
    """三角波已删除：不再有波形下拉/速度框，频率永远可用。"""
    assert not hasattr(win, "sweep_wave_combo")
    assert not hasattr(win, "sweep_speed")
    _set_mode(win, "position")
    assert win.sweep_freq.isEnabled()


def test_sweep_freq_always_enabled(win):
    """三种轴下频率框都必须可编辑（修前三角波下是灰的）。"""
    _set_mode(win, "position")
    for ax in (0, 1, 2):
        win.sweep_axis.setCurrentIndex(ax)
        assert win.sweep_freq.isEnabled(), f"轴={ax} 时频率被禁用"
    win.sweep_freq.setValue(0.35)
    assert win.sweep_freq.value() == pytest.approx(0.35)


def test_sweep_pitch_amp_only_on_dual(win):
    _set_mode(win, "position")
    win.sweep_axis.setCurrentIndex(0)
    assert not win.sweep_amp_p.isEnabled()
    win.sweep_axis.setCurrentIndex(2)
    assert win.sweep_amp_p.isEnabled()


def test_sweep_hint_label_shows_active_params(win):
    _set_mode(win, "position")
    win.sweep_axis.setCurrentIndex(0)
    win.sweep_freq.setValue(0.75)
    txt = win.sweep_active_label.text()
    assert "ROLL" in txt and "0.75" in txt


def test_sweep_hint_shows_both_amps_on_dual(win):
    _set_mode(win, "position")
    win.sweep_axis.setCurrentIndex(2)
    win.sweep_amp.setValue(7.0)
    win.sweep_amp_p.setValue(3.0)
    txt = win.sweep_active_label.text()
    assert "7" in txt and "3" in txt


def test_sweep_allowed_in_position_and_impedance_only(win):
    """扫掠：位置 + 阻抗可用；三个力控模式与混合模式禁用。"""
    _set_mode(win, "position")
    assert win.sweep_check.isEnabled()
    _set_mode(win, "impedance")
    assert win.sweep_check.isEnabled(), "阻抗模式应当允许扫掠（输入就是 q*）"
    for mode in ("force", "tension", "tight", "c1_position"):
        _set_mode(win, mode)
        assert not win.sweep_check.isEnabled(), mode
    _set_mode(win, "position")


# ---------------- 5. 混合模式自动勾上位姿曲线（2026-11-26） ----------------

_POSE_KEYS = ("pose_roll", "pose_roll_tgt", "pose_pitch", "pose_pitch_tgt")


def _checked(win):
    return [k for k, c in win.channels.items()
            if c.tree_item.checkState(0) == scope.Qt.Checked]


def test_hybrid_mode_autochecks_all_pose_curves(win):
    """混控模式下四条位姿曲线必须自动勾上（实测：数据一直在写，纯粹没勾不画）。"""
    _set_mode(win, "tension")
    for k in _POSE_KEYS:                      # 清掉位姿选择
        win.channels[k].tree_item.setCheckState(0, scope.Qt.Unchecked)
    win.channels["pose_roll"].tree_item.setCheckState(0, scope.Qt.Checked)
    _set_mode(win, "c1_position")
    ck = _checked(win)
    for k in _POSE_KEYS:
        assert k in ck, f"{k} 没被自动勾上"
        assert win.channels[k].curve is not None, f"{k} 曲线没建出来"


def test_hybrid_autocheck_is_additive(win):
    """只加不减：用户已选的其它通道不能被清掉。"""
    _set_mode(win, "tension")
    win.channels["tension_f1"].tree_item.setCheckState(0, scope.Qt.Checked)
    for k in _POSE_KEYS:
        win.channels[k].tree_item.setCheckState(0, scope.Qt.Unchecked)
    _set_mode(win, "c1_position")
    assert "tension_f1" in _checked(win)


def test_hybrid_autocheck_idempotent(win):
    _set_mode(win, "c1_position")
    win._ensure_hybrid_curves()
    before = sorted(_checked(win))
    win._ensure_hybrid_curves()
    assert sorted(_checked(win)) == before


def test_hybrid_preset_exists_and_covers_pose(win):
    assert "混合调试" in win.PRESETS
    keys = win.PRESETS["混合调试"]
    for k in _POSE_KEYS:
        assert k in keys
    assert "tension_f1" in keys

# ---------------- 6. 混合模式的目标曲线必须跟着正弦走（2026-11-26 实报） ----------------

def _pose_ready(win):
    """让 `_wrist_pose_now()` 返回 (0,0)、并给一个时间基准。"""
    win._enc_filt_raw[16] = 5000
    win._enc_filt_raw[17] = 5000
    win.angle_baseline[16] = win._axis_deg(16, 5000)
    win.angle_baseline[17] = win._axis_deg(17, 5000)
    win._latest_t = 1.0


def test_hybrid_cmd_targets_drive_curves(win):
    """`_c1_cmd_tgt` 一设，pose_*_tgt 与 tension_f1_tgt 必须跟着变。

    修前：pose_*_tgt 用的是界面框（常数），tension_f1_tgt 从来没被写过
    —— 表现就是"开了混合正弦，目标曲线一动不动"。
    """
    _set_mode(win, "c1_position")
    _pose_ready(win)
    win.cl_enabled = True
    try:
        win._c1_cmd_tgt = (5.0, -10.0, 8.0)
        win._update_tables()
        assert win.channels["pose_roll_tgt"].buf.last() == pytest.approx(5.0)
        assert win.channels["pose_pitch_tgt"].buf.last() == pytest.approx(-10.0)
        assert win.channels["tension_f1_tgt"].buf.last() == pytest.approx(8.0)
        # 换一个相位
        win._c1_cmd_tgt = (-5.0, 10.0, 2.0)
        win._update_tables()
        assert win.channels["pose_roll_tgt"].buf.last() == pytest.approx(-5.0)
        assert win.channels["tension_f1_tgt"].buf.last() == pytest.approx(2.0)
    finally:
        win._c1_cmd_tgt = None
        win.cl_enabled = False


def test_hybrid_cmd_targets_update_big_labels(win):
    _set_mode(win, "c1_position")
    _pose_ready(win)
    win.cl_enabled = True
    try:
        win._c1_cmd_tgt = (5.0, -10.0, 8.0)
        win._update_tables()
        assert "+5.00" in win.cl_roll_now.text()
        assert "-10.00" in win.cl_pitch_now.text()
    finally:
        win._c1_cmd_tgt = None
        win.cl_enabled = False


def test_hybrid_curves_fall_back_to_ui_when_stopped(win):
    """停环（`_c1_cmd_tgt=None`）后目标曲线回到界面框的值，不再停在命令值。"""
    _set_mode(win, "c1_position")
    _pose_ready(win)
    win.cl_enabled = True
    try:
        win._c1_cmd_tgt = (5.0, -10.0, 8.0)
        win._update_tables()
        win._c1_cmd_tgt = None                  # 等价于停环后的状态
        win._update_tables()
        # 界面目标角留空 → 用实测角 0；不应再是 5.0
        assert win.channels["pose_roll_tgt"].buf.last() == pytest.approx(0.0, abs=1e-6)
    finally:
        win.cl_enabled = False
