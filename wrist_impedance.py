"""阻抗控制外环（2026-11-22 框架，`τ_ff` 待补）。

**定位**：这是四层控制里的**最外层**（任务层）。它只做一件事：

    位置误差 ──► 力矩目标

     τ* = K_θ·(q* − q) + D_θ·(q̇* − q̇) + τ_ff

算出的 τ* 交给**力矩层**（`wrist_tda.allocate_torque_priority` → 三缆张力
目标 → 张力环 PI），所以本模块：

* 不碰电机、不碰张力、不知道缆怎么分
* 纯函数、无状态、可单测（100% 可复现）
* 与 `wrist_force_law` / `wrist_tda` 同一条"可逐行译成 C"的口径

> **符号约定**：本模块输出的是 **UI 角度口径**的 τ（与传入的 `roll_deg` 同号）。
> 硬件方向修正不在本模块做——上位机 `_cl_tick_impedance` 会把 roll 乘
> `IMPEDANCE_ROLL_SIGN`（2026-11-23 台架实测 roll 方向反），pitch 不动。

## 三个参数的物理意义

| 参数 | 作用 | 取 0 时 |
|---|---|---|
| `K`（刚度）[N·m/rad] | 偏离目标就给回中力矩 | **退化成纯力矩控制**（τ=τ_ff） |
| `D`（阻尼）[N·m/(rad/s)] | 抑制回中过冲 | 无阻尼（可能振荡） |
| `τ_ff`（前馈）[N·m] | 抵消重力/外载（**待补**） | 目标点会被自重压偏 `τ_g/K` |

## 为什么 K 不能无限大

`K` 越大越"硬"，但需要的力矩也越大：

    τ = K·|q* − q|  ⟹  偏 0.2 rad(11.5°) 时 τ = 0.2K

本机力矩能力约 0.43~1.44 N·m（方向不对称）⟹ `K ≲ 1.5 N·m/rad` 较安全，
更硬就交给**位置模式**（缆弹性刚度 4.3/20 N·m/rad）。

## 未实现的接线（下一步）

* `τ_ff`：起环静止时锁一次 `τ_ff = R(q0)·f_meas0`（不需要知道腕质量）
* ~~阻尼用的 `q̇`~~ —— **2026-11-25 已接线**：上位机用 `RateFilter`
  （差分 + 一阶低通）从 J16/J17 磁编算角速度，传 `q̇* − q̇` 进来。
"""
from __future__ import annotations

import math

ROLL = 0
PITCH = 1

IMP_OK = 0
IMP_NO_TARGET = 1 << 0       # 目标角非法（NaN/Inf）
IMP_TAU_CLAMPED = 1 << 1     # 输出力矩被 tau_*_max 钳制


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


def gravity_tau_sine(amp_roll, amp_pitch, roll_deg, pitch_deg):
    """重力力矩的**串列式正弦模型** + 取反（前馈用）。

    ## 机构假设：roll 是外轴，pitch 是内轴（串列）

    roll 转起来以后，pitch 轴的力臂方向也跟着转 —— 所以 **roll 会影响 pitch 的
    重力矩**，而 pitch 不影响 roll（外轴不感受内轴的转角）：

        τ_g,roll  = A_r · sin(roll)
        τ_g,pitch = A_p · sin(pitch) · cos(roll)      ← 关键是 cos(roll)

    物理直觉：`roll = 0°` 时 pitch 轴的力臂完全展开（cos0=1，力矩最大）；
    `roll = ±90°` 时 pitch 轴被转到"与重力平行"的位置（cos90=0，**力矩为 0**）。

    前馈要**反向顶住**重力（"重力要取反"）：

        τ_ff,roll  = −A_r · sin(roll)
        τ_ff,pitch = −A_p · sin(pitch) · cos(roll)

    `A_i` = **90° 处的重力力矩幅值**（用户给 0.3 ⇒ A=0.3）。
    `A<0` = 翻转方向（实际重力往另一边拉时用）。

    Args:
        amp_roll, amp_pitch: 90° 处重力力矩幅值 [N·m]
        roll_deg, pitch_deg: 当前实测角 [deg]

    Returns:
        (tau_ff_roll, tau_ff_pitch) [N·m]
    """
    d2r = math.pi / 180.0
    ar = float(amp_roll) if _finite(amp_roll) else 0.0
    ap = float(amp_pitch) if _finite(amp_pitch) else 0.0
    qr = float(roll_deg) if _finite(roll_deg) else 0.0
    qp = float(pitch_deg) if _finite(pitch_deg) else 0.0
    cr = math.cos(qr * d2r)
    return (-ar * math.sin(qr * d2r),
            -ap * math.sin(qp * d2r) * cr)


class WristImpedanceParams:
    """阻抗外环参数（2 自由度：roll / pitch）。

    与力控其它 params 类同款约定：构造即校验，非法直接 ValueError，
    避免"参数坏了一半"跑到 100 Hz 环里。
    """

    __slots__ = ("k_roll", "k_pitch", "d_roll", "d_pitch",
                 "tau_ff", "tau_r_max", "tau_p_max", "deadband_deg")

    def __init__(self, k_roll: float, k_pitch: float,
                 d_roll: float = 0.0, d_pitch: float = 0.0,
                 tau_ff=(0.0, 0.0),
                 tau_r_max: float = 0.0, tau_p_max: float = 0.0,
                 deadband_deg: float = 0.0):
        for name, v in (("k_roll", k_roll), ("k_pitch", k_pitch),
                        ("d_roll", d_roll), ("d_pitch", d_pitch)):
            if not _finite(v) or v < 0.0:
                raise ValueError(f"{name} 需为非负有限数")
        if (not isinstance(tau_ff, (list, tuple)) or len(tau_ff) != 2
                or not all(_finite(v) for v in tau_ff)):
            raise ValueError("tau_ff 需为长度 2 的有限数组 [N·m]")
        for name, v in (("tau_r_max", tau_r_max), ("tau_p_max", tau_p_max)):
            if not _finite(v) or v < 0.0:
                raise ValueError(f"{name} 需为非负有限数")
        if not _finite(deadband_deg) or deadband_deg < 0.0:
            raise ValueError("deadband_deg 需为非负有限数")
        self.k_roll = float(k_roll)
        self.k_pitch = float(k_pitch)
        self.d_roll = float(d_roll)
        self.d_pitch = float(d_pitch)
        self.tau_ff = (float(tau_ff[0]), float(tau_ff[1]))
        self.tau_r_max = float(tau_r_max)
        self.tau_p_max = float(tau_p_max)
        self.deadband_deg = float(deadband_deg)


class RateFilter:
    """角度序列 → 角速度 [deg/s]：差分 + 一阶低通（**纯状态机，可单测**）。

    为什么需要：阻抗的 D 项要 `q̇`，而编码器只给角度。直接差分噪声太大
    （14 bit 磁编量化 0.022°，100 Hz 下每 1 count 就是 2.2 °/s），所以
    先差分、再按时间常数 `tau_s` 过一阶 EMA。

    两个安全点：
      · `dt` 超出 `[dt_min, dt_max]`（首拍 / 停环 / 线程卡顿）→ 本次不更新、
        输出 0，并把基准重置到当前角度。否则一次 200 ms 的卡顿会被算成
        "巨大角速度"，D 项会瞬间给一个反方向力矩尖峰。
      · 差分结果先按 `±max_dps` 限幅再进 EMA —— 编码器偶发跳变不会穿到力矩。

    用法（上位机每拍调一次）：:

        f = RateFilter(tau_s=0.03)
        w_roll, w_pitch = f.update(roll, pitch, time.perf_counter())
        ...
        f.reset()          # 起环 / 停环 / 换模式时清状态
    """

    __slots__ = ("tau_s", "max_dps", "dt_min", "dt_max",
                 "_prev", "_prev_t", "_rate")

    def __init__(self, tau_s: float = 0.03, max_dps: float = 500.0,
                 dt_min: float = 0.002, dt_max: float = 0.05):
        if not _finite(tau_s) or tau_s < 0.0:
            raise ValueError("tau_s 需为非负有限数 [s]")
        if not _finite(max_dps) or max_dps <= 0.0:
            raise ValueError("max_dps 需为正有限数 [deg/s]")
        if not (_finite(dt_min) and _finite(dt_max)) or not (0.0 < dt_min < dt_max):
            raise ValueError("需要 0 < dt_min < dt_max")
        self.tau_s = float(tau_s)
        self.max_dps = float(max_dps)
        self.dt_min = float(dt_min)
        self.dt_max = float(dt_max)
        self.reset()

    def reset(self) -> None:
        """清空基准与滤波状态（下一次 `update` 只记基准、输出 0）。"""
        self._prev = None
        self._prev_t = None
        self._rate = [0.0, 0.0]

    def update(self, roll_deg: float, pitch_deg: float,
               now_s: float) -> tuple:
        """喂一拍角度，返回这一拍的角速度 `(droll, dpitch)` [deg/s]。

        Args:
            roll_deg, pitch_deg: 当前实测角（与调用方同一口径，本类不做换号）
            now_s: 单调时基（`time.perf_counter()`）。用调用方给的时刻，
                   而不是内部取时，便于单测与跨线程一致。

        Returns:
            (droll_dps, dpitch_dps)；非法输入 / 首拍 / 间隔越界 → (0, 0)。
        """
        if not (_finite(roll_deg) and _finite(pitch_deg) and _finite(now_s)):
            return 0.0, 0.0
        prev, prev_t = self._prev, self._prev_t
        self._prev = (float(roll_deg), float(pitch_deg))
        self._prev_t = float(now_s)
        if prev is None or prev_t is None:
            return 0.0, 0.0
        dt = float(now_s) - prev_t
        if not (self.dt_min <= dt <= self.dt_max):
            # 首拍/停顿/卡顿：不做差分（大间隔会被当成巨大速度）
            self._rate = [0.0, 0.0]
            return 0.0, 0.0
        lim = self.max_dps
        raw_r = (float(roll_deg) - prev[0]) / dt
        raw_p = (float(pitch_deg) - prev[1]) / dt
        raw_r = max(-lim, min(lim, raw_r))
        raw_p = max(-lim, min(lim, raw_p))
        a = dt / (self.tau_s + dt) if self.tau_s > 0.0 else 1.0
        self._rate[0] += (raw_r - self._rate[0]) * a
        self._rate[1] += (raw_p - self._rate[1]) * a
        return self._rate[0], self._rate[1]


def wrist_impedance_torque(p: WristImpedanceParams,
                           roll_deg: float, pitch_deg: float,
                           roll_tgt_deg: float, pitch_tgt_deg: float,
                           droll_dps: float = 0.0,
                           dpitch_dps: float = 0.0) -> tuple:
    """阻抗外环：位置 → 力矩目标。

    Args:
        p: 参数
        roll_deg, pitch_deg: 当前实测角（UI/硬件口径，单位度）
        roll_tgt_deg, pitch_tgt_deg: 目标角
        droll_dps, dpitch_dps: 角速度 [deg/s]；框架默认 0（不测速度，D 项不起作用）。
            接线时应传 `q̇* − q̇`（目标速率通常 0）。

    Returns:
        (tau_roll, tau_pitch, flags)
        · 正常：flags = IMP_OK
        · 有角被 tau_*_max 钳制：flags |= IMP_TAU_CLAMPED
        · 输入含 NaN/Inf：返回 (nan, nan, IMP_NO_TARGET)（断口语义）
    """
    for v in (roll_deg, pitch_deg, roll_tgt_deg, pitch_tgt_deg,
              droll_dps, dpitch_dps):
        if not _finite(v):
            return math.nan, math.nan, IMP_NO_TARGET

    db = p.deadband_deg
    e_r = roll_tgt_deg - roll_deg
    e_p = pitch_tgt_deg - pitch_deg
    if abs(e_r) <= db:
        e_r = 0.0
    if abs(e_p) <= db:
        e_p = 0.0

    deg2rad = math.pi / 180.0
    # K 项：刚度（N·m/rad × rad）。D 项：阻尼（N·m/(rad/s) × rad/s）。
    # 用 deg→rad 转换而不是把 K 改成 N·m/deg，是为了让 K 的数值等价论文口径。
    tau_r = (p.k_roll * e_r * deg2rad
             + p.d_roll * droll_dps * deg2rad
             + p.tau_ff[ROLL])
    tau_p = (p.k_pitch * e_p * deg2rad
             + p.d_pitch * dpitch_dps * deg2rad
             + p.tau_ff[PITCH])

    flags = IMP_OK
    if p.tau_r_max > 0.0 and abs(tau_r) > p.tau_r_max:
        tau_r = math.copysign(p.tau_r_max, tau_r)
        flags |= IMP_TAU_CLAMPED
    if p.tau_p_max > 0.0 and abs(tau_p) > p.tau_p_max:
        tau_p = math.copysign(p.tau_p_max, tau_p)
        flags |= IMP_TAU_CLAMPED
    return tau_r, tau_p, flags
