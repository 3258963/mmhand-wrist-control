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
FORCE_SENSOR_FAULT = 1 << 4    # 张力读数物理不可能（< −F_SENSOR_MIN_N）：停闭环

# 2026-11-23：负张力超过这个量级就不是"零漂/松绳"，而是**传感器或通道坏了**
# （现场实测 C2 报 −396.65 N 并长期冻结）。以前的做法是 `max(0, f)` 钳 0 继续控，
# 于是误差恒为正 → 每拍满步收绳，永不收敛，也没有任何保护。
F_SENSOR_MIN_N = -2.0
FORCE_NO_NULL = 1 << 4      # 该位姿无全正零空间方向（张紧模式不可用）

STALE_MS = 300.0

# ---------- 张力环的"力单位"常数（2026-11-11 用户实测 / 定案） ----------
# 单位换换算链：k[counts/m] ÷ 1000 = counts/mm；1 count 的力变化 = K/counts_per_mm。
# 用户给的等效刚度（电机走 1mm 读 Δf）：K = 5.5 N/mm。
# 卷筒 r = 6/5.5/5.5 mm → k = 108650/118527/118527 counts/m（见 wrist_control_law）。
ROPE_STIFFNESS_N_PER_MM = 5.5
# 积分贡献的钳制（counts）。
# 2026-11-14：用户要求**先关闭**——绳子有"松绳/紧绳"两种状态，同一个 count 在两种状态下
# 含义不同，counts 口径的钳制先不启用；后面按需要再打开（改 ENABLED 即可）。
# 关闭时调用方退回 `max_trim`（≈不限），此时积分仍被**条件积分**兜底：
# `|kp·e + ki·I| ≥ max_step` 就不再累加 ⇒ 实际仍封顶在 ~max_step（20 counts ≈0.93 N）。
TENSION_I_TERM_LIM_ENABLED = True
# 5 counts ≈ 0.23 N 的"偏置能力"：够压住摩擦/迟滞的稳态差，又不至于
# 在误差≈0 时把输出顶满（40 就顶满了：raw=15·0.02+40 > max_step=20）。
# 同一数值**同时**是两道闸：贡献上限 5 counts、状态上限 5/ki = 0.25 N·s。
# 现场若发现稳态总差一点，再往 10 抬（10 → 0.46 N 偏置）。
TENSION_I_TERM_LIM_COUNTS = 5.0


def tension_i_term_lim_counts(*_ignored) -> float:
    """积分贡献的钳制值（counts）。

    `ENABLED=False` 时返回 0 → 调用方退回 `max_trim`（等于不钳，靠条件积分兜底）。
    保留 `*_ignored` 只为兼容旧调用点（曾传 k_list / kp）。
    """
    return TENSION_I_TERM_LIM_COUNTS if TENSION_I_TERM_LIM_ENABLED else 0.0


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


def _check_common(kp, ki, trim_sign, max_trim, max_step, f_max, deadband,
                  i_term_lim):
    """三个 params 类共用的字段校验 + 归一化（2026-11-19 抽出，原来三份逐字重复）。

    返回归一化后的
    `(kp, ki, trim_sign, max_trim, max_step, f_max, deadband, i_term_lim)`；
    `i_term_lim=None` 时回退到 `max_trim`（= 不钳制）。
    各 params 类各自特有的字段（f_target / t_target / f_min / null_dir / tau_d…）
    仍由各自的 `__init__` 检查。
    """
    for name, v in (("kp", kp), ("ki", ki)):
        if not _finite(v) or v < 0.0:
            raise ValueError(f"{name} 需为非负有限数")
    if (not isinstance(trim_sign, (list, tuple)) or len(trim_sign) != 3
            or any(v not in (-1, 1) for v in trim_sign)):
        raise ValueError("trim_sign 需为长度 3 的 ±1 数组")
    for name, v in (("max_trim", max_trim), ("max_step", max_step),
                    ("f_max", f_max)):
        if not _finite(v) or v <= 0.0:
            raise ValueError(f"{name} 需为正数")
    if not _finite(deadband) or deadband < 0.0:
        raise ValueError("deadband 需为非负有限数")
    if i_term_lim is not None and (not _finite(i_term_lim) or i_term_lim < 0.0):
        # 2026-11-20：允许 0 —— 语义是"关闭积分"（纯 P），界面「积分上限」填 0 即此意。
        raise ValueError("i_term_lim 需为非负有限数")
    return (float(kp), float(ki), [float(v) for v in trim_sign],
            float(max_trim), float(max_step), float(f_max), float(deadband),
            float(i_term_lim) if i_term_lim is not None else float(max_trim))


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
    P 直接作用在 e 上（非 Δe）：ki=0 时恒速 kp·e 逼近目标，进死区才停。

    2026-11-20：**两道上限都改成"每拍都夹"**（原来只在本拍要积分时才夹状态，
    历史残留的 state 能一直撑着贡献上限）。两道都必要：
      · `integ` 状态上限 = i_term_lim/ki（N·s）——防"状态越攒越多、反向退不完"
      · `ki·∫e` 贡献上限 = i_term_lim（counts）——防"积分一家把输出顶满"

    2026-11-20 二次变更（用户定案）：**取消条件积分闸门，允许一直累积**。
    原来 `|raw| < max_step` 才积分，导致两个副作用：
      · 闸门窗口 = max_step/kp，**改 max_step 会顺手改积分窗口**（max_step 340 时窗口 34 N，
        等于全程积分；max_step 20 时窗口 1.3 N，松绳期恒不积分）；
      · 松绳→接触的末段是否积分，取决于限幅值，行为不可预期。
    现在一律累积、只用**一个可调上限**（i_term_lim）封顶：
      · 填 0 ⟹ lim_state=0 ⟹ 状态恒 0 ⟹ 纯 P
      · 饱和期积分会顶在上限（有界 windup），这是用户要的"只给一个累积上限"。
    """
    lim_state = (i_term_lim / ki) if ki > 0.0 else 0.0
    if ki > 0.0:                               # 状态上限：每拍都夹，不看是否积分
        integ_i = max(-lim_state, min(lim_state, integ_i))
    i_term = max(-i_term_lim, min(i_term_lim, ki * integ_i))   # 贡献上限
    raw = kp * e_i + i_term
    du = max(-max_step, min(max_step, raw))
    if ki > 0.0:                               # 无条件累积（含饱和期），只受上限约束
        integ_i += e_i * dt
        integ_i = max(-lim_state, min(lim_state, integ_i))
    resid_i += du
    step = int(round(resid_i))
    resid_i -= step
    return integ_i, resid_i, step


def parse_per_cable(text, default, lo: float = 0.0, hi: float = 1e9,
                    name: str = "参数"):
    """把「1 个数」或「3 个数（逗号分隔）」解析成**逐缆**列表（2026-11-24）。

    为什么需要：三根缆的摩擦/绳长/预紧不同，一套 `kp/ki` 不可能同时最优
    （现场：C2 一直上不去、C1 却在摆）。这里给"可填 1 个或 3 个"的轻量方案，
    不改界面布局：

        "15"        → [15, 15, 15]     （一缆通吃，保持旧行为）
        "15,15,8"   → [15, 15, 8]      （C1/C2 用 15，C3 用 8）

    非法（个数不是 1/3、非数字、超界）→ 返回 `None`，调用方据此拒绝启动
    （宁可不跑，也不要拿错参数去驱动电机）。

    Args:
        text: 输入框文本；`None`/空串 → 用 `default`
        default: 缺省值（标量或 3 元组）
        lo/hi: 每项允许范围（含端点）
        name: 出错信息里用的参数名

    Returns:
        list[3] | None
    """
    raw = "" if text is None else str(text).strip()
    if not raw:
        if isinstance(default, (int, float)):
            base = [float(default)] * 3
        else:
            try:
                base = [float(v) for v in default]
            except (TypeError, ValueError):
                return None
            if len(base) != 3:
                return None
        return base if all(_finite(v) and lo <= v <= hi for v in base) else None
    parts = [p.strip() for p in raw.replace("，", ",").replace(";", ",").split(",")]
    parts = [p for p in parts if p != ""]
    try:
        vals = [float(p) for p in parts]
    except (TypeError, ValueError):
        return None
    if len(vals) == 1:
        vals = vals * 3
    if len(vals) != 3:
        return None
    if not all(_finite(v) and lo <= v <= hi for v in vals):
        return None
    return vals


def _per_cable(per, scalar, i: int, lo: float = 0.0):
    """逐缆取值：给了 `per`（3 元组）就用它，否则退回标量。内部小工具。"""
    if per is None:
        return scalar
    try:
        return float(per[i])
    except (TypeError, IndexError, ValueError):
        return scalar


def sine_target_step(base, amp: float, hz: float, phase_rad: float,
                     t: float, signs, lo: float, hi: float) -> list:
    """**正弦跟随测试**的目标生成（2026-11-24 用户要求，测张力内环动态响应）。

        f_target_i = clamp(base_i + sign_i · A · sin(2π f t + φ), lo, hi)

    设计要点：
    · `t` 由调用方从"勾上测试那一刻"起算 → `sin(0+φ)`，`φ=0` 时起点严格等于基值，
      **不会有阶跃**（阶跃会把内环的非线性/饱和混进辨识结果里）。
    · 结果夹在 `[lo, hi]`：幅度填太大会**削顶**而不是撞界停环（过载闸门要留给真故障）。
    · `base` 允许 3 元组；`signs` 同一长度，元素取符号（±1）。

    Args:
        base: 基值 [N]（长度 n）
        amp: 幅度 [N]（≥0）
        hz: 频率 [Hz]
        phase_rad: 初相 [rad]
        t: 从测试开始算起的时间 [s]
        signs: 每缆符号（±1），如 `(1,-1,-1)` 为差动
        lo/hi: 夹紧区间 [N]（`lo>hi` 时退化为 `lo`）

    Returns:
        list[float]，长度同 `base`；非法输入返回 `[]`。
    """
    if not all(_finite(v) for v in (amp, hz, phase_rad, t, lo, hi)):
        return []
    try:
        n = len(base)
        sg = [float(v) for v in signs]
    except (TypeError, ValueError):
        return []
    if n == 0 or len(sg) != n:
        return []
    s = math.sin(2.0 * math.pi * max(0.0, hz) * t + phase_rad)
    a = abs(amp)
    out = []
    for i in range(n):
        if not _finite(base[i]):
            return []
        v = float(base[i]) + (1.0 if sg[i] >= 0 else -1.0) * a * s
        v = max(lo, min(max(lo, hi), v))
        out.append(v)
    return out


def tau_trim_step(e_tau: float, integ: float, ki: float, dt: float,
                  cap: float, deadband: float = 0.005,
                  leak: float = 0.1, freeze: bool = False) -> tuple:
    """**力矩修正（漏积分外环）**一步（2026-11-24 新增）。

    为什么需要：力控的 τ 是**纯前馈**（`τ* → f_d → 追 f`），没有"τ 误差 → 修正"
    的环节。一旦内环到不了 `f_d`（积分权限不足、`max_trim` 打满、摩擦迟滞），
    实测力矩会长期低于 `τ*`，而没有任何东西去补。

    为什么**只能积分、且要漏 + 死区 + 冻结**：
        `τ_meas = R·f` 与 `τ*` 只差一个"f 追上 f_d 没有"，所以 τ 误差的响应
        **就是内环的响应**（本机内环极点 0.70，10~30 ms）。外环若带 P
        （旧实现 `Kp_τ=20`），等于给同一个快通道再套一环 → 2026-11-18 就是
        这样振的（`Kp=20,Ki=10` → 51% 的拍 α<1、摆动 0.075 N·m）。
        · `leak`：漏积分。误差消失后修正量会自己衰减（时间常数 1/leak），
          不会留一个永久偏置把张力长期顶高。
        · `deadband`：`|e|` 小于它就不积分（测量噪声不该被积）。
        · `freeze`：调用方在"能力受限（α<1）"时置 True —— 那时差距是物理上限，
          再积分只会把目标推到更不可行。

    局限（必须知道）：`τ_meas` 是**用模型 R 算出来的**，传感器在电机侧。
    若"传感器侧张力"到 `f_d` 了、而"关节侧张力"因导管摩擦差一截，
    这个外环**看不见**那部分误差。

    Args:
        e_tau: `τ* − τ_meas` [N·m]
        integ: 当前积分值 [N·m]（就是"加在 τ* 上的修正量"）
        ki: 积分增益 [1/s]；`0` = 关闭
        dt: 拍周期 [s]
        cap: 修正量上限 [N·m]（正负对称；`0` = 不限）
        deadband: 误差死区 [N·m]
        leak: 漏积分速率 [1/s]
        freeze: True = 本拍不积分（只保留/衰减）

    Returns:
        (new_integ, trim)
    """
    if not (_finite(e_tau) and _finite(integ) and _finite(ki)
            and _finite(dt) and _finite(cap)) or dt <= 0.0:
        return integ, integ
    if ki <= 0.0:
        return 0.0, 0.0
    v = integ
    if leak > 0.0:
        v *= max(0.0, 1.0 - leak * dt)       # **总是漏**：偏置不会永久留在命令里
    if not freeze and abs(e_tau) > max(0.0, deadband):
        v += ki * e_tau * dt                 # 死区外才积分（噪声不积）
    if cap > 0.0:
        v = max(-cap, min(cap, v))
    return v, v


# ============================================================
# 关节空间解耦力矩律（论文式，唯一版本）
# ============================================================

class WristForceV2Params:
    """v2 参数：**τ 目标（开环）** + TDA 分配 + 逐缆张力 PI。

    ⚠ 2026-11-24 澄清：`kp/ki` 是**历史字段**（曾经的"力矩 PI 外环"），
    现在 law 里**不再读取**它们（力矩没有闭环）。真正在用的闭环增益是
    `kp_inner/ki_inner`（张力误差 → counts/帧）。

    trim_sign 无默认值：+1 = counts 增 ⇒ 该缆张力增；−1 = 反向。
    错符号 = 正反馈飞车，必须由台架点动判向后显式给定。
    """

    __slots__ = ("tau_d", "preload_n", "kp", "ki",
                 "kp_inner", "ki_inner", "trim_sign",
                 "max_trim", "max_step", "f_max", "f_min", "deadband",
                 "r_m", "null_dir", "i_term_lim",
                 "kp3", "ki3", "max_step3", "i_term_lim3")

    def __init__(self, tau_d, preload_n: float,
                 kp: float, ki: float, trim_sign,
                 max_trim: float, f_max: float, f_min: float,
                 deadband: float, r_m, null_dir, max_step: float = 5.0,
                 kp_inner: float = None, ki_inner: float = None,
                 i_term_lim: float = None, *, kp3=None, ki3=None,
                 max_step3=None, i_term_lim3=None):
        if (not isinstance(tau_d, (list, tuple)) or len(tau_d) != 2
                or not all(_finite(v) for v in tau_d)):
            raise ValueError("tau_d 需为长度 2 的有限数组 [N·m]")
        # 内环增益：P/I 分离（2026-11-17）。旧的 `trim_gain`（P=I 单旋钮，
        # S·50=2.32 越界）已于 2026-11-19 删除，现在必须显式给 kp_inner/ki_inner。
        if kp_inner is None or ki_inner is None:
            raise ValueError("内环增益：kp_inner/ki_inner 必须同时给出")
        for name, v in (("kp_inner", kp_inner), ("ki_inner", ki_inner)):
            if not _finite(v) or v < 0.0:
                raise ValueError(f"{name} 需为非负有限数")
        # 未显式给 i_term_lim → 用全局钳制常量；常量关闭时退回 max_trim（旧行为）
        if i_term_lim is None:
            i_term_lim = tension_i_term_lim_counts() or float(max_trim)
        # 公共字段（trim_sign/max_trim/max_step/f_max/deadband/i_term_lim/kp/ki）
        (kp, ki, trim_sign, max_trim, max_step, f_max, deadband,
         i_term_lim) = _check_common(kp, ki, trim_sign, max_trim, max_step,
                                     f_max, deadband, i_term_lim)
        if not _finite(f_min) or f_min < 0.0:
            raise ValueError("f_min 需为非负有限数")
        if not _finite(preload_n) or preload_n < 0.0:
            raise ValueError("preload_n 需为非负有限数")
        if f_min >= f_max:
            raise ValueError("需 f_min < f_max")
        self.tau_d = [float(v) for v in tau_d]
        self.preload_n = float(preload_n)
        self.kp, self.ki = kp, ki
        self.kp_inner, self.ki_inner = float(kp_inner), float(ki_inner)
        self.trim_sign = trim_sign
        self.max_trim, self.max_step = max_trim, max_step
        self.f_max, self.f_min = f_max, float(f_min)
        self.deadband = deadband
        self.r_m = r_m       # 2×3 list，不拷贝（调用方保证一致性）
        self.null_dir = null_dir  # 3 tuple | None
        # 积分钳制（2026-11-20 补齐）：原来这里传的是 max_trim（＝不限），
        # 三个模式里只有力矩模式漏接，导致它的积分仍会无限累积。
        # 2026-11-20 二次修：上一版把 `None` 传给 `_check_common`，返回值把
        # 调用方给的 5.0 覆盖成 max_trim(5000)，等于钳制又没生效；现在
        # `_check_common` 直接吃解析好的 i_term_lim，这里只做赋值。
        self.i_term_lim = float(i_term_lim)
        # 逐缆覆盖（2026-11-24）：与张力模式同一套"可填 1 个或 3 个"。
        for nm, v in (("kp3", kp3), ("ki3", ki3),
                      ("max_step3", max_step3), ("i_term_lim3", i_term_lim3)):
            if v is None:
                setattr(self, nm, None)
                continue
            if (not isinstance(v, (list, tuple)) or len(v) != 3
                    or not all(_finite(x) and x >= 0.0 for x in v)):
                raise ValueError(f"{nm} 需为长度 3 的非负有限数组")
            setattr(self, nm, [float(x) for x in v])


class IncrPiState:
    """增量式 PI 状态：3 缆误差积分 + 步长小数残差（三个力控模式共用）。

    2026-11-19 合并：原先 `WristTensionState` / `WristForceV2State` 是两份
    结构相同的类（字段名一个叫 integ、一个叫 integ_f），现已统一为一份；
    旧名保留为别名，现有调用点/测试不需要改。
    """
    __slots__ = ("integ", "resid")

    def __init__(self) -> None:
        self.integ = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]

    def reset(self) -> None:
        self.integ = [0.0, 0.0, 0.0]
        self.resid = [0.0, 0.0, 0.0]


# 兼容别名（scope 与测试按这些名字导入）
WristTensionState = IncrPiState
WristForceV2State = IncrPiState


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
    # 2026-11-23：负到物理不可能 ⟹ 传感器/通道故障（不是松绳）。必须停环：
    # 钳 0 继续控会让误差恒为正 → 无限收绳（现场已复现，C3 被单独收到 30N+）。
    if any(v < F_SENSOR_MIN_N for v in f_n):
        return None, FORCE_SENSOR_FAULT, math.nan
    if any(v < 0.0 for v in f_n):
        f_n = [max(0.0, v) for v in f_n]      # 小负值（零点漂移/松绳）钳 0 继续控
    if not _finite(age_ms) or age_ms > STALE_MS:
        return None, FORCE_STALE, math.nan
    if not _finite(dt) or dt <= 0.0:
        return None, FORCE_STALE, math.nan
    if any(f > p.f_max for f in f_n):
        return None, FORCE_OVERLOAD, math.nan

    # 1) 观测 τ = R·f（**只用于状态显示**；2026-11-18 起不再参与控制）
    tau_meas_r = sum(p.r_m[0][i] * f_n[i] for i in range(3))
    tau_meas_p = sum(p.r_m[1][i] * f_n[i] for i in range(3))

    # 2) 【已移除】力矩 PI 外环。
    #    旧实现：u = sat(Kp_τ·(τ_d − R·f) + ∫, ±lim)，再把 τ_d+u 送 TDA。
    #    实测（τ_d=0.1、预紧15）：外环关掉反而更好
    #        Kp=0,Ki=0 → 稳态 0.1012，摆动 0.0038，α≡1
    #        Kp=20,Ki=10 → 稳态 0.1147，摆动 0.0751，51% 的拍 α<1
    #    原因：TDA 算 f_d 精确、内环跟得上 → R·f 自然≈τ_d，外环只是在
    #    "内环还没跟上"的窗口里过度纠正 → 振荡。故 P 外环删除。
    #    ⚠ 2026-11-24：**只保留积分**的"力矩修正"已加回（`tau_trim_step`），
    #    由调用方把 `τ* + ∫(τ*−R·f)` 作为 tau_d 传进来；本函数仍然只做前馈，
    #    所以这里的 τ_d 可能已经含修正量。
    #    参数 kp/ki/deadband 保留（兼容旧调用/布局），但**不再使用**。

    # 3) TDA 分配（前馈：τ_d 直接进 TDA → 三缆目标张力 f_d）
    f_d, tda_flags, alpha = tda_solver(p.r_m, p.null_dir,
                                        p.tau_d[0], p.tau_d[1],
                                        p.preload_n, p.f_min, p.f_max)
    if f_d is None:
        return None, tda_flags | FORCE_TDA_INFEASIBLE, math.nan

    # 4) 张力误差 → 增量步长（内环执行，与张力/张紧模式同一增量基元）。
    #    trim_sign 在出口统一翻方向；内环 P/I 分离（2026-11-17，旧 trim_gain
    #    是 P=I 单旋钮 → S·50=2.32 越界，实测 50Hz 极限环 + 稳态跟不到目标）。
    trim = [0.0, 0.0, 0.0]
    for i in range(3):
        f_err = f_d[i] - f_n[i]
        state.integ[i], state.resid[i], step = _incr_step(
            f_err, state.integ[i], state.resid[i],
            _per_cable(p.kp3, p.kp_inner, i), _per_cable(p.ki3, p.ki_inner, i),
            dt, _per_cable(p.max_step3, p.max_step, i),
            _per_cable(p.i_term_lim3, p.i_term_lim, i))
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

    **逐缆增益（2026-11-24 用户要求）**：`kp3/ki3/max_step3/i_term_lim3` 为
    长度 3 的列表，给了就**按缆覆盖**对应标量（`None` = 三缆共用标量）。
    三根缆的摩擦/绳长/预紧不同，一套增益不可能同时最优
    （现场：C2 一直上不去、C1 却在摆）。
    """

    __slots__ = ("f_target", "kp", "ki", "trim_sign",
                 "max_trim", "max_step", "f_max", "deadband", "i_term_lim",
                 "kp3", "ki3", "max_step3", "i_term_lim3")

    def __init__(self, f_target, kp: float, ki: float, trim_sign,
                 max_trim: float, f_max: float, deadband: float,
                 max_step: float = 5.0, i_term_lim: float = None, *,
                 kp3=None, ki3=None, max_step3=None, i_term_lim3=None):
        if (not isinstance(f_target, (list, tuple)) or len(f_target) != 3
                or not all(_finite(v) and v >= 0.0 for v in f_target)):
            raise ValueError("f_target 需为长度 3 的非负有限数组 [N]")
        # 2026-11-20：未显式给 i_term_lim → 用模块常量（与力矩模式同一个缺省口径）
        if i_term_lim is None:
            i_term_lim = tension_i_term_lim_counts() or float(max_trim)
        (kp, ki, trim_sign, max_trim, max_step, f_max, deadband,
         i_term_lim) = _check_common(kp, ki, trim_sign, max_trim, max_step,
                                     f_max, deadband, i_term_lim)
        self.f_target = [float(v) for v in f_target]
        self.kp, self.ki = kp, ki
        self.trim_sign = trim_sign
        self.max_trim, self.f_max = max_trim, f_max
        self.max_step = max_step
        self.deadband = deadband
        self.i_term_lim = i_term_lim
        # 逐缆覆盖：长度必须 3 且非负有限；给了非法值直接拒绝（不静默忽略）
        for nm, v in (("kp3", kp3), ("ki3", ki3),
                      ("max_step3", max_step3), ("i_term_lim3", i_term_lim3)):
            if v is None:
                setattr(self, nm, None)
                continue
            if (not isinstance(v, (list, tuple)) or len(v) != 3
                    or not all(_finite(x) and x >= 0.0 for x in v)):
                raise ValueError(f"{nm} 需为长度 3 的非负有限数组")
            setattr(self, nm, [float(x) for x in v])


# 张力环状态类见上面的 `IncrPiState`（三个力控模式共用）。


def wrist_tension_cable_step(state: WristTensionState, cable: int, error_n: float,
                            *, kp: float, ki: float, dt: float, max_step: float,
                            i_term_lim: float, deadband: float = 0.05) -> int:
    """单缆张力 PI。调用方校验反馈并将收绳为正的步长转换为电机方向。"""
    error = 0.0 if abs(error_n) <= deadband else error_n
    state.integ[cable], state.resid[cable], step = _incr_step(
        error, state.integ[cable], state.resid[cable], kp, ki, dt, max_step, i_term_lim)
    return step


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
        step = wrist_tension_cable_step(
            state, i, p.f_target[i] - f_n[i],
            kp=_per_cable(p.kp3, p.kp, i), ki=_per_cable(p.ki3, p.ki, i),
            dt=dt, max_step=_per_cable(p.max_step3, p.max_step, i),
            i_term_lim=_per_cable(p.i_term_lim3, p.i_term_lim, i),
            deadband=p.deadband)
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
                 "max_trim", "max_step", "f_max", "f_min", "deadband", "null_dir",
                 "i_term_lim")

    def __init__(self, t_target: float, kp: float, ki: float, trim_sign,
                 max_trim: float, f_max: float, deadband: float, null_dir,
                 max_step: float = 5.0, f_min: float = 0.0,
                 i_term_lim: float = None):
        if not _finite(t_target) or t_target < 0.0:
            raise ValueError("t_target 需为非负有限数 [N]")
        # 2026-11-20：未显式给 i_term_lim → 用模块常量（与张力/力矩同一个缺省口径）
        if i_term_lim is None:
            i_term_lim = tension_i_term_lim_counts() or float(max_trim)
        (kp, ki, trim_sign, max_trim, max_step, f_max, deadband,
         i_term_lim) = _check_common(kp, ki, trim_sign, max_trim, max_step,
                                     f_max, deadband, i_term_lim)
        if not _finite(f_min) or f_min < 0.0 or f_min >= f_max:
            raise ValueError("f_min 需为 0（禁用）或 [0, f_max)")
        if null_dir is not None and (not isinstance(null_dir, (list, tuple))
                                     or len(null_dir) != 3):
            raise ValueError("null_dir 需为长度 3 数组或 None")
        self.t_target = float(t_target)
        self.kp, self.ki = kp, ki
        self.trim_sign = trim_sign
        self.max_trim, self.max_step = max_trim, max_step
        self.f_max = f_max
        self.f_min = float(f_min)
        self.deadband = deadband
        self.null_dir = null_dir
        self.i_term_lim = i_term_lim


# ============================================================
# 张紧模式：2026-11-19 起**实现在 mmhand_scope._cl_tick_tight**
#   f_d = t*·n̂ → 复用 wrist_tension_step（每缆绝对目标）
# 旧的单标量 PI（wrist_tight_step + WristTightState + 方向地板）已删除：
#   反馈秩只有 1，n̂_i 小的缆不可观测；新结构秩 3。
# 这里只保留 `WristTightParams` 作为**参数容器**（scope 仍在用）。
# ============================================================

