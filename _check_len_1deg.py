# -*- coding: utf-8 -*-
"""1°/1° 绳长独立核算：代码公式 vs 论文闭式 s²=α+βcosθ+γsinθ vs 有限差分。"""
import math
import sys

sys.path.insert(0, r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main")
from wrist_model import SEG_PROJ_M, wrist_eval, ROLL, PITCH, N_CABLES

def s_code(theta_rad, axis, cable):
    """逐行复刻 wrist_model._segment_length_and_arm（独立抄写，防止同源错觉）。"""
    u1, u2, v1, v2, h = (x * 1000.0 for x in SEG_PROJ_M[axis][cable])  # m -> mm
    c, sn = math.cos(theta_rad), math.sin(theta_rad)
    vp1 = v1 * c - v2 * sn
    vp2 = v1 * sn + v2 * c
    d1, d2 = vp1 - u1, vp2 - u2
    return math.sqrt(d1 * d1 + d2 * d2 + h * h)

def s_closed(theta_rad, axis, cable):
    """论文闭式：s² = α + β·cosθ + γ·sinθ（由五常数推导）。"""
    u1, u2, v1, v2, h = (x * 1000.0 for x in SEG_PROJ_M[axis][cable])
    alpha = v1*v1 + v2*v2 + u1*u1 + u2*u2 + h*h
    beta = -2.0 * (v1*u1 + v2*u2)
    gamma = 2.0 * (v2*u1 - v1*u2)
    return math.sqrt(alpha + beta*math.cos(theta_rad) + gamma*math.sin(theta_rad))

print(f"{'段':<10}{'s(0°)mm':>10}{'s(+1°)':>10}{'s(-1°)':>10}{'闭式差':>12}{'±1°差μm':>10}")
th = math.radians(1.0)
for axis, name in ((ROLL, "ROLL"), (PITCH, "PITCH")):
    for cable in range(N_CABLES):
        s0 = s_code(0.0, axis, cable)
        sp = s_code(th, axis, cable)
        sm = s_code(-th, axis, cable)
        sc = s_closed(th, axis, cable)
        print(f"{name} C{cable+1:<7}{s0:10.4f}{sp:10.4f}{sm:10.4f}"
              f"{abs(sp-sc):12.2e}{(sp-sm)*1000:10.1f}")

print()
out = wrist_eval(math.radians(1.0), math.radians(1.0))
ref = wrist_eval(0.0, 0.0)
print("UI 绳长卡 1°/1° 应显示（θ_model = 1°+δ, δ=0）：")
for i in range(3):
    sr = out.s_m[ROLL][i] * 1000
    spp = out.s_m[PITCH][i] * 1000
    dsum = (out.s_m[ROLL][i] + out.s_m[PITCH][i]
            - ref.s_m[ROLL][i] - ref.s_m[PITCH][i]) * 1000
    print(f"  C{i+1}: ROLL段 {sr:8.3f}  PITCH段 {spp:8.3f}  合计 {sr+spp:8.3f}  Δ {dsum:+8.3f} mm")

print()
print("常见手算错误量级参考（C1 ROLL 段, 0°值 s0=%.4f mm）：" % s_code(0.0, ROLL, 0))
bad = math.cos(1.0)  # 把 1° 当 1 rad
u1, u2, v1, v2, h = (x * 1000.0 for x in SEG_PROJ_M[ROLL][0])
vp1, vp2 = v1*bad - v2*math.sin(1.0), v1*math.sin(1.0) + v2*bad
sbad = math.hypot(vp1-u1, vp2-u2, h)
print(f"  θ=1 rad 误用: s={sbad:.4f} mm（比正确值大 {sbad - s_code(th,ROLL,0):+.4f} mm）")
