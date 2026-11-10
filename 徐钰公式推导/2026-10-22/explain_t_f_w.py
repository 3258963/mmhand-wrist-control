# 把 t = f·w 讲清楚：w 是什么、f 怎么求
import sys, math
CODE = r'E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main'
sys.path.insert(0, CODE)
from wrist_model import wrist_eval, positive_null_direction
import wrist_tda as tda

def dot(a, b):
    return sum(x * y for x, y in zip(a, b))

def Rf(R, f):
    return [sum(R[j][i] * f[i] for i in range(3)) for j in range(2)]

print("=" * 78)
print("A. w = n̂ 随位姿变化（单位向量，三个分量全正）")
print("=" * 78)
print(f"{'roll,pitch':>12} | {'R_roll 行 (m/rad)':>34} | {'n̂ = w':>26} | R·w")
for r_deg, p_deg in [(0, 0), (10, 10), (0, 30), (14, 0), (20, 10)]:
    rr, pp = math.radians(r_deg), math.radians(p_deg)
    out = wrist_eval(rr, pp)
    n = positive_null_direction(rr, pp)
    Rw = Rf(out.r_m, n) if n else None
    rr_s = f"[{out.r_m[0][0]:+.4f},{out.r_m[0][1]:+.4f},{out.r_m[0][2]:+.4f}]"
    nn = f"({n[0]:.4f},{n[1]:.4f},{n[2]:.4f})" if n else "None"
    rw = f"({Rw[0]:+.1e},{Rw[1]:+.1e})" if Rw else "-"
    print(f"{r_deg:>5},{p_deg:<5} | {rr_s} | {nn} | {rw}")

print()
print("=" * 78)
print("B. 只有 t = f·w 时，f 不唯一（3 未知、1 方程）")
print("=" * 78)
rr, pp = 0.0, 0.0
out = wrist_eval(rr, pp)
n = positive_null_direction(rr, pp)
t_target = 5.0
f0 = [t_target * x for x in n]
print(f"w=n̂=({n[0]:.4f},{n[1]:.4f},{n[2]:.4f})，t*={t_target} N")
print(f"解 1（纯预紧 f=t·w）: f=[{f0[0]:.3f},{f0[1]:.3f},{f0[2]:.3f}]"
      f"  → f·w={dot(f0,n):.4f}  τ=R·f=({Rf(out.r_m,f0)[0]:+.2e},{Rf(out.r_m,f0)[1]:+.2e})")
# 任取一个与 w 正交的扰动 → t 不变、τ 变
d = [1.0, -1.0, 0.0]
proj = dot(d, n)
d_orth = [d[i] - proj * n[i] for i in range(3)]
f1 = [f0[i] + 2.0 * d_orth[i] for i in range(3)]
print(f"解 2（f=t·w+2·Δ，Δ⊥w）: f=[{f1[0]:.3f},{f1[1]:.3f},{f1[2]:.3f}]"
      f"  → f·w={dot(f1,n):.4f}  τ=R·f=({Rf(out.r_m,f1)[0]:+.4f},{Rf(out.r_m,f1)[1]:+.4f})")
print("  ⇒ 两个解 t 都是 5N，力矩却完全不同 → 必须再加 τ=R·f 两条方程")

print()
print("=" * 78)
print("C. 补上 τ = R·f 后的 3×3 求解  f = P⁻¹[τ;t]")
print("=" * 78)
for tau_r, tau_p, t in [(0.0, 0.0, 5.0), (0.05, -0.03, 5.0), (0.10, 0.05, 8.0)]:
    f, flags, alpha = tda.tda_solve(out.r_m, n, tau_r, tau_p, t, 0.5, 50.0)
    got_tau = Rf(out.r_m, f)
    print(f"τ*=({tau_r:+.2f},{tau_p:+.2f}) t*={t:>4} → f=[{f[0]:6.3f},{f[1]:6.3f},{f[2]:6.3f}]"
          f"  f·w={dot(f,n):.4f}  实际τ=({got_tau[0]:+.4f},{got_tau[1]:+.4f})  α={alpha:.2f}")

print()
print("=" * 78)
print("D. 如果 w 乱选（w=(1,1,1)/√3，不是零空间方向）")
print("=" * 78)
w_bad = [1 / math.sqrt(3)] * 3
P = [list(out.r_m[0]), list(out.r_m[1]), w_bad]
Pin = tda._inv3(P)
b = [0.05, -0.03, 5.0]
f_bad = tda._mat_vec(Pin, b)
print(f"w_bad·n̂ = {dot(w_bad, n):.4f}（≠1 ⇒ t 的物理含义已变）")
print(f"指令 τ=(0.05,-0.03) t=5 → f=[{f_bad[0]:.3f},{f_bad[1]:.3f},{f_bad[2]:.3f}]")
print(f"  实际 f·w_bad={dot(f_bad,w_bad):.4f}（=5 ✓ 因为方程就是这么写的）")
print(f"  但真正的零空间份量 f·n̂={dot(f_bad,n):.4f} ≠ 5"
      f"  → 你以为预紧 5N，其实是 {dot(f_bad,n):.3f}N")
print(f"  力矩仍准：τ=R·f=({Rf(out.r_m,f_bad)[0]:+.4f},{Rf(out.r_m,f_bad)[1]:+.4f})")

print()
print("=" * 78)
print("E. 张紧模式实际不做矩阵求逆：增量式沿 w 分配")
print("=" * 78)
t_meas, t_tgt = 4.5, 5.0
err = t_tgt - t_meas
print(f"t_meas={t_meas} t*={t_tgt} → err={err:.3f}")
print("e_i = err·w_i =", [f"{err*x:+.4f}" for x in n])
f_now = [4.5 * x for x in n]
df = [err * x for x in n]
print(f"若 f={[f'{x:.3f}' for x in f_now]}，一步加 δf=err·w=[{df[0]:+.3f},{df[1]:+.3f},{df[2]:+.3f}]")
print(f"  δt = δf·w = {dot(df,n):+.4f}（=err，收敛）")
print(f"  R·δf = ({Rf(out.r_m,df)[0]:+.2e},{Rf(out.r_m,df)[1]:+.2e})（≈0，力矩不动）")
