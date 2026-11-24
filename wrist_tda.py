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


def preload_window(r_m, null_dir, tau_roll, tau_pitch, f_min, f_max):
    """给定目标力矩 τ，求预紧 `p` 的可行区间（**带 τ 项的通用式**）。

    数学：`f_i(τ, p) = c_i·τ + p·n̂_i`，其中 `c = P⁻¹·[e_axis]`。
    对每根缆解 `f_min ≤ f_i ≤ f_max`，得到 p 的上下界，取交集。

    与旧公式的关系：
        τ = 0 时退化为  `f_min/max(n̂) … f_max/min(n̂)`？ ——不，见下：
        τ = 0 时 `f_i = p·n̂_i`，所以是 `p ≥ f_min/max? ` 逐缆约束
        ⇒ `p_min = max_i (f_min/n̂_i) = f_min/min(n̂)`
        ⇒ `p_max = min_i (f_max/n̂_i) = f_max/max(n̂)`
        与代码旧实现 `fmin/min(n̂) … fmax/max(n̂)` **完全一致**。

    Args:
        r_m: 2×3 力臂矩阵（`wrist_eval().r_m`）
        null_dir: 3 元 n̂（`positive_null_direction` 的返回值），必须全正
        tau_roll, tau_pitch: 目标关节力矩 [N·m]
        f_min, f_max: 每缆张力上下限 [N]

    Returns:
        (p_min, p_max) | None
        None 表示该位姿/该力矩下**无解**（n̂ 缺失、P 奇异、或区间为空）。
    """
    if null_dir is None or len(null_dir) != 3:
        return None
    if any((not math.isfinite(v)) or v <= 0.0 for v in null_dir):
        return None
    P = [
        [r_m[0][0], r_m[0][1], r_m[0][2]],
        [r_m[1][0], r_m[1][1], r_m[1][2]],
        [null_dir[0], null_dir[1], null_dir[2]],
    ]
    P_inv = _inv3(P)
    if P_inv is None:
        return None
    # c = P⁻¹·[τ_r, τ_p, 0]（τ 的那一半；另一半 p·n̂ 单独算）
    c = _mat_vec(P_inv, [tau_roll, tau_pitch, 0.0])
    p_lo, p_hi = -math.inf, math.inf
    for i in range(3):
        n_i = null_dir[i]
        ci = c[i]
        if n_i > 1e-12:
            lo = (f_min - ci) / n_i
            hi = (f_max - ci) / n_i
        elif n_i < -1e-12:
            lo = (f_max - ci) / n_i
            hi = (f_min - ci) / n_i
        else:
            # n̂_i ≈ 0：该缆不受 p 影响，只能靠 τ 本身满足边界
            if not (f_min - 1e-9 <= ci <= f_max + 1e-9):
                return None
            continue
        p_lo = max(p_lo, lo)
        p_hi = min(p_hi, hi)
    if (not math.isfinite(p_lo)) or (not math.isfinite(p_hi)) or p_lo > p_hi:
        return None
    return p_lo, p_hi


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


# ---------------------------------------------------------------- 力矩优先分配
# 2026-11-22：`tda_solve` 是"固定预紧 t → 做不到就把力矩缩 alpha"。
# 用户要的是反过来：**力矩是任务、预紧是手段**。所以加这个函数。
TDA_PRELOAD_RAISED = 1 << 4        # 预紧被抬到 s_lo 以上（满足力矩所需）
TDA_PRELOAD_INFEASIBLE = 1 << 5    # 用户预紧下限超过 s_hi（预紧本身不可行）


# ---------------------------------------------------------------- 闭式能力
# 2026-11-23：3 缆 2 轴的能力集是**沿方向凸集**，不是"每轴独立矩形"。
# 旧实现按轴各自二分再各砍各的 → 双轴组合会被高估 → 砍完仍不可行 → 误判停环
# （实测 (τ_r,τ_p)=(0.1,-2.0)：pitch 单轴能力 1.443，但叠加 0.1 roll 后
#  真实能力只有 1.380，按轴砍到 1.429 仍然无解）。
# 现在改成"沿目标方向求最大缩放系数"——这正是论文的 α，且可闭式求出。
#
# 推导（详见 docs/张力能力闭式推导_20261122.md）：
#   f(m,t) = m·u + t·n̂,  m = 交付力矩幅值,  u = P⁻¹[d;0]（d 为单位方向）
#   每缆界约束换算成 t 的区间：L_i(m) ≤ t ≤ U_i(m)
#       L_i = (f_min − m·u_i)/n̂_i = a_i − m·b_i
#       U_i = (f_max − m·u_i)/n̂_i = c_i − m·b_i
#   其中 a_i = f_min/n̂_i,  b_i = u_i/n̂_i,  c_i = f_max/n̂_i
#   存在 t ⟺ max(t_floor, max_i L_i) ≤ min_j U_j
#   ⟹ L_i ≤ U_j（对所有 i,j，给出 m 的上界）与 t_floor ≤ U_j
#   ⟹ m_max = min{ min_{b_j>b_i}(c_j−a_i)/(b_j−b_i), min_{b_j>0}(c_j−t_floor)/b_j }
#   （b_j<b_i 的那些对给的是 m 的**下界**，对 m≥0 自动满足，跳过）
# 与论文算法 2（迭代解 2×2）逐位等价（9 工况 + 10 方向验证，差 0.000000），
# 但没有迭代、没有 2×2 奇异风险，并且附带给出"该方向的绝对能力"。


def capacity_closed_form(r_m, null_dir, tau_roll, tau_pitch,
                         t_floor, f_min, f_max):
    """沿 (tau_roll, tau_pitch) 方向的 |τ| 上界 [N·m]（闭式，O(m²)）。

    Args:
        r_m: 2×3 力臂矩阵
        null_dir: 3 元正零空间方向（全正）
        tau_roll, tau_pitch: 目标力矩（决定方向；幅值不参与，只取方向）
        t_floor: 预紧**下限** [N]（≤0 表示不设）
        f_min, f_max: 每缆张力界 [N]

    Returns:
        · `None`：几何无效（无零空间 / P 奇异）
        · `0.0` ：连零力矩都不可行（预紧下限太高，或 f_min/f_max 自相矛盾）
        · `>0`  ：该方向可交付的力矩幅值上限 [N·m]
    """
    if null_dir is None:
        return None
    if not all(math.isfinite(n) and n > 0.0 for n in null_dir):
        return None
    P = [
        [r_m[0][0], r_m[0][1], r_m[0][2]],
        [r_m[1][0], r_m[1][1], r_m[1][2]],
        [null_dir[0], null_dir[1], null_dir[2]],
    ]
    P_inv = _inv3(P)
    if P_inv is None:
        return None

    floor = float(t_floor) if math.isfinite(t_floor) else 0.0
    floor = max(0.0, floor)
    a = [f_min / null_dir[i] for i in range(3)]
    c = [f_max / null_dir[i] for i in range(3)]
    # m=0 可行性：t·n̂ 必须能落进盒子
    if max(floor, max(a)) > min(c):
        return 0.0

    k = math.hypot(tau_roll, tau_pitch)
    if k < 1e-12:
        return float("inf")          # 方向无定义：零力矩总能做
    d = [tau_roll / k, tau_pitch / k]
    u = _mat_vec(P_inv, [d[0], d[1], 0.0])
    b = [u[i] / null_dir[i] for i in range(3)]

    m_max = float("inf")
    for i in range(3):
        for j in range(3):
            den = b[j] - b[i]
            if den > 1e-12:
                m_max = min(m_max, (c[j] - a[i]) / den)
    for i in range(3):
        if b[i] > 1e-12:
            m_max = min(m_max, (c[i] - floor) / b[i])
    return max(0.0, m_max)


def allocation_step(r_m, null_dir, tau_roll, tau_pitch,
                    t_floor, f_min, f_max, alpha_cap=1.0):
    """**完整分配**：α 内生（闭式能力）+ t 反解（下限）→ (f_d, flags, alpha, info)。

    与 `allocate_torque_priority` 的区别：
        · `allocate_torque_priority`：α ≡ 1，做不到就返回 None（对方自己钳 τ）
        · 本函数：做不到时**沿方向**把力矩缩到能力上限（α < 1），永远给出可行解
          —— 与论文算法 2 等价（论文迭代解 2×2，本函数闭式解，结果逐位相同）

    Args:
        alpha_cap: α 的上限（安全系数）。1.0 = 对齐论文；0.9 = 只给 90% 能力。

    Returns:
        (f_d[3] | None, flags, alpha, info)
        · `info` = dict(k, m_max, m, t, s_lo, alpha, cap_limited)
          —— 供状态行/诊断显示；`None` 时为空 dict
        · `alpha`：力矩实现比例（1=全额；<1=打 α 折）；错误路径 NaN
        · `R·f_d == alpha·τ*`（恒等式，可自检）
    """
    info = {}
    if null_dir is None:
        return None, TDA_NO_NULL, math.nan, info
    if not all(math.isfinite(n) and n > 0.0 for n in null_dir):
        return None, TDA_NO_NULL, math.nan, info
    P = [
        [r_m[0][0], r_m[0][1], r_m[0][2]],
        [r_m[1][0], r_m[1][1], r_m[1][2]],
        [null_dir[0], null_dir[1], null_dir[2]],
    ]
    P_inv = _inv3(P)
    if P_inv is None:
        return None, TDA_SINGULAR, math.nan, info

    floor = float(t_floor) if math.isfinite(t_floor) else 0.0
    floor = max(0.0, floor)
    cap = float(alpha_cap) if math.isfinite(alpha_cap) else 1.0
    cap = min(1.0, max(0.0, cap))
    a = [f_min / null_dir[i] for i in range(3)]
    c = [f_max / null_dir[i] for i in range(3)]

    # ---- 零力矩：只需预紧（t 取"刚好不松"与下限的较大者）
    k = math.hypot(tau_roll, tau_pitch)
    if k < 1e-12:
        s_lo0 = max(a)
        s_hi0 = min(c)
        if max(floor, s_lo0) > s_hi0:
            return None, TDA_PRELOAD_INFEASIBLE, math.nan, info
        t = max(floor, s_lo0)
        f_d = [t * null_dir[i] for i in range(3)]
        raised = floor < s_lo0 - 1e-12
        info.update(k=0.0, m_max=float("inf"), m=0.0, t=t,
                    s_lo=s_lo0, alpha=1.0, cap_limited=False)
        return f_d, (TDA_PRELOAD_RAISED if raised else TDA_OK), 1.0, info

    # ---- m=0 可行性（预紧下限太高 / 界自相矛盾）
    if max(floor, max(a)) > min(c):
        return None, TDA_PRELOAD_INFEASIBLE, math.nan, info

    # ---- 闭式能力（与 capacity_closed_form 同一段逻辑，内联避免重复求逆）
    d = [tau_roll / k, tau_pitch / k]
    u = _mat_vec(P_inv, [d[0], d[1], 0.0])
    b = [u[i] / null_dir[i] for i in range(3)]
    m_max = float("inf")
    for i in range(3):
        for j in range(3):
            den = b[j] - b[i]
            if den > 1e-12:
                m_max = min(m_max, (c[j] - a[i]) / den)
    for i in range(3):
        if b[i] > 1e-12:
            m_max = min(m_max, (c[i] - floor) / b[i])
    m_max = max(0.0, m_max)
    if m_max <= 0.0:
        return None, TDA_PRELOAD_INFEASIBLE, math.nan, info

    # ---- α：沿方向缩到能力内（再受安全系数约束）
    alpha = min(cap, m_max / k) if math.isfinite(m_max) else cap
    alpha = min(1.0, max(0.0, alpha))
    cap_limited = alpha < min(1.0, m_max / k) - 1e-12 if math.isfinite(m_max) else False
    m = alpha * k

    # ---- t 反解：满足力矩所需的最小预紧，且不低于下限
    f_tau = [m * u[i] for i in range(3)]
    s_lo = max((f_min - f_tau[i]) / null_dir[i] for i in range(3))
    s_hi = min((f_max - f_tau[i]) / null_dir[i] for i in range(3))
    if not (math.isfinite(s_lo) and math.isfinite(s_hi)):
        return None, TDA_INFEASIBLE, math.nan, info
    t = max(s_lo, floor)
    if t > s_hi:
        # 数值贴边（m 恰好等于能力）：夹进区间，避免一根缆破界 1e-15
        t = max(s_lo, s_hi)
    if s_lo > s_hi + 1e-9:
        return None, TDA_INFEASIBLE, math.nan, info

    f_d = [f_tau[i] + t * null_dir[i] for i in range(3)]
    raised = (t > floor + 1e-12) and (floor < s_lo - 1e-12)
    flags = TDA_PRELOAD_RAISED if raised else TDA_OK
    info.update(k=k, m_max=m_max, m=m, t=t, s_lo=s_lo, alpha=alpha,
                cap_limited=cap_limited)
    return f_d, flags, alpha, info


def allocate_torque_priority(r_m, null_dir, tau_roll, tau_pitch,
                             t_floor, f_min, f_max):
    """力矩优先分配：**力矩精确实现，不降额**（α ≡ 1）。

    保留此函数是因为它的契约很硬：**要么全额，要么 None**（调用方自己决定
    钳制/拒绝）。内部委托给 `allocation_step`，把 alpha<1 翻译成 None。

    Args:
        r_m: 2×3 力臂矩阵（`wrist_eval(...).r_m`）
        null_dir: 3 元正零空间方向（全正；`positive_null_direction`）
        tau_roll, tau_pitch: 期望关节力矩 [N·m]
        t_floor: 预紧**下限** [N]（用户填的 preload；≤0 表示只保证力封闭）
        f_min, f_max: 每缆张力上下限 [N]

    Returns:
        (f_d[3] | None, flags, alpha)
        · f_d 非 None 时 `alpha ≡ 1.0`（力矩全额实现）
        · flags: TDA_OK / TDA_PRELOAD_RAISED / TDA_NO_NULL / TDA_SINGULAR
                 / TDA_INFEASIBLE（力矩超能力）/ TDA_PRELOAD_INFEASIBLE（预紧下限太大）
        · None = 做不到（**不是降额**；调用方应钳制 τ 或拒绝启动）
        · 错误路径 alpha = NaN（曲线断口语义，与 `tda_solve` 一致）
    """
    f_d, flags, alpha, _info = allocation_step(
        r_m, null_dir, tau_roll, tau_pitch, t_floor, f_min, f_max,
        alpha_cap=1.0)
    if f_d is None:
        return None, flags, math.nan
    if alpha < 1.0 - 1e-9:
        # 旧契约：α≠1 → 视为"该力矩做不到"
        return None, flags | TDA_INFEASIBLE, math.nan
    return f_d, flags, 1.0


def torque_capacity(r_m, null_dir, t_floor, f_min, f_max,
                    axis=1, sign=1.0, tol=1e-6, hi=50.0):
    """当前位姿/预紧下可实现的 |τ| 上限 [N·m]（沿 `axis`：0=roll, 1=pitch）。

    ⚠ **方向不对称**：`R` 的力臂对不同转向不同，实测 (0,0) 位姿 pitch 正向
    0.50 vs 负向 1.44 N·m。所以必须传 `sign`（+1/-1，取目标力矩的符号）。

    二分找 `s_lo(τ) = s_hi(τ)` 的根；不可行返回 0.0。
    用于"超能力拒绝/钳制"与状态行显示。
    """
    if null_dir is None or not all(math.isfinite(n) and n > 0.0 for n in null_dir):
        return 0.0
    sg = 1.0 if sign >= 0.0 else -1.0

    def feasible(tau):
        tr, tp = (sg * tau, 0.0) if axis == 0 else (0.0, sg * tau)
        f, _fl, _a = allocate_torque_priority(r_m, null_dir, tr, tp,
                                              t_floor, f_min, f_max)
        return f is not None

    if not feasible(tol):
        return 0.0
    lo, up = tol, float(hi)
    if feasible(up):
        return up
    for _ in range(40):
        mid = 0.5 * (lo + up)
        if feasible(mid):
            lo = mid
        else:
            up = mid
    return lo


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
