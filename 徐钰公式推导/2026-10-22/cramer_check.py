import sys, math
import numpy as np
sys.path.insert(0, r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main")
from wrist_model import wrist_eval, positive_null_direction
import wrist_tda as tda

out = wrist_eval(0.0, 0.0)
n = positive_null_direction(0.0, 0.0)
P = [list(out.r_m[0]), list(out.r_m[1]), list(n)]
print("P 行1 (R_roll ):", [f"{x:+.6f}" for x in P[0]])
print("P 行2 (R_pitch):", [f"{x:+.6f}" for x in P[1]])
print("P 行3 (w = n^ ):", [f"{x:+.6f}" for x in P[2]])
det = tda._det3(P)
print("det(P) =", f"{det:.6e}")
b = [0.05, -0.03, 5.0]


def det_rep(P, b, i):
    M = [row[:] for row in P]
    for r in range(3):
        M[r][i] = b[r]
    return tda._det3(M)


for i in range(3):
    num = det_rep(P, b, i)
    print(f"Cramer: det(第{i+1}列换b) = {num:+.6f}  ->  f{i+1} = {num/det:+.6f}")
A = np.array(P, dtype=float)
print("cond(P) =", f"{np.linalg.cond(A):.2f}")
print("||R_roll|| =", f"{np.linalg.norm(A[0]):.4f}", " ||R_pitch|| =", f"{np.linalg.norm(A[1]):.4f}")
print("P^-1 行1 ~ f 对 tau_r 的灵敏度 =", f"{abs(np.linalg.inv(A)[0][0]):.2f}", "N per N·m")
