# -*- coding: utf-8 -*-
"""
不用 α、β、γ 的完整算法：直接算 8 个点的位置 → 绳长 → 力臂。

三种算法互相校验：
  A. 向量链式法则（解析，PDF 式 7-9）
  B. 数值中心差分（最省事，PDF 第 8 节的 CAD 校验就是这么做的）
  C. α/β/γ 闭式（前面那个脚本，用来对照）

运行：python 计算_不用系数.py
"""
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- 数据
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
BODY = (["base"] * 4) + (["roll_link"] * 2) + (["palm"] * 2)   # P1..P8 所属刚体

O_R, A_R = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)      # roll 轴
O_P, A_P = (0.0, 0.0, 24.0), (1.0, 0.0, 0.0)     # pitch 轴（零位）

# ---------------------------------------------------------------- 向量小工具
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(s, a): return (s * a[0], s * a[1], s * a[2])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])
def norm(a): return math.sqrt(dot(a, a))


def rotate(a, theta, v):
    """罗德里格斯公式：把向量 v 绕单位轴 a 转 theta（右手，主动旋转）"""
    c, s = math.cos(theta), math.sin(theta)
    return add(add(mul(c, v), mul(s, cross(a, v))),
               mul(dot(a, v) * (1.0 - c), a))

# ---------------------------------------------------------------- A. 直接算法
def point_pos(p0, body, tr, tp):
    """点在当前姿态下的位置（零位坐标 p0 → 当前坐标）"""
    if body == "base":
        return p0
    if body == "palm":
        p = add(O_P, rotate(A_P, tp, sub(p0, O_P)))     # 先绕 pitch 转
    else:
        p = p0
    return rotate(A_R, tr, p)                            # 再被 roll 带走


def point_vel(p, body, joint, tr):
    """点对某个关节的导数 ∂p/∂θ（式 9）"""
    if joint == "roll":
        if body == "base":
            return (0.0, 0.0, 0.0)
        return cross(A_R, sub(p, O_R))
    if joint == "pitch":
        if body != "palm":
            return (0.0, 0.0, 0.0)
        o = rotate(A_R, tr, O_P)         # 当前 pitch 轴原点
        a = rotate(A_R, tr, A_P)         # 当前 pitch 轴方向
        return cross(a, sub(p, o))
    raise ValueError(joint)


def evaluate(tr, tp):
    """返回 3 根绳的长度、力臂矩阵 R（行 roll/pitch，列 C1..C3）"""
    lengths, R = [], [[], []]
    for name, pts in P.items():
        pos = [point_pos(pts[k], BODY[k], tr, tp) for k in range(8)]
        length = sum(norm(sub(pos[k + 1], pos[k])) for k in range(7))
        lengths.append(length)
        r_roll = r_pitch = 0.0
        for k in range(7):
            d = sub(pos[k + 1], pos[k])
            u = mul(1.0 / norm(d), d)                       # 该段单位方向
            for joint, acc in (("roll", "r"), ("pitch", "p")):
                dv = sub(point_vel(pos[k + 1], BODY[k + 1], joint, tr),
                         point_vel(pos[k], BODY[k], joint, tr))
                val = -dot(u, dv)                           # r = −dl/dθ
                if acc == "r":
                    r_roll += val
                else:
                    r_pitch += val
        R[0].append(r_roll)
        R[1].append(r_pitch)
    return lengths, R

# ---------------------------------------------------------------- B. 数值差分
def lengths_only(tr, tp):
    out = []
    for name, pts in P.items():
        pos = [point_pos(pts[k], BODY[k], tr, tp) for k in range(8)]
        out.append(sum(norm(sub(pos[k + 1], pos[k])) for k in range(7)))
    return out


def evaluate_numeric(tr, tp, h=1e-6):
    lp, lm = lengths_only(tr + h, tp), lengths_only(tr - h, tp)
    qp, qm = lengths_only(tr, tp + h), lengths_only(tr, tp - h)
    R = [[-(lp[i] - lm[i]) / (2 * h) for i in range(3)],
         [-(qp[i] - qm[i]) / (2 * h) for i in range(3)]]
    return R

# ---------------------------------------------------------------- C. α/β/γ 对照
def abc(A, B0, o, a):
    u, v = sub(A, o), sub(B0, o)
    return (dot(u, u) + dot(v, v) - 2 * dot(u, a) * dot(v, a),
            -2 * (dot(u, v) - dot(u, a) * dot(v, a)),
            -2 * dot(u, cross(a, v)))


COEF = {}
for name, pts in P.items():
    COEF[name] = {"roll": abc(pts[3], pts[4], O_R, A_R),
                  "pitch": abc(pts[5], pts[6], O_P, A_P)}


def evaluate_abc(tr, tp):
    R = [[], []]
    for name in ("C1", "C2", "C3"):
        for j, key in enumerate(("roll", "pitch")):
            al, be, ga = COEF[name][key]
            th = tr if key == "roll" else tp
            D = al + be * math.cos(th) + ga * math.sin(th)
            R[j].append((be * math.sin(th) - ga * math.cos(th)) / (2 * math.sqrt(D)))
    return R

# ---------------------------------------------------------------- 主程序
def main():
    print("三种算法算 R（单位 mm），看它们是否一致：")
    for tr_deg, tp_deg in ((0, 0), (4, -25), (10, 20), (-25, 45)):
        tr, tp = math.radians(tr_deg), math.radians(tp_deg)
        _, Ra = evaluate(tr, tp)
        Rn = evaluate_numeric(tr, tp)
        Rc = evaluate_abc(tr, tp)
        print()
        print(f"θr={tr_deg:>4}°  θp={tp_deg:>4}°")
        print(f"{'':<8}{'C1':>14}{'C2':>14}{'C3':>14}")
        for j, tag in ((0, "roll"), (1, "pitch")):
            print(f"A {tag:<6}" + "".join(f"{v:>14.9f}" for v in Ra[j]))
            print(f"B {tag:<6}" + "".join(f"{v:>14.9f}" for v in Rn[j]))
            print(f"C {tag:<6}" + "".join(f"{v:>14.9f}" for v in Rc[j]))
            diff_ab = max(abs(Ra[j][i] - Rn[j][i]) for i in range(3))
            diff_ac = max(abs(Ra[j][i] - Rc[j][i]) for i in range(3))
            print(f"  A−B 最大差 {diff_ab:.2e}   A−C 最大差 {diff_ac:.2e}")

    print()
    print("绳长示例（直接算法）：")
    for tr_deg, tp_deg in ((0, 0), (4, -25)):
        L, _ = evaluate(math.radians(tr_deg), math.radians(tp_deg))
        print(f"  θr={tr_deg:>3}° θp={tp_deg:>4}° : "
              + "  ".join(f"{n}={l:.6f}" for n, l in zip(("C1", "C2", "C3"), L)) + " mm")


if __name__ == "__main__":
    main()
