"""关节空间解耦力矩控制律（v2，唯一版本）—— 纯函数，无 UI/串口依赖。

v2 架构（论文式，在位置舵机上的可适配版）：
    被控量  (τ_roll, τ_pitch) = R(q)·f  [N·m]（动态 R 由 wrist_model 提供）
    执行量  trim_i（位置微调，叠加在力控基准上）
    律      u = K_p·(τ_d − τ_meas) + K_i·∫(τ_d − τ_meas)dt   （u、integ 钳 ±可达力矩）
            f_d = TDA(τ_d + u, t, f_min, f_max)          ← TDA 做饱和分配
            trim_i = s_i·(trim_gain·(f_d,i − f_meas,i) + ∫)   s_i = trim_sign ±1
    抗饱和  α<1（目标力矩不可达）时 integ_tau 本拍冻结——不可达域持续灌
            积分只会在解除饱和后猛冲；integ_tau 域为 N·m，钳 ±可达力矩
            （= 张力可用跨度 × 力臂绝对值和，由参数自行推得）
    饱和    TDA 内部做一维区间交集 + α 缩放（论文 §8.3）
    方向    trim_sign[i]：counts 增大时该缆张力 增=+1 / 减=−1（逐电机，
            台架点动判向后写入；错填 = 正反馈飞车，故无默认值可瞒）

历史注记：v1 对角张力 PI（每缆独立控 f_target）已删除（2026-11-02）——
它是论文 §6.2 批评的腱空间方案，且未暴露 trim→张力方向符号，留着即
误用隐患。对照实验需要时从 git 历史取。

安全语义（调用方必须实现）：
    (None, FORCE_STALE)    → 冻结：不更新 trim、不发新命令
    (None, FORCE_OVERLOAD) → 调用方必须立即停闭环
    负张力样本（松绳）→ 钳 0 继续控（松绳提示由张力守卫 TENSION_SLACK 负责）

对应 C 结构：
    typedef struct {
        float tau_d[2];       /* 期望关节力矩 N·m */
        float preload_n;      /* 预紧 N */
        float kp;             /* 力矩 P 增益（无量纲，u 与 τ 同为 N·m） */
        float ki;             /* 力矩 I 增益 1/s */
        float trim_gain;      /* 张力误差→位置微调增益 counts/N */
        int8_t trim_sign[3];  /* trim→张力方向 ±1：+1=counts增⇒张力增 */
        float max_trim;       /* trim/integ 统一限幅 counts */
        float f_max;          /* 硬过载 N */
        float f_min;          /* 松绳阈值 N */
        float deadband;       /* 力矩死区 N·m */
        float r_m[2][3];      /* 当前姿态力臂 m/rad */
        float null_dir[3];    /* 正零空间方向 */
    } wrist_force_v2_params_t;
    typedef struct { float integ_tau[2]; float trim_base[3]; } wrist_force_v2_state_t;
"""
from __future__ import annotations

import math

FORCE_OK = 0
FORCE_STALE = 1 << 0        # 样本过期/缺失：冻结
FORCE_OVERLOAD = 1 << 1     # 任一缆 f > f_max：调用方停闭环
FORCE_TDA_INFEASIBLE = 1 << 3  # TDA 不可行（无零空间/预紧超界）
FORCE_NO_NULL = 1 << 4      # 该位姿无全正零空间方向（张紧模式不可用）

STALE_MS = 300.0

# ---------- 张力环的"力单位"常数（2026-11-11 用户实测 / 定案） ----------
# 单位换换算链：k[counts/m] ÷ 1000 = counts/mm；1 count 的力变化 = K/counts_per_mm。
# 用户给的等效刚度（电机走 1mm 读 Δf）：K = 5.5 N/mm。
# 卷筒 r = 6/5.5/5.5 mm → k = 108650/118527/118527 counts/m（见 wrist_control_law）。
ROPE_STIFFNESS_N_PER_MM = 5.5
# 积分贡献的钳制（counts，2026-11-11 用户改为 counts 口径）：|K_i·∫e| ≤ 5 counts。
# 换算参考：1 count = 0.0464 N(C2/C3) / 0.0506 N(C1) → 5 counts ≈ 0.23 N 力当量；
# 它能顶偏的静差 = 5/Kp（Kp=15 时 0.33 N、Kp=10 时 0.5 N）。
TENSION_I_TERM_LIM_COUNTS = 5.0


def tension_counts_per_n(k_i: float) -> float:
    """该路 1 N 对应多少 counts（k_i 单位 counts/m）＝ k/(K·1000)。仅报数用。"""
    return abs(k_i) / (ROPE_STIFFNESS_N_PER_MM * 1000.0)


def tension_i_term_lim_counts(*_ignored) -> float:
    """积分贡献的钳制值（counts）——直接按 counts 给，不再经牛顿换算。

    保留 `*_ignored` 只为兼容旧调用点（曾传 k_list / kp）。
    """
    return TENSION_I_TERM_LIM_COUNTS


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def _sample_prelude(f_n, age_ms: float, dt: float, f_max: float):
    """三模式共用的样本前置检查。返回 (f_n|None, flags)：非 None 即通过，
    f_n 已钳负值；调用方拿到 None 按 flags 处置（STALE 冻结 / OVERLOAD 停）。"""
    if (not isinstance(f_n, (list, tuple)) or len(f_n) != 3
            or not all(_finite(v) for v in f_n)):
        return None, FORCE_STALE
    if any(v < 0.0 for v in f_n):
        f_n = [max(0.0, v) for v in f_n]      # 松绳：钳 0 继续控
    if not _finite(age_ms) or age_ms > STALE_MS:
        return None, FORCE_STALE
    if not _finite(dt) or dt <= 0.0:
        return None, FORCE_STALE
    if any(f > f_max for f in f_n):
        return None, FORCE_OVERLOAD
    return f_n, FORCE_OK


def _incr_step(e_i: float, integ_i: float, resid_i: float,
               kp: float, ki: float, dt: float,
               max_step: float, i_term_lim: float) -> tuple:
    """增量式 PI 基元（三力控模式统一执行器，2026-11-02 用户定案）。

        I    = clamp(∫e·dt, ±i_term_lim/ki)          # 状态本身钳住（2026-11-11）
        du   = sat_{±max_step}( kp·e + ki·I )
        step = round(resid + du)；resid -= step        # 小数残差进位
    返回 (新integ, 新resid, 本拍整数步长)。
    条件积分：未饱和（|raw|<max_step）或误差已反向（raw·e<0）才累加 ∫e。

    2026-11-11 变更：`i_term_lim` 改成"积分贡献"的硬上限（counts），
    **状态 ∫e 也被钳到 i_term_lim/ki**——否则钳制只卡住贡献、状态仍在涨，
    反向时要按状态的绝对值慢慢退，等于把"反向滞后"变成无界。
    P 直接作用在 e 上（非 Δe）：ki=0 时恒速 kp·e 逼近目标，进死区才停。"""
    i_term = max(-i_term_lim, min(i_term_lim, ki * integ_i))
    raw = kp * e_i + i_term
    du = max(-max_step, min(max_step, raw))
    if ki > 0.0 and (abs(raw) < max_step or raw * e_i < 0.0):
        integ_i += e_i * dt
        lim_state = i_term_lim / ki            # 状态与贡献同步封顶（防"假钳制"）
        integ_i = max(-lim_state, min(lim_state, integ_i))
    resid_i += du
    step = int(round(resid_i))
    resid_i -= step
    return integ_i, resid_i, step


# ============================================================
# 关节空间解耦力矩律（论文式，唯一版本）
# ============================================================

class WristForceV2Params:
    """v2 参数：关节空间力矩 PI + TDA 分配。

    trim_sign 无默认值：+1 = counts 增 ⇒ 该缆张力增；−1 = 反向。
    错符号 = 正反馈飞车，必须由台架点动判向后显式给定。
    """

    __slots__ = ("tau_d", "preload_n", "kp", "ki", "trim_gain", "trim_sign",
                 "max_trim", "max_step", "f_max", "f_min", "deadband",
                 "r_m", "null_dir")

    def __init__(self, tau_d, preload_n: float,
                 kp: float, ki: float, trim_gain: float, trim_sign,
                 max_trim: float, f_max: float, f_min: float,
                 deadband: float, r_m, null_dir, max_step: float = 5.0):
        if (not isinstance(tau_d, (list, tuple)) or len(tau_d) != 2
                or not all(_finite(v) for v in tau_d)):
            raise ValueError("tau_d 需为长度 2 的有限数组 [N·m]")
        for name, v in (("kp", kp), ("ki", ki), ("trim_gain", trim_gain)):
            if not _finite(v) or v < 0.0:
                raise ValueError(f"{name} 需为非负有限数")
        if (not isinstance(trim_sign, (list, tuple)) or len(trim_sign) != 3
                or any(v not in (-1, 1) for v in trim_sign)):
            raise ValueError("trim_sign 需为长度 3 的 ±1 数组"
                             "（+1=counts增⇒张力增，−1=反向）")
        if not _finite(max_trim) or max_trim <= 0.0:
            raise ValueError("max_trim 需为正数")
        if not _finite(f_max) or f_max <= 0.0:
            raise ValueError("f_max 需为正数")
        if not _finite(f_min) or f_min < 0.0:
            raise ValueError("f_min 需为非负有限数")
        if not _finite(deadband) or deadband < 0.0:
            raise ValueError("deadband 需为非负有限数")
        if not _finite(preload_n) or preload_n < 0.0:
            raise ValueError("preload_n 需为非负有限数")
        if f_min >= f_max:
            raise ValueError("需 f_min < f_max")
        if not _finite(max_step) or max_step <= 0.0:
            raise ValueError("max_step 需为正数")
        self.tau_d = [float(v) for v in tau_d]
        self.preload_n = float(preload_n)
        self.kp, self.ki, self.trim_gain = float(kp), float(ki), float(trim_gain)
        self.trim_sign = [float(v) for v in trim_sign]
        self.max_trim, self.max_step = float(max_trim), float(max_step)
        self.f_max, self.f_min = float(f_max), float(f_min)
        self.deadband = float(deadband)
        self.r_m = r_m       # 2×3 list，不拷贝（调用方保证一致性）
        self.null_dir = null_dir  # 3 tuple | None


class WristForceV2State:
    """v2 状态：2 轴力矩外环积分 + 3 缆内环增量积分/残差。"""
    __slots__ = ("integ_tau", "integ_f", "resid")

    def __init__(self) -> None:
        self.integ_tau = [0.0, 0.0]
        self.integ_f = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]

    def reset(self) -> None:
        self.integ_tau = [0.0, 0.0]
        self.integ_f = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]


def wrist_force_v2_step(p: WristForceV2Params,
                         state: WristForceV2State,
                         f_n, age_ms: float, dt: float,
                         tda_solver) -> tuple:
    """v2 关节空间解耦力矩律。

    Args:
        tda_solver: callable(r_m, null_dir, tau_r, tau_p, t, fmin, fmax)
                    → (f_d[3]|None, flags, alpha)  即 wrist_tda.tda_solve

    Returns:
        (trim[3] | None, flags, alpha)
        alpha：TDA 饱和缩放系数（1=全力矩；<1=目标不可达被打折——论文 §8.3
        优雅降级）；错误路径 alpha=NaN（曲线断口语义，与 t 同款）。
    """
    if (not isinstance(f_n, (list, tuple)) or len(f_n) != 3
            or not all(_finite(v) for v in f_n)):
        return None, FORCE_STALE, math.nan
    if any(v < 0.0 for v in f_n):
        f_n = [max(0.0, v) for v in f_n]      # 松绳：钳 0 继续控
    if not _finite(age_ms) or age_ms > STALE_MS:
        return None, FORCE_STALE, math.nan
    if not _finite(dt) or dt <= 0.0:
        return None, FORCE_STALE, math.nan
    if any(f > p.f_max for f in f_n):
        return None, FORCE_OVERLOAD, math.nan

    # 1) 观测 τ = R·f
    tau_meas_r = sum(p.r_m[0][i] * f_n[i] for i in range(3))
    tau_meas_p = sum(p.r_m[1][i] * f_n[i] for i in range(3))

    # 2) 力矩 PI → 校正量 u（N·m 域）。
    #    可达力矩上界 = 张力可用跨度 × 力臂绝对值和：超出它 TDA 也只能
    #    α 缩，u 钳在这里防积分在不可达域狂灌（windup）。
    span = p.f_max - p.f_min
    lim_r = span * sum(abs(p.r_m[0][i]) for i in range(3))
    lim_p = span * sum(abs(p.r_m[1][i]) for i in range(3))
    errs = [p.tau_d[0] - tau_meas_r, p.tau_d[1] - tau_meas_p]
    for j in range(2):
        if abs(errs[j]) <= p.deadband:
            errs[j] = 0.0
    u_r = max(-lim_r, min(lim_r, p.kp * errs[0] + state.integ_tau[0]))
    u_p = max(-lim_p, min(lim_p, p.kp * errs[1] + state.integ_tau[1]))

    # 3) TDA 分配（τ_d + u 校正后 → f_d 三缆目标张力）
    f_d, tda_flags, alpha = tda_solver(p.r_m, p.null_dir,
                                        p.tau_d[0] + u_r, p.tau_d[1] + u_p,
                                        p.preload_n, p.f_min, p.f_max)
    if f_d is None:
        return None, tda_flags | FORCE_TDA_INFEASIBLE, math.nan

    #    抗饱和：α<1 = 目标力矩不可达，本拍冻结积分（条件积分法）。
    #    否则误差持续存在会把 integ 灌满限幅，解除饱和后猛烈回冲。
    if alpha >= 1.0 - 1e-9:
        state.integ_tau[0] = max(-lim_r, min(lim_r,
                                state.integ_tau[0] + p.ki * errs[0] * dt))
        state.integ_tau[1] = max(-lim_p, min(lim_p,
                                state.integ_tau[1] + p.ki * errs[1] * dt))

    # 4) 张力误差 → 增量步长（内环执行，与张力/张紧模式同一增量基元）。
    #    trim_sign 在出口统一翻方向；内环 P=I=trim_gain（单旋钮，沿袭原设计）。
    #    外环保持力矩域位置式（其输出 u 是给 TDA 的代数校正量，不是位置指令，
    #    不经过"累加到实测位置"的执行接口——增量式的定义域在位置出口层）。
    trim = [0.0, 0.0, 0.0]
    for i in range(3):
        f_err = f_d[i] - f_n[i]
        state.integ_f[i], state.resid[i], step = _incr_step(
            f_err, state.integ_f[i], state.resid[i],
            p.trim_gain, p.trim_gain, dt, p.max_step, p.max_trim)
        trim[i] = p.trim_sign[i] * step
    return trim, FORCE_OK, alpha


# ============================================================
# 模式二：张力控制（每缆独立张力闭环；增量式 PI，无前馈）
# ============================================================

class WristTensionParams:
    """张力模式参数类：每缆张力目标 + 对角增量式 PI（无前馈） + 逐缆方向符号。

    trim_sign 语义同 v2：+1 = counts 增 ⇒ 该缆张力增；错填 = 正反馈飞车。
    max_step 是每拍最大位置增量 [counts]（相对增量输出，限制速度）。
    max_trim 是相对进入点允许的最大累计行程 [counts]（调用方做绝对夹紧）。
    i_term_lim 是积分贡献 `K_i·∫e` 的钳制 [counts]，按"1 N 对应多少 counts"折算
    （见 tension_i_term_lim_counts）；缺省 = max_trim（旧行为）。
    """

    __slots__ = ("f_target", "kp", "ki", "trim_sign",
                 "max_trim", "max_step", "f_max", "deadband", "i_term_lim")

    def __init__(self, f_target, kp: float, ki: float, trim_sign,
                 max_trim: float, f_max: float, deadband: float,
                 max_step: float = 5.0, i_term_lim: float = None):
        if (not isinstance(f_target, (list, tuple)) or len(f_target) != 3
                or not all(_finite(v) and v >= 0.0 for v in f_target)):
            raise ValueError("f_target 需为长度 3 的非负有限数组 [N]")
        for name, v in (("kp", kp), ("ki", ki)):
            if not _finite(v) or v < 0.0:
                raise ValueError(f"{name} 需为非负有限数")
        if (not isinstance(trim_sign, (list, tuple)) or len(trim_sign) != 3
                or any(v not in (-1, 1) for v in trim_sign)):
            raise ValueError("trim_sign 需为长度 3 的 ±1 数组")
        if not _finite(max_trim) or max_trim <= 0.0:
            raise ValueError("max_trim 需为正数")
        if not _finite(max_step) or max_step <= 0.0:
            raise ValueError("max_step 需为正数")
        if not _finite(f_max) or f_max <= 0.0:
            raise ValueError("f_max 需为正数")
        if not _finite(deadband) or deadband < 0.0:
            raise ValueError("deadband 需为非负有限数")
        if i_term_lim is not None and (not _finite(i_term_lim) or i_term_lim <= 0.0):
            raise ValueError("i_term_lim 需为正数")
        self.f_target = [float(v) for v in f_target]
        self.kp, self.ki = float(kp), float(ki)
        self.trim_sign = [float(v) for v in trim_sign]
        self.max_trim, self.f_max = float(max_trim), float(f_max)
        self.max_step = float(max_step)
        self.deadband = float(deadband)
        self.i_term_lim = float(i_term_lim) if i_term_lim is not None else float(max_trim)


class WristTensionState:
    """张力模式状态：误差积分（N·s）+ 步长小数残差（相对增量输出）。"""
    __slots__ = ("integ", "resid")

    def __init__(self) -> None:
        self.integ = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]

    def reset(self) -> None:
        self.integ = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]


def wrist_tension_step(p: WristTensionParams,
                       state: WristTensionState,
                       f_n, age_ms: float, dt: float) -> tuple:
    """张力控制一拍：每缆独立 PI，**输出本拍位置增量（相对模式）**。

        I    = ∫e·dt（条件积分，饱和时冻结）
        du   = Kp·e + Ki·I                           # 本拍要走多少 counts
        du   = clamp(du, ±max_step)                  # 每拍速度上限
        step = round(resid + du); resid -= step      # 小数残差进位
        trim = trim_sign · step

    调用方按 out = 实测当前位置 + trim 下发；max_trim 由调用方做
    “相对进入点的累计行程”夹紧。死区内 e 归零（不再走）。
    与标准增量式（Kp·Δe）不同：这里 P 直接作用在 e 上，所以 Ki=0 时
    只要 e≠0 也会每拍走一点，不会“只动一次”。
    对角结构=论文 §6 的腱空间方案（台架起步/直观操作用）。

    Returns:
        (trim[3] | None, flags)
    """
    f_n, flags = _sample_prelude(f_n, age_ms, dt, p.f_max)
    if f_n is None:
        return None, flags
    trim = [0.0, 0.0, 0.0]
    for i in range(3):
        e = p.f_target[i] - f_n[i]
        if abs(e) <= p.deadband:
            e = 0.0
        state.integ[i], state.resid[i], step = _incr_step(
            e, state.integ[i], state.resid[i],
            p.kp, p.ki, dt, p.max_step, p.i_term_lim)
        trim[i] = p.trim_sign[i] * step
    return trim, FORCE_OK


# ============================================================
# 模式三：张紧控制（零空间预紧单旋钮，力矩守恒）
# ============================================================

class WristTightParams:
    """张紧模式参数类：目标预紧 t（沿 +n̂ 的张力分量）+ 增量式 PI + 方向地板。

    数学：修正步长沿零空间分布 du_i ∝ e·n̂_i，由 R·n̂=0 保证 τ 守恒、
    Σdu_i·n̂_i 跟 e 保证预紧分量跟误差（整数步长四舍五入偏差 ≤0.5c/缆）。
    n̂ None → 不可用。输出本拍整数步长，调用方按 实测当前位置+步长 下发。

    f_min 方向地板（PLAN v8.2 D4 / v8.3 裁定）：f_i ≤ f_min 且 step<0 →
    本拍禁放（step<0=物理放绳，与 trim_sign 无关：Δcounts=sign×step，
    Δ张力=sign×Δcounts=sign(step)），并清 integ/resid 防积分/残差继续放。
    可证不变式（增益/路径无关）：f_i 终 ≥ min(f_i 起, f_min) − 一步粒度。
    起始低于地板的缆不会被地板抬起（那是 err>0 紧方向的事）；f_min=0 禁用。
    """

    __slots__ = ("t_target", "kp", "ki", "trim_sign",
                 "max_trim", "max_step", "f_max", "f_min", "deadband", "null_dir")

    def __init__(self, t_target: float, kp: float, ki: float, trim_sign,
                 max_trim: float, f_max: float, deadband: float, null_dir,
                 max_step: float = 5.0, f_min: float = 0.0):
        if not _finite(t_target) or t_target < 0.0:
            raise ValueError("t_target 需为非负有限数 [N]")
        for name, v in (("kp", kp), ("ki", ki)):
            if not _finite(v) or v < 0.0:
                raise ValueError("kp/ki 需为非负有限数")
        if (not isinstance(trim_sign, (list, tuple)) or len(trim_sign) != 3
                or any(v not in (-1, 1) for v in trim_sign)):
            raise ValueError("trim_sign 需为长度 3 的 ±1 数组")
        if not _finite(max_trim) or max_trim <= 0.0:
            raise ValueError("max_trim 需为正数")
        if not _finite(max_step) or max_step <= 0.0:
            raise ValueError("max_step 需为正数")
        if not _finite(f_max) or f_max <= 0.0:
            raise ValueError("f_max 需为正数")
        if not _finite(f_min) or f_min < 0.0 or f_min >= f_max:
            raise ValueError("f_min 需为 0（禁用）或 [0, f_max)")
        if not _finite(deadband) or deadband < 0.0:
            raise ValueError("deadband 需为非负有限数")
        if null_dir is not None and (not isinstance(null_dir, (list, tuple))
                                     or len(null_dir) != 3):
            raise ValueError("null_dir 需为长度 3 数组或 None")
        self.t_target = float(t_target)
        self.kp, self.ki = float(kp), float(ki)
        self.trim_sign = [float(v) for v in trim_sign]
        self.max_trim, self.max_step = float(max_trim), float(max_step)
        self.f_max = float(f_max)
        self.f_min = float(f_min)
        self.deadband = float(deadband)
        self.null_dir = null_dir


class WristTightState:
    """张紧模式状态：误差积分 + 步长小数残差（增量式）。"""
    __slots__ = ("integ", "resid")

    def __init__(self) -> None:
        self.integ = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]

    def reset(self) -> None:
        self.integ = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]


def wrist_tight_step(p: WristTightParams,
                     state: WristTightState,
                     f_n, age_ms: float, dt: float) -> tuple:
    """张紧模式一拍：t_meas=f·n̂ → 增量式 PI → 步长∝n̂ 分配（τ 守恒）。

    Returns:
        (trim|None, flags)；null_dir 缺失 → (None, FORCE_NO_NULL)
    """
    if p.null_dir is None:
        return None, FORCE_NO_NULL
    f_n, flags = _sample_prelude(f_n, age_ms, dt, p.f_max)
    if f_n is None:
        return None, flags
    n = p.null_dir
    t_meas = sum(f_n[i] * n[i] for i in range(3))
    err = p.t_target - t_meas
    if abs(err) <= p.deadband:
        err = 0.0
    trim = [0.0, 0.0, 0.0]
    for i in range(3):
        e_i = err * n[i]                    # 预紧误差沿零空间分到各缆
        state.integ[i], state.resid[i], step = _incr_step(
            e_i, state.integ[i], state.resid[i],
            p.kp, p.ki, dt, p.max_step, p.max_trim)
        if p.f_min > 0.0 and f_n[i] <= p.f_min and step < 0:
            # 方向地板（v8.3）：贴地禁放——step<0=物理放（Δ张力=sign(step)），
            # 与 trim_sign 无关；清三态防积分/残差继续泄。
            step = 0.0
            state.integ[i] = 0.0
            state.resid[i] = 0.0
        trim[i] = p.trim_sign[i] * step
    return trim, FORCE_OK
