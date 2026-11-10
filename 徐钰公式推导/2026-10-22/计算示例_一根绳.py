# -*- coding: utf-8 -*-
"""
一根绳的解析计算：从 8 个零位点位 → c、α/β/γ → 任意角度的绳长 s 与力臂 r。

运行：  python 计算示例_一根绳.py
依赖：  只用 Python 标准库（math）。长度单位 mm，角度内部用 rad。

对应 PDF：式 (14)(15)-(21)(22)-(23)(24)
"""

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------------------------
# 1. 备料：零位坐标（mm）+ 两条轴线
#    这些数来自 PDF 附录 D3 的 24 点表，按"绳内顺序"存放
# ----------------------------------------------------------------------------
P = {
    "C1": [(27.0, 85.0, -35.0), (27.0, 85.0, -27.0), (0.5, 55.0, -5.0), (0.5, 55.0, 5.0),
           (2.5, 58.0, 18.0), (2.5, 58.0, 30.0), (2.321457, 53.0, 56.472169),
           (2.321457, 53.0, 61.472169)],
    "C2": [(-23.0, -20.0, -35.0), (-23.0, -20.0, -27.0), (-27.0, -16.0, -5.0),
           (-27.0, -16.0, 5.0), (-32.5, -12.0, 18.0), (-32.5, -12.0, 30.0),
           (-32.216413, -12.5, 46.0), (-32.216413, -15.5, 54.0)],
    "C3": [(23.0, -20.0, -35.0), (23.0, -20.0, -27.0), (27.0, -16.0, -5.0),
           (27.0, -16.0, 5.0), (37.5, -12.0, 18.0), (37.5, -12.0, 30.0),
           (43.783587, -12.5, 46.0), (43.783587, -15.5, 54.0)],
}

O_ROLL, A_ROLL = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)          # roll 轴上一点 / 方向
O_PITCH, A_PITCH = (0.0, 0.0, 24.0), (1.0, 0.0, 0.0)       # pitch 轴抬高 24 mm

# ----------------------------------------------------------------------------
# 2. 几个小工具
# ----------------------------------------------------------------------------
def sub(a, b):  return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def dot(a, b):  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])
def norm(a):    return math.sqrt(dot(a, a))

# ----------------------------------------------------------------------------
# 3. 第一步：c_i = 五段"同刚体"长度之和（这些段永远不变）
# ----------------------------------------------------------------------------
def constant_length(pts):
    pairs = [(0, 1), (1, 2), (2, 3), (4, 5), (6, 7)]   # P1P2 P2P3 P3P4 P5P6 P7P8
    return sum(norm(sub(pts[b], pts[a])) for a, b in pairs)

# ----------------------------------------------------------------------------
# 4. 第二步：三个系数 α/β/γ（式 19-21）
#    A  = 跨关节段的固定端，B0 = 运动端零位，o/a = 该关节轴上一点与方向
# ----------------------------------------------------------------------------
def coefficients(A, B0, o, a):
    u = sub(A, o)
    v = sub(B0, o)
    alpha = dot(u, u) + dot(v, v) - 2.0 * dot(u, a) * dot(v, a)
    beta  = -2.0 * (dot(u, v) - dot(u, a) * dot(v, a))
    gamma = -2.0 * dot(u, cross(a, v))
    return alpha, beta, gamma

# ----------------------------------------------------------------------------
# 5. 第三步：任意角度下的段长 s 与力臂 r（式 18、22、23）
# ----------------------------------------------------------------------------
def length_and_arm(theta, alpha, beta, gamma):
    D = alpha + beta * math.cos(theta) + gamma * math.sin(theta)   # = s²
    if D <= 0:
        raise ValueError("D<=0：这个角度下该段退化，不能开根号")
    s = math.sqrt(D)
    r = (beta * math.sin(theta) - gamma * math.cos(theta)) / (2.0 * s)
    return s, r, D

# ----------------------------------------------------------------------------
# 6. 主流程：算三根绳，打印六组系数 + 零位 R 矩阵
# ----------------------------------------------------------------------------
def main():
    print("单位：长度 mm，系数 mm²，力臂 mm/rad")
    print()
    print(f"{'绳':<4}{'c_i':>12}   段   {'α':>16}{'β':>16}{'γ':>14}")
    print("-" * 68)

    coef = {}
    for name, pts in P.items():
        c = constant_length(pts)
        # roll 段 = P04(固定, base) → P05(运动, roll件)
        cr = coefficients(pts[3], pts[4], O_ROLL, A_ROLL)
        # pitch 段 = P06(固定, roll件) → P07(运动, palm)
        cp = coefficients(pts[5], pts[6], O_PITCH, A_PITCH)
        coef[name] = {"c": c, "roll": cr, "pitch": cp}
        print(f"{name:<4}{c:>12.6f}  roll  {cr[0]:>16.6f}{cr[1]:>16.6f}{cr[2]:>14.6f}")
        print(f"{'':<4}{'':>12}  pitch {cp[0]:>16.6f}{cp[1]:>16.6f}{cp[2]:>14.6f}")

    print()
    print("注：这里用附录里 6 位小数的坐标；与全精度 JSON 相比，系数末几位差 1e-5 量级，属正常。")
    print()
    print("零位（θr=θp=0）力臂矩阵 R / mm")
    print(f"{'':<7}{'C1':>12}{'C2':>12}{'C3':>12}")
    for row, key, o in (("roll", "roll", O_ROLL), ("pitch", "pitch", O_PITCH)):
        vals = [length_and_arm(0.0, *coef[n][key])[1] for n in ("C1", "C2", "C3")]
        print(f"{row:<7}" + "".join(f"{v:>12.6f}" for v in vals))

    print()
    print("任意角度示例（C1，roll 段）：")
    for deg in (0.0, 10.0, 25.0):
        s, r, D = length_and_arm(math.radians(deg), *coef["C1"]["roll"])
        print(f"  θr={deg:>5.1f}°   D={D:>10.4f} mm²   s={s:>9.6f} mm   r={r:>+10.6f} mm")

    print()
    print("整根绳长度示例（C1）：")
    for tr, tp in ((0, 0), (4, -25)):
        s_r = length_and_arm(math.radians(tr), *coef["C1"]["roll"])[0]
        s_p = length_and_arm(math.radians(tp), *coef["C1"]["pitch"])[0]
        total = coef["C1"]["c"] + s_r + s_p
        print(f"  θr={tr:>3}° θp={tp:>4}° : "
              f"{coef['C1']['c']:.6f} + {s_r:.6f} + {s_p:.6f} = {total:.6f} mm")


if __name__ == "__main__":
    main()
