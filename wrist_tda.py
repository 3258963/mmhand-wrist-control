"""张力分配算法 TDA（Tension Distribution Algorithm）—— 纯函数，无 UI/串口依赖。

论文 §8.3 的核心贡献：给定期望关节力矩 τ_d 和预紧参数 t，
在上下限约束 [f_min, f_max]^3 内求三缆张力 f_d，饱和时用标量 α 优雅缩力矩。

数学：
    P = [R(q)(2×3); n̂ᵀ(1×3)]   —— 3×3 可逆（n̂ = positive_null_direction）
    f_d = P⁻¹ · [τ_r, τ_p, t]ᵀ
    约束：f_min ≤ f_d[i] ≤ f_max
    超界时：α·τ_d + P⁻¹·[0,0,t]ᵀ 仍满足约束，α ∈ [0,1] 二分/闭式

单位：τ N·m，f N，R m/rad（wrist_model 已提供）。

对应 C 结构（移植用）：
    typedef struct {
        float f_min_n, f_max_n;   /* 上下限 N */
        float alpha_min;          /* α 下限（低于此返回不可行 */
    } tda_params_t;
    int tda_solve(const float P_inv[9], const float tau_d[2],
                  float t, const tda_params_t *p, float f_d[3],
                  float *alpha_out);
"""
from __future__ import annotations

import math

TDA_OK = 0
TDA_NO_NULL = 1 << 0        # 该姿态无正零空间方向（n̂ 不存在）
TDA_SINGULAR = 1 << 1       # P 矩阵奇异（det≈0）
TDA_INFEASIBLE = 1 << 2     # 连 α=0 都不满足约束
TDA_ALPHA_CLAMPED = 1 << 3  # α < 1，力矩被缩放


def _det3(m) -> float:
    """3×3 行列式（列表的列表，row-major）。"""
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
          - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
          + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _inv3(m):
    """3×3 逆（伴随法）。返回 None 如果奇异。"""
    det = _det3(m)
    if abs(det) < 1e-12:
        return None
    inv_det = 1.0 / det
    # 伴随矩阵 / det
    return [
        [(m[1][1]*m[2][2] - m[1][2]*m[2][1]) * inv_det,
         (m[0][2]*m[2][1] - m[0][1]*m[2][2]) * inv_det,
         (m[0][1]*m[1][2] - m[0][2]*m[1][1]) * inv_det],
        [(m[1][2]*m[2][0] - m[1][0]*m[2][2]) * inv_det,
         (m[0][0]*m[2][2] - m[0][2]*m[2][0]) * inv_det,
         (m[0][2]*m[1][0] - m[0][0]*m[1][2]) * inv_det],
        [(m[1][0]*m[2][1] - m[1][1]*m[2][0]) * inv_det,
         (m[0][1]*m[2][0] - m[0][0]*m[2][1]) * inv_det,
         (m[0][0]*m[1][1] - m[0][1]*m[1][0]) * inv_det],
    ]


def _mat_vec(m, v):
    """3×3 矩阵 × 3 向量。"""
    return [m[i][0]*v[0] + m[i][1]*v[1] + m[i][2]*v[2] for i in range(3)]


def tda_solve(r_m, null_dir, tau_roll, tau_pitch, preload_t,
              f_min, f_max):
    """TDA 主入口。

    Args:
        r_m: 2×3 力臂矩阵 [m/rad]（wrist_eval 的 r_m）
        null_dir: 3 元组，正零空间方向（positive_null_direction 的返回值）
        tau_roll, tau_pitch: 期望关节力矩 [N·m]
        preload_t: 预紧参数 [N]（沿零空间方向的张力分量）
        f_min, f_max: 每缆上下限 [N]

    Returns:
        (f_d[3] | None, flags, alpha)
        f_d = 分配出的三缆张力目标 [N]
        alpha ∈ [0,1]，1 = 完整力矩，<1 = 缩放后
        None = 不可行（flags 说明原因）
    """
    if null_dir is None:
        return None, TDA_NO_NULL, 0.0

    # 构造 P = [R; n^T] (3×3)
    P = [
        [r_m[0][0], r_m[0][1], r_m[0][2]],
        [r_m[1][0], r_m[1][1], r_m[1][2]],
        [null_dir[0], null_dir[1], null_dir[2]],
    ]
    P_inv = _inv3(P)
    if P_inv is None:
        return None, TDA_SINGULAR, 0.0

    # b_full = [τ_r, τ_p, t]
    b_full = [tau_roll, tau_pitch, preload_t]
    f_full = _mat_vec(P_inv, b_full)

    # 检查完整解是否在界内
    if all(f_min <= f <= f_max for f in f_full):
        return [float(f) for f in f_full], TDA_OK, 1.0

    # 超界：找最大 α 使 α·τ + 预紧仍在界内
    # b(α) = [α·τ_r, α·τ_p, t]，f(α) = P⁻¹·b(α) = α·f_τ + f_t
    # 其中 f_τ = P⁻¹·[τ_r, τ_p, 0]，f_t = P⁻¹·[0, 0, t]
    f_tau = _mat_vec(P_inv, [tau_roll, tau_pitch, 0.0])
    f_t = _mat_vec(P_inv, [0.0, 0.0, preload_t])

    # f_i(α) = α·f_tau[i] + f_t[i]，约束 f_min ≤ f_i(α) ≤ f_max
    # → α ∈ [(f_min - f_t[i]) / f_tau[i], (f_max - f_t[i]) / f_tau[i]]（f_tau[i] > 0 时）
    #   区间反转 f_tau[i] < 0 时
    lo, hi = 0.0, 1.0
    for i in range(3):
        ft = f_tau[i]
        fb = f_t[i]
        if abs(ft) < 1e-12:
            # 该缆不依赖 α，检查预紧分量自身
            if fb < f_min or fb > f_max:
                return None, TDA_INFEASIBLE, 0.0
            continue
        if ft > 0:
            a_lo = (f_min - fb) / ft
            a_hi = (f_max - fb) / ft
        else:
            a_lo = (f_max - fb) / ft
            a_hi = (f_min - fb) / ft
        lo = max(lo, a_lo)
        hi = min(hi, a_hi)

    if lo > hi:
        # 连 α=0 都不可行（预紧自身超界）
        return None, TDA_INFEASIBLE, 0.0

    alpha = min(hi, 1.0)
    if alpha < 0.0:
        return None, TDA_INFEASIBLE, 0.0

    f_d = [alpha * f_tau[i] + f_t[i] for i in range(3)]
    flags = TDA_ALPHA_CLAMPED if alpha < 1.0 - 1e-9 else TDA_OK
    return f_d, flags, alpha


if __name__ == "__main__":
    # 自测
    from wrist_model import wrist_eval, positive_null_direction

    out = wrist_eval(0.0, 0.0)
    n = positive_null_direction(0.0, 0.0)
    assert n is not None

    # 恒零力矩 + 预紧
    f, fl, a = tda_solve(out.r_m, n, 0.0, 0.0, 5.0, 0.5, 50.0)
    assert f is not None and fl == TDA_OK and a == 1.0, (f, fl, a)
    assert all(0.5 <= v <= 50.0 for v in f), f
    print(f"恒零+预紧5N: f=[{f[0]:.3f},{f[1]:.3f},{f[2]:.3f}] alpha={a:.2f}")

    # 小力矩
    f2, fl2, a2 = tda_solve(out.r_m, n, 0.05, -0.03, 5.0, 0.5, 50.0)
    assert f2 is not None and a2 == 1.0, (f2, fl2, a2)
    assert all(0.5 <= v <= 50.0 for v in f2), f2
    print(f"τ=(0.05,-0.03): f=[{f2[0]:.3f},{f2[1]:.3f},{f2[2]:.3f}] alpha={a2:.2f}")

    # 大力矩 → α 缩放
    f3, fl3, a3 = tda_solve(out.r_m, n, 5.0, 5.0, 5.0, 0.5, 50.0)
    assert f3 is not None and a3 < 1.0, (f3, fl3, a3)
    assert all(0.5 - 1e-6 <= v <= 50.0 + 1e-6 for v in f3), f3  # 数值容差
    print(f"τ=(5,5) 大力矩: f=[{f3[0]:.3f},{f3[1]:.3f},{f3[2]:.3f}] alpha={a3:.3f} (缩放)")

    # 预紧自身超界
    f4, fl4, a4 = tda_solve(out.r_m, n, 0.0, 0.0, 100.0, 0.5, 50.0)
    assert f4 is None and fl4 & TDA_INFEASIBLE, (f4, fl4, a4)
    print(f"预紧100N超50N上限: 不可行 ✓")

    # 无零空间
    out5 = wrist_eval(0.3, -0.2)
    n5 = positive_null_direction(0.3, -0.2)
    assert n5 is None
    f5, fl5, a5 = tda_solve(out5.r_m if out5.math_valid else [[0]*3]*2,
                            n5, 0.0, 0.0, 5.0, 0.5, 50.0)
    assert f5 is None and fl5 & TDA_NO_NULL, (f5, fl5, a5)
    print(f"偏位无零空间: 不可行 ✓")

    print("wrist_tda 自测全部通过")
