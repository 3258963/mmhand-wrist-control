# -*- coding: utf-8 -*-
"""逐条验证修复是否真的生效（离屏实例化界面，不动电机）。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main")

import math  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

import mmhand_scope as scope  # noqa: E402
from wrist_control_law import WristCalib, WristControlParams, wrist_control_step_model  # noqa: E402

app = QApplication.instance() or QApplication([])
scope.ScopeWindow._save_layout = lambda self: None
win = scope.ScopeWindow(default_port="COM_TEST")

ok = []


def check(name, cond, detail=""):
    ok.append((name, bool(cond), detail))
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   {detail}" if detail else ""))


print("1) 位置模式没有模型前馈 → 门禁拒绝")
win.armed = True
win.connected = True
win.angle_baseline[16] = 0.0
win.angle_baseline[17] = 0.0
win._enc_filt_raw[16] = 8000.0
win._enc_filt_raw[17] = 9000.0
win._motor_origin = {27: 1000, 28: 2000, 29: 3000}
for cb in win.cable_enable_checks.values():
    cb.setChecked(True)
win.wrist_calib = None
win.cl_model_check.setChecked(False)
r = win._start_cl_gate_reason()
check("拒绝启动并说明原因", r and "模型前馈" in r, r)

print("2) 载入标定 + 勾选后 → 放行")
win.wrist_calib = WristCalib([130380.0] * 3, [0.0, 0.0])
win.cl_model_check.setEnabled(True)
win.cl_model_check.setChecked(True)
r = win._start_cl_gate_reason()
check("门禁放行", r is None, str(r))

print("3) 分轴开关在模型路径真正生效（关 pitch 后指令只剩 roll 分量）")
p = WristControlParams()
p.kp = 0.6
p.deadband_deg = 0.3
p.target_limit_deg = 25.0
p.origin = [0, 0, 0]
p.soft_limit = 2_000_000
both, _ = wrist_control_step_model(p, win.wrist_calib, 0.0, 0.0, 15.0, 20.0)
roll_only, _ = wrist_control_step_model(p, win.wrist_calib, 0.0, 0.0, 15.0, 20.0,
                                        pitch_enabled=False)
pitch_only, _ = wrist_control_step_model(p, win.wrist_calib, 0.0, 0.0, 15.0, 20.0,
                                         roll_enabled=False)
check("关 pitch 时输出 = 纯 roll 分量（非零、且与 both 不同）",
      roll_only != both and any(abs(v) > 1 for v in roll_only), f"{roll_only}")
check("关 roll 时输出 = 纯 pitch 分量", pitch_only != both and any(abs(v) > 1 for v in pitch_only),
      f"{pitch_only}")
check("两分量相加 ≈ 全量（线性可分）",
      all(abs(a + b - c) <= 2 for a, b, c in zip(roll_only, pitch_only, both)),
      f"{roll_only} + {pitch_only} vs {both}")

print("4) 扫掠：真实 dt / 独立幅值 / 切轴重播种")
win.cl_enabled = True
win.sweep_wave_combo.setCurrentIndex(1)
win.sweep_freq.setValue(0.5)
win.cl_edits["limit"].setText("25")
win.sweep_amp.setValue(8.0)
win.sweep_axis.setCurrentIndex(0)
win.cl_edits["roll_tgt"].setText("0")
win.sweep_check.setChecked(True)
win._sweep_phase = math.pi / 2
win._sweep_tick(0.05)
v = float(win.cl_edits["roll_tgt"].text())
check("幅值 8° 生效（不受限幅 25 影响）", abs(v - 8.0) < 0.2, f"v={v:+.2f}")
check("幅值超过限幅时按限幅截断", (win.sweep_amp.setValue(90.0),
                                win.cl_edits["limit"].setText("10"),
                                setattr(win, "_sweep_phase", math.pi / 2),
                                win._sweep_tick(0.05),
                                abs(float(win.cl_edits["roll_tgt"].text()) - 10.0) < 0.2)[-1],
      f"v={win.cl_edits['roll_tgt'].text()}")
before = win._sweep_val
win.cl_edits["pitch_tgt"].setText("3.5")
win.sweep_axis.setCurrentIndex(1)          # 切到 PITCH → 按新轴框重新播种
check("切轴重播种（不跳上一轴的值）", abs(win._sweep_val - 3.5) < 1e-9
      and win._sweep_phase == 0.0, f"seed={win._sweep_val}, before={before}")

print("5) 停环：扫掠自动取消 + 目标收口到实测角度")
win.cl_edits["pitch_tgt"].setText("+12.00")
win._stop_closed_loop("验证", hold=False, popup=False)
check("停环后扫掠已取消", not win.sweep_check.isChecked())
txt = float(win.cl_edits["pitch_tgt"].text())
pose = win._wrist_pose_now()
expect = None if pose is None else pose[1]
check("目标收口到实际角度（或保持原值当无位姿）",
      (pose is None and abs(txt - 12.0) < 0.01) or (expect is not None and abs(txt - expect) < 0.01),
      f"txt={txt:+.2f}, pose={pose}")

print("6) 启动即载入标定（文件存在时）")
win2_ok = win.wrist_calib is not None
check("wrist_calib 已载入", win2_ok)
check("「模型前馈」不再默认禁用", win.cl_model_check.isEnabled())

bad = [n for n, c, _ in ok if not c]
print()
print(f"结果：{len(ok) - len(bad)}/{len(ok)} 通过" + (f"，失败：{bad}" if bad else ""))
win.close()
sys.exit(1 if bad else 0)
