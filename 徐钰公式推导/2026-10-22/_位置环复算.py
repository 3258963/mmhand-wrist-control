# -*- coding: utf-8 -*-
"""用一页纸参数复现位置闭环的指令量：M27/28/29 该收到什么。"""
import math
import sys

sys.path.insert(0, r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main")
from wrist_control_law import WristCalib, WristControlParams, wrist_control_step, wrist_control_step_model  # noqa: E402
from wrist_model import wrist_eval  # noqa: E402

K = 130380.0            # counts/m（草稿值）
CALIB = WristCalib([K, K, K], [0.0, 0.0])

def params():
    p = WristControlParams()
    p.origin = [0, 0, 0]
    p.kp = 0.6
    p.deadband_deg = 0.3          # 布局里 deadband 为空 -> 默认 0.3
    p.target_limit_deg = 25.0
    p.soft_limit = 2_000_000
    return p

print("=" * 84)
print("A) 模型前馈【勾上】：目标 roll=15°, pitch=20°，反馈 0°")
print("=" * 84)
for fb in [(0.0, 0.0), (7.5, 10.0), (15.0, 20.0), (20.0, 25.0)]:
    out, flags = wrist_control_step_model(params(), CALIB, fb[0], fb[1], 15.0, 20.0)
    print(f"  反馈 ({fb[0]:5.1f},{fb[1]:5.1f})° -> M27/M28/M29 = {out}  (相对 origin)")

print()
print("=" * 84)
print("B) 模型前馈【不勾】：位置模式只剩 origin（系数全 0）")
print("=" * 84)
out = wrist_control_step(params(), 0.0, 0.0, 15.0, 20.0)
print(f"  M27/M28/M29 = {out}   <-- 就是 origin，和启动时 targets 完全相等")
print("  => _clamp_per_tick 判 v == targets，整帧被丢弃，100Hz 一帧都不发。")

print()
print("=" * 84)
print("C) 反馈角若卡住不动（编码器没跟上），指令会怎样")
print("=" * 84)
for i in range(4):
    out, _ = wrist_control_step_model(params(), CALIB, 0.0, 0.0, 15.0, 20.0)
    print(f"  第{i+1}拍（反馈恒 0）-> {out}   每拍限幅 50 counts 后逐步爬")
print("  说明：反馈卡死时指令是一个固定终点，不会无限爬；但终点是错的。")

print()
print("=" * 84)
print("D) k 的符号整体取反（装反/映射反）时，同一目标给出的指令")
print("=" * 84)
calib_neg = WristCalib([-K, -K, -K], [0.0, 0.0])
out_neg, _ = wrist_control_step_model(params(), calib_neg, 0.0, 0.0, 15.0, 20.0)
out_pos, _ = wrist_control_step_model(params(), CALIB, 0.0, 0.0, 15.0, 20.0)
print(f"  k>0: {out_pos}")
print(f"  k<0: {out_neg}")
print("  两行完全反号 -> 收绳/放绳整体反向。")

print()
print("=" * 84)
print("E) 每 1° 绳长变化（counts），用于判断量级对不对")
print("=" * 84)
o0 = wrist_eval(0.0, 0.0)
for axis, an in ((0, "roll"), (1, "pitch")):
    for i in range(3):
        mm = abs(o0.r_m[axis][i]) * 1000.0 * math.radians(1.0)
        print(f"  {an:5s} C{i+1}: |r|={abs(o0.r_m[axis][i])*1000:7.3f} mm -> 1° 约 {mm:6.3f} mm = {mm*K/1000:7.1f} counts")
