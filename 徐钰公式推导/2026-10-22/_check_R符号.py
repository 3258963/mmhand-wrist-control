# -*- coding: utf-8 -*-
"""核对 R 矩阵里每个负号的含义：r = -ds/dθ 的数值验证。"""
import math
import sys

sys.path.insert(0, r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main")
import wrist_model as wm  # noqa: E402

deg = math.radians


def seg_len(theta, axis, cable):
    u1, u2, v1, v2, h = wm.SEG_PROJ_M[axis][cable]
    c, s = math.cos(theta), math.sin(theta)
    vp1, vp2 = v1 * c - v2 * s, v1 * s + v2 * c
    d1, d2 = vp1 - u1, vp2 - u2
    return math.sqrt(d1 * d1 + d2 * d2 + h * h)


names = ["C1", "C2", "C3"]
print("=" * 78)
print("1) 零位 R（mm），以及数值微分 -ds/dθ 对照")
print("=" * 78)
out = wm.wrist_eval(0.0, 0.0)
eps = 1e-6
for axis, axis_name in ((wm.ROLL, "roll"), (wm.PITCH, "pitch")):
    for cab in range(3):
        r = out.r_m[axis][cab] * 1000.0
        s_plus = seg_len(eps, axis, cab)
        s_minus = seg_len(-eps, axis, cab)
        num = -(s_plus - s_minus) / (2 * eps) * 1000.0
        print(f"  {axis_name:5s} {names[cab]}: r = {r:+9.4f} mm    -ds/dθ = {num:+9.4f} mm   差 {r-num:+.2e}")

print()
print("=" * 78)
print("2) 符号的含义：r<0 时，关节正转 1° 这根绳是变长还是变短？")
print("=" * 78)
for axis, axis_name in ((wm.ROLL, "roll"), (wm.PITCH, "pitch")):
    for cab in range(3):
        r = out.r_m[axis][cab] * 1000.0
        s0 = seg_len(0.0, axis, cab) * 1000.0
        s1 = seg_len(deg(1.0), axis, cab) * 1000.0
        trend = "变长" if s1 > s0 else "变短"
        print(f"  {axis_name:5s} {names[cab]}: r={r:+9.4f}  →  +1° 绳长 {s0:8.3f} → {s1:8.3f} mm（{trend} {s1-s0:+.4f}）")

print()
print("=" * 78)
print("3) tau = R f 的物理意义：只在 C2 上加 1 N 张力")
print("=" * 78)
for axis, axis_name in ((wm.ROLL, "roll"), (wm.PITCH, "pitch")):
    tau = out.r_m[axis][1] * 1000.0  # mm * N = mN·m
    sense = "负向（阻碍正转）" if tau < 0 else "正向（助推正转）"
    print(f"  {axis_name:5s}: tau = {tau:+8.4f} mN·m  → {sense}")

print()
print("=" * 78)
print("4) C2/roll 的 r 随角度变化（越过 r=0 就变号）")
print("=" * 78)
for d in (-25, -20, -10, 0, 10, 20, 25, 30):
    r = wm.wrist_eval(deg(d), 0.0).r_m[wm.ROLL][1] * 1000.0
    s = seg_len(deg(d), wm.ROLL, 1) * 1000.0
    print(f"  θr = {d:+4d}° : s = {s:8.3f} mm   r = {r:+9.4f} mm")

print()
print("=" * 78)
print("5) 丢掉外层负号会怎样：R' = +(∂l/∂q)^T  →  同一张力给出反向力矩")
print("=" * 78)
J = [[-out.r_m[a][c] * 1000.0 for c in range(3)] for a in range(2)]
print("  +(∂l/∂q)^T 零位 =")
for row in J:
    print("     " + "  ".join(f"{v:+9.4f}" for v in row))
print("  -(∂l/∂q)^T 零位 =")
for row in out.r_m:
    print("     " + "  ".join(f"{v*1000:+9.4f}" for v in row))
