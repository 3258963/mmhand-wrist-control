"""腕部两轴负反馈控制律 —— 纯函数模块，专为移植设计。

无任何 Qt / 串口 / 全局状态依赖；每个函数与 C 实现一一对应，
迁移到 STM32 时按函数逐行翻译即可（float 运算，无动态分配）。

对应 C 结构建议：
    typedef struct {
        int32_t origin[3];        /* M27/M28/M29 使能起点（counts） */
        float   gain_roll[3];     /* ROLL 通道系数，counts/deg，带符号 */
        float   gain_pitch[3];    /* PITCH 通道系数，counts/deg，带符号 */
        float   kp;               /* 误差比例增益（无量纲） */
        float   deadband_deg;     /* 死区（deg），抑制编码器噪声 */
        float   target_limit_deg; /* 目标角限幅（deg） */
        int32_t soft_limit;       /* 相对起点的输出限幅（counts） */
    } wrist_control_params_t;

    void wrist_control_step(const wrist_control_params_t *p,
                            float roll_deg, float pitch_deg,
                            float roll_target_deg, float pitch_target_deg,
                            int32_t out[3]);

坐标约定：
    roll/pitch 为相对"基准零点"的角度（deg，正负号由安装方向决定）；
    out[i] 为 M27+i 的绝对 logical ABS 目标（counts）。

v2 位置环（2026-10-25 前馈+P，2026-11-10 扩为两种结构）：
    一种结构、两个变体，都由 wrist_control_step_pid 实现：

    A. 前馈 + PID（feedforward=True，绝对式）
       前馈 = k_i · [l_i(目标位姿) − l_i(参考位姿)]，l 由 wrist_model 六段几何求值；
       参考位姿 = 启动瞬间的实测位姿（不是模型零位，否则稳态偏 θ_e/(1+kp)）。
       PID  = 关节角域 δθ = kp·e + ki·∫e dt + kd·(−dθ_fb/dt)，
              再经当前雅可比 J_i = −k_i·R_i 折算到 counts。
    B. 纯 PID（feedforward=False，增量式）
       没有"角度→绝对 counts"的模型映射，只能以**实测位置**为基准：
       out = 实测 counts + J_i·δθ；δθ 同上（PID 在关节角域，比例/积分/微分都作用在 e 上）。

    符号（2026-11-10 更正为"符号无关"表述）：
        k 的定义是 Δcounts = k·Δl，所以 k>0 ⇒ counts 增大是放绳（绳变长）、
        k<0 ⇒ counts 增大是收绳。k 的符号 = 硬件收放方向，由台架点动判定，
        位置环**不假设**它是正是负：J_i = −k_i·R_i 自带方向，两种结构的输出
        都随 k 的符号整体翻转，因此只要 k 与硬件一致就不会反。
        位置环不需要 trim_sign（那是给没有雅可比的三个力控模式用的），
        但不变量仍然成立：sign(trim_sign_i) = −sign(k_i)，两者以同一次点动为准。

    θ_model = θ_rel + δ 全链只校正一次；角度接口一律 deg，rad 转换仅在出口前一处。

    对应 C 结构（追加到 v1 结构体之后）：
        typedef struct {
            float k_counts_per_m[3];   /* M27+i 收放系数，counts/m，符号=硬件方向 */
            float zero_offset_deg[2];  /* δr, δp：基线零位对应的模型角偏移，deg */
        } wrist_calib_t;

        typedef struct {               /* 位置环 PID 状态（C 里放静态区） */
            float integ_deg[2];        /* ∫e dt，deg·s */
            float d_filt_deg_s[2];     /* 一阶滤波后的 −dθ_fb/dt，deg/s */
            float prev_fb_deg[2];
            uint8_t primed;
        } wrist_pid_state_t;

        /* 返回 status 标志位（FLAG_*）；有硬错误标志时 out 不可用且不发送 */
        int wrist_control_step_pid_c(const wrist_control_params_t *p,
                                     const wrist_calib_t *calib,
                                     wrist_pid_state_t *st,
                                     float roll_deg, float pitch_deg,
                                     float roll_tgt_deg, float pitch_tgt_deg,
                                     float dt, uint8_t feedforward,
                                     const int32_t base_counts[3],
                                     int32_t out[3]);
        /* 旧接口（= ki=kd=0 的变体 A），保留给老调用点与 golden 测试 */
        int wrist_control_step_model_c(...);
"""

from __future__ import annotations

import math

from wrist_model import (
    LOW_PITCH_LIMIT_DEG,
    PITCH,
    RANGE_DEG,
    ROLL,
    wrist_eval,
)

MOTOR_COUNT = 3  # M27, M28, M29


class WristControlParams:
    """控制参数快照。每周期由调用方从 UI/配置读出并填充。

    ki/kd 只服务位置环（wrist_control_step_pid）；v1 与力控三模式不读它们。
    """

    __slots__ = (
        "origin", "gain_roll", "gain_pitch", "kp", "ki", "kd",
        "deadband_deg", "target_limit_deg", "soft_limit",
        "i_limit_deg", "d_filter_alpha",
    )

    def __init__(self):
        self.origin = [0] * MOTOR_COUNT
        self.gain_roll = [0.0] * MOTOR_COUNT
        self.gain_pitch = [0.0] * MOTOR_COUNT
        self.kp = 0.0
        self.ki = 0.0                  # 1/s，积分项（关节角域）
        self.kd = 0.0                  # s，微分项（作用在反馈上，见 wrist_control_step_pid）
        self.deadband_deg = 0.0
        self.target_limit_deg = 90.0
        self.soft_limit = 5000
        self.i_limit_deg = 25.0        # 积分项的等效角上限：|ki·∫e| ≤ 此值（防 windup）
        self.d_filter_alpha = 0.25     # 微分一阶低通系数（1=不滤；0=微分恒 0）


def clampf(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def clampi(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else (hi if v > hi else v)


def shortest_angle_delta(cur_deg: float, base_deg: float) -> float:
    """最短角差，结果落在 (-180, 180]。"""
    return (cur_deg - base_deg + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# v2：解析模型前馈 + R 矩阵 P 校正（2026-10-25，追加实现，v1 保持原样）
# ---------------------------------------------------------------------------

# 状态标志（位掩码）。硬错误 = FLAG_NONFINITE / FLAG_GEOM_INVALID：
# 返回 out=None，调用方必须保持上一目标，不得发送 origin（会引起运动）。
FLAG_OK = 0
FLAG_TARGET_CLAMPED = 1 << 0    # 目标角被限幅/模型行程/低置信区钳制
FLAG_LOW_PITCH = 1 << 1         # 最终 pitch 目标 ≤ −24°（低置信区，进区即提示）
FLAG_FEEDBACK_CLAMPED = 1 << 2  # 反馈角被钳入模型行程
FLAG_GEOM_INVALID = 1 << 3      # 模型求值失败（段长退化/非有限）
FLAG_NONFINITE = 1 << 4         # 输入非有限
FLAG_I_CLAMPED = 1 << 5         # 积分项顶到 i_limit_deg（windup 保护生效，输出仍可用）


class WristPidState:
    """位置环 PID 状态（纯数据，可逐字段译成 C 静态结构）。

    - integ_deg：∫e dt（deg·s），按轴存；两轴共用同一组 ki/kd 增益；
    - d_filt_deg_s：一阶低通后的 −dθ_fb/dt（deg/s），微分**作用在反馈上**，
      这样改目标框不会砸出微分尖峰（目标阶跃只在 P 项上体现）；
    - prev_fb_deg / primed：上一拍反馈，首拍无微分。
    """

    __slots__ = ("integ_deg", "d_filt_deg_s", "prev_fb_deg", "primed")

    def __init__(self) -> None:
        self.integ_deg = [0.0, 0.0]
        self.d_filt_deg_s = [0.0, 0.0]
        self.prev_fb_deg = [0.0, 0.0]
        self.primed = False

    def reset(self) -> None:
        self.integ_deg = [0.0, 0.0]
        self.d_filt_deg_s = [0.0, 0.0]
        self.prev_fb_deg = [0.0, 0.0]
        self.primed = False



class WristCalib:
    """腕部标定快照：每电机收放系数 k（counts/m，带符号）+ 模型零偏 δ（deg）。

    δ 语义：基线零位（PC angle_baseline）对应的模型角。θ_model = θ_rel + δ
    是全链唯一校正点；δ 只能来自机械基准，不得与几何系数一起拟合。
    """

    __slots__ = ("k_counts_per_m", "zero_offset_deg")

    def __init__(self, k_counts_per_m, zero_offset_deg):
        self.k_counts_per_m = [float(v) for v in k_counts_per_m]
        self.zero_offset_deg = [float(v) for v in zero_offset_deg]


def parse_wrist_calib(data):
    """解析 wrist_calib.json 内容 -> (WristCalib, None) | (None, 原因)。

    格式：{"version":1,"k_counts_per_m":[3 带符号],"zero_offset_deg":[2]（可缺省=0）}。
    校验：version==1、k 长度 3 且全部有限非零、δ 长度 2 且有限。
    不静默吞错：任何字段缺失/类型错/值非法都返回明确原因。
    """
    if not isinstance(data, dict):
        return None, "标定文件内容不是 JSON 对象"

    version = data.get("version")
    if version != 1:
        return None, f"version 不支持：{version!r}（需要 1）"

    def _finite_list(key, n):
        """取 key 字段 -> (list[float] | None, 原因 | None)。"""
        if key not in data:
            return None, f"缺少字段 {key}"
        vals = data[key]
        if not isinstance(vals, (list, tuple)) or len(vals) != n:
            return None, f"{key} 需为长度 {n} 的数组"
        try:
            out = [float(v) for v in vals]
        except (TypeError, ValueError):
            return None, f"{key} 含非数值"
        if not all(math.isfinite(v) for v in out):
            return None, f"{key} 含 NaN/Inf"
        return out, None

    k, err = _finite_list("k_counts_per_m", 3)
    if err:
        return None, err
    if any(v == 0.0 for v in k):
        return None, "k_counts_per_m 含 0：未标定或文件损坏"

    if "zero_offset_deg" in data:
        d, err = _finite_list("zero_offset_deg", 2)
        if err:
            return None, err
    else:
        d = [0.0, 0.0]
    return WristCalib(k, d), None


def wrist_control_step_pid(p: WristControlParams,
                           calib: WristCalib,
                           state: "WristPidState | None",
                           roll_deg: float,
                           pitch_deg: float,
                           roll_tgt_deg: float,
                           pitch_tgt_deg: float,
                           dt: float,
                           feedforward: bool = True,
                           base_counts=None,
                           roll_enabled: bool = True,
                           pitch_enabled: bool = True,
                           ref_roll_deg: float | None = None,
                           ref_pitch_deg: float | None = None) -> tuple:
    """位置环一拍：可选模型前馈 + 关节角域 PID（经当前雅可比折算到 counts）。

    两种结构（同一份代码，只差基准）：

        A 前馈+PID（feedforward=True，绝对式）
            out = origin + k·[l(θ*) − l(ref)] + J(θ_fb)·δθ
        B 纯PID（feedforward=False，增量式）
            out = 实测 counts + J(θ_fb)·δθ
          ——没有"角度→绝对 counts"的映射，基准只能是实测位置（与三个力控模式
            同一个执行器语义：每拍从实测出发走一步）。

        δθ_A = kp·e + ki·∫e·dt + kd·(−dθ_fb/dt)         （关节角域，deg）
        J_i  = −k_i·R_i·(π/180)                          （counts/deg，自带硬件方向）

    Args:
        state: PID 状态；None = 旧接口（ki/kd 强制为 0、不读写状态，等价于纯 P）。
        dt: 本拍实际间隔（s），积分/微分用；state=None 时忽略。
        base_counts: 变体 B 的基准（实测电机 counts，3 个）；变体 A 忽略。
        ref_*: 变体 A 的前馈参考位姿；**必须是 origin 对应的那个实测位姿**。

    Returns:
        (out[3] | None, flags)：硬错误（非有限/几何无效/基准缺失）时 out=None，
        调用方必须保持上一目标、不得发送 origin（会引起运动）。
    """
    ins = (roll_deg, pitch_deg, roll_tgt_deg, pitch_tgt_deg)
    if not all(math.isfinite(v) for v in ins):
        return None, FLAG_NONFINITE
    if (not all(math.isfinite(v) for v in calib.k_counts_per_m)
            or not all(math.isfinite(v) for v in calib.zero_offset_deg)):
        return None, FLAG_NONFINITE
    if ((ref_roll_deg is not None and not math.isfinite(ref_roll_deg))
            or (ref_pitch_deg is not None and not math.isfinite(ref_pitch_deg))):
        return None, FLAG_NONFINITE
    if not math.isfinite(dt) or dt < 0.0:
        return None, FLAG_NONFINITE
    if not feedforward:
        # 变体 B 没有绝对基准，必须由调用方给实测 counts（否则无从谈起"走一步"）。
        if (not isinstance(base_counts, (list, tuple))
                or len(base_counts) != MOTOR_COUNT
                or not all(math.isfinite(v) for v in base_counts)):
            return None, FLAG_NONFINITE

    flags = FLAG_OK
    dr, dp = calib.zero_offset_deg

    # 目标钳制：UI 限幅 ∩ 模型行程；pitch 抬底到低置信区边界 −24°。
    lim = p.target_limit_deg
    lo_r = max(-lim, RANGE_DEG[ROLL][0])
    hi_r = min(lim, RANGE_DEG[ROLL][1])
    lo_p = max(-lim, RANGE_DEG[PITCH][0])
    hi_p = min(lim, RANGE_DEG[PITCH][1])
    rt = clampf(roll_tgt_deg, lo_r, hi_r)
    pt = clampf(pitch_tgt_deg, lo_p, hi_p)
    if rt != roll_tgt_deg or pt != pitch_tgt_deg:
        flags |= FLAG_TARGET_CLAMPED
    if pt <= LOW_PITCH_LIMIT_DEG:
        pt = max(pt, LOW_PITCH_LIMIT_DEG)
        flags |= FLAG_LOW_PITCH

    # 反馈角钳入模型行程（不钳入目标域：限幅是目标的安全约束，不是反馈的）。
    rf = clampf(roll_deg, RANGE_DEG[ROLL][0], RANGE_DEG[ROLL][1])
    pf = clampf(pitch_deg, RANGE_DEG[PITCH][0], RANGE_DEG[PITCH][1])
    if rf != roll_deg or pf != pitch_deg:
        flags |= FLAG_FEEDBACK_CLAMPED

    # deg → rad 仅此一处（目标/反馈/参考一并转换，θ_model = θ_rel + δ）。
    t_r = math.radians(rt + dr)
    t_p = math.radians(pt + dp)
    fb_r = math.radians(rf + dr)
    fb_p = math.radians(pf + dp)
    ref_r = math.radians((ref_roll_deg if ref_roll_deg is not None else 0.0) + dr)
    ref_p = math.radians((ref_pitch_deg if ref_pitch_deg is not None else 0.0) + dp)

    out_t = wrist_eval(t_r, t_p)
    out_ref = wrist_eval(ref_r, ref_p)
    out_fb = wrist_eval(fb_r, fb_p)
    if not (out_t.math_valid and out_ref.math_valid and out_fb.math_valid):
        return None, flags | FLAG_GEOM_INVALID

    e_roll = rt - rf
    e_pitch = pt - pf
    if -p.deadband_deg <= e_roll <= p.deadband_deg:
        e_roll = 0.0
    if -p.deadband_deg <= e_pitch <= p.deadband_deg:
        e_pitch = 0.0

    # ---- 关节角域 PID → 虚拟角修正 δθ（deg）----
    # state=None：旧接口，退化为纯 P（不读 ki/kd、不写状态）。
    if state is None:
        dth_r = p.kp * e_roll
        dth_p = p.kp * e_pitch
    else:
        # 微分作用在**反馈**上：−dθ_fb/dt，改目标框不会砸出微分尖峰。
        if state.primed and dt > 0.0:
            raw_d_r = -(rf - state.prev_fb_deg[0]) / dt
            raw_d_p = -(pf - state.prev_fb_deg[1]) / dt
        else:
            raw_d_r = 0.0
            raw_d_p = 0.0
        a = p.d_filter_alpha
        if a >= 1.0:
            state.d_filt_deg_s[0] = raw_d_r
            state.d_filt_deg_s[1] = raw_d_p
        elif a > 0.0:
            state.d_filt_deg_s[0] += a * (raw_d_r - state.d_filt_deg_s[0])
            state.d_filt_deg_s[1] += a * (raw_d_p - state.d_filt_deg_s[1])
        state.prev_fb_deg = [rf, pf]
        state.primed = True

        # 积分：轴启用才累加；按等效角上限 ±i_limit_deg 钳制（防 windup）。
        i_cap = max(0.0, p.i_limit_deg)
        for ax, e_ax, enabled in ((ROLL, e_roll, roll_enabled),
                                  (PITCH, e_pitch, pitch_enabled)):
            if not enabled or p.ki <= 0.0:
                continue
            state.integ_deg[ax] += e_ax * dt
            cap = i_cap / p.ki
            if state.integ_deg[ax] > cap:
                state.integ_deg[ax] = cap
                flags |= FLAG_I_CLAMPED
            elif state.integ_deg[ax] < -cap:
                state.integ_deg[ax] = -cap
                flags |= FLAG_I_CLAMPED

        dth_r = (p.kp * e_roll + p.ki * state.integ_deg[ROLL]
                 + p.kd * state.d_filt_deg_s[ROLL])
        dth_p = (p.kp * e_pitch + p.ki * state.integ_deg[PITCH]
                 + p.kd * state.d_filt_deg_s[PITCH])
    if not roll_enabled:
        dth_r = 0.0
    if not pitch_enabled:
        dth_p = 0.0

    out = [0] * MOTOR_COUNT
    d2r = math.pi / 180.0
    for i in range(MOTOR_COUNT):
        k_i = calib.k_counts_per_m[i]
        # 分轴开关（2026-11-10）：关掉的轴从「前馈 + 校正」里整体剔除。
        # 旧实现只在 v1 把系数置零，模型路径照样用整张 R 和整段绳长，
        # 勾掉 ROLL环/PITCH环 毫无作用。
        if feedforward:
            dl = 0.0
            if roll_enabled:
                dl += out_t.s_m[ROLL][i] - out_ref.s_m[ROLL][i]
            if pitch_enabled:
                dl += out_t.s_m[PITCH][i] - out_ref.s_m[PITCH][i]
            base = p.origin[i] + k_i * dl
        else:
            base = float(base_counts[i])
        # J_i = −k_i·R_i（counts/deg）：δθ 在关节角域，折算到该缆的 counts。
        delta_c = 0.0
        if roll_enabled:
            delta_c += -k_i * out_fb.r_m[ROLL][i] * (dth_r * d2r)
        if pitch_enabled:
            delta_c += -k_i * out_fb.r_m[PITCH][i] * (dth_p * d2r)
        value = base + delta_c
        out[i] = clampi(int(round(value)),
                        p.origin[i] - p.soft_limit,
                        p.origin[i] + p.soft_limit)
    return out, flags


def wrist_control_step_model(p: WristControlParams,
                             calib: WristCalib,
                             roll_deg: float,
                             pitch_deg: float,
                             roll_tgt_deg: float,
                             pitch_tgt_deg: float,
                             roll_enabled: bool = True,
                             pitch_enabled: bool = True,
                             ref_roll_deg: float | None = None,
                             ref_pitch_deg: float | None = None) -> tuple:
    """旧接口：模型绳长前馈 + P 校正（= ki=kd=0 的变体 A），行为逐位不变。

    保留给老调用点与 golden 测试（2026-11-10 起新代码用 wrist_control_step_pid）。

    ref_*：前馈参考位姿（与 roll_deg/pitch_deg 同一坐标系，δ 由函数内部再加）。
    缺省 None = 模型零位（δ），即"origin 对应零位姿态"的旧假设。
    **正确用法是传启动瞬间的实测位姿**：前馈算的是 origin→目标 的绳长增量，
    而 origin 记的是启动瞬间的电机计数，两者必须同一个姿态。若启动时读数
    不是 0 却按 0 算，稳态偏差 = −θ_e/(1+kp)（kp=0.6 时 0.625 倍，不是放大）。
    """
    return wrist_control_step_pid(
        p, calib, None, roll_deg, pitch_deg, roll_tgt_deg, pitch_tgt_deg,
        dt=0.0, feedforward=True,
        roll_enabled=roll_enabled, pitch_enabled=pitch_enabled,
        ref_roll_deg=ref_roll_deg, ref_pitch_deg=ref_pitch_deg)


def wrist_control_step(p: WristControlParams,
                       roll_deg: float,
                       pitch_deg: float,
                       roll_target_deg: float,
                       pitch_target_deg: float) -> list:
    """一拍控制律：前馈 + 误差 P 校正 + 双重限幅。

    out[i] = origin[i]
           + gain_roll[i] * roll_tgt_clamped
           + gain_pitch[i] * pitch_tgt_clamped
           + kp * (gain_roll[i] * err_roll + gain_pitch[i] * err_pitch)
    误差先过死区；目标角先过 ±target_limit；输出钳到 origin±soft_limit。
    """
    lim = p.target_limit_deg
    r_tgt = clampf(roll_target_deg, -lim, lim)
    p_tgt = clampf(pitch_target_deg, -lim, lim)

    e_roll = r_tgt - roll_deg
    e_pitch = p_tgt - pitch_deg
    if -p.deadband_deg <= e_roll <= p.deadband_deg:
        e_roll = 0.0
    if -p.deadband_deg <= e_pitch <= p.deadband_deg:
        e_pitch = 0.0

    out = [0] * MOTOR_COUNT
    for i in range(MOTOR_COUNT):
        value = (p.origin[i]
                 + p.gain_roll[i] * r_tgt
                 + p.gain_pitch[i] * p_tgt
                 + p.kp * (p.gain_roll[i] * e_roll
                           + p.gain_pitch[i] * e_pitch))
        out[i] = clampi(int(round(value)),
                        p.origin[i] - p.soft_limit,
                        p.origin[i] + p.soft_limit)
    return out


if __name__ == "__main__":
    # 自测：与实机验证过的四组用例一致。
    p = WristControlParams()
    p.origin = [1000, 2000, 3000]
    p.gain_roll = [50.0, 0.0, 30.0]
    p.gain_pitch = [0.0, -40.0, 30.0]
    p.kp = 0.6
    p.deadband_deg = 0.3
    p.target_limit_deg = 25.0
    p.soft_limit = 5000

    # 1) 前馈+P：实际 ROLL=1 目标 2 -> [1130, 2000, 3078]
    assert wrist_control_step(p, 1.0, 0.0, 2.0, 0.0) == [1130, 2000, 3078]
    # 2) 负系数 PITCH：实际 +1 目标 -1 -> M28 = 2088
    assert wrist_control_step(p, 1.0, 1.0, 2.0, -1.0)[1] == 2088
    # 3) 目标限幅：100° 被压到 25° -> M27 = 1000+1250+720 = 2970
    assert wrist_control_step(p, 1.0, 0.0, 100.0, 0.0)[0] == 2970
    # 4) 死区：误差 0.2°<0.3° -> 误差项为 0，M27 = 1100
    assert wrist_control_step(p, 1.8, 0.0, 2.0, 0.0)[0] == 1100
    # 5) 最短角差跨绕回点
    assert abs(shortest_angle_delta(-179.0, 179.0) - 2.0) < 1e-9

    # ---- v2 位置环两种结构自测 ----
    # 两种符号各测一遍：出厂标定是 k=+130380（counts↑=放绳），镜像 k<0 也必须对称。
    calib = WristCalib([130380.0] * 3, [0.0, 0.0])
    calib_neg = WristCalib([-130380.0] * 3, [0.0, 0.0])
    q = WristControlParams()
    q.origin = [0, 0, 0]
    q.kp, q.ki, q.kd = 0.6, 0.0, 0.0
    q.deadband_deg = 0.3
    q.target_limit_deg = 25.0
    q.soft_limit = 2_000_000

    st = WristPidState()
    # A) 前馈+PID：误差为 0 且参考=当前 ⇒ 输出就是 origin（无零位漂移）
    out_a, fl_a = wrist_control_step_pid(q, calib, st, 0.0, 0.0, 0.0, 0.0, 0.01)
    assert out_a == [0, 0, 0] and fl_a == FLAG_OK, (out_a, fl_a)
    # B) 纯 PID：误差为 0 ⇒ 输出 = 实测基准（原地保持）
    base = [100, 200, 300]
    out_b, fl_b = wrist_control_step_pid(q, calib, st, 0.0, 0.0, 0.0, 0.0, 0.01,
                                         feedforward=False, base_counts=base)
    assert out_b == base, out_b
    # C) 纯 PID：ROLL 目标 +1° ⇒ 方向随 k 的符号整体翻转
    out_c, _ = wrist_control_step_pid(q, calib, st, 0.0, 0.0, 1.0, 0.0, 0.01,
                                      feedforward=False, base_counts=base)
    out_c2, _ = wrist_control_step_pid(q, calib_neg, st, 0.0, 0.0, 1.0, 0.0, 0.01,
                                       feedforward=False, base_counts=base)
    assert out_c[1] > base[1] and out_c2[1] < base[1], (out_c, out_c2)
    # D) 积分：恒定 1° 误差下 ∫e 增长，修正量随之变大（用绝对位移比较，方向随 k）
    st.reset()
    o1, _ = wrist_control_step_pid(q, calib, st, 0.0, 0.0, 1.0, 0.0, 0.01,
                                   feedforward=False, base_counts=base)
    q.ki = 5.0
    for _ in range(20):
        o2, _ = wrist_control_step_pid(q, calib, st, 0.0, 0.0, 1.0, 0.0, 0.01,
                                       feedforward=False, base_counts=base)
    assert abs(o2[1] - base[1]) > abs(o1[1] - base[1]) * 1.5, (o1, o2)
    # E) 积分钳位：把 ki 拉到很大，|ki·∫e| 不会超过 i_limit_deg
    q.ki = 1000.0
    for _ in range(200):
        wrist_control_step_pid(q, calib, st, 0.0, 0.0, 25.0, 0.0, 0.01,
                               feedforward=False, base_counts=base)
    assert abs(q.ki * st.integ_deg[0]) <= q.i_limit_deg + 1e-9, st.integ_deg
    print("wrist_control_law 自测全部通过")

