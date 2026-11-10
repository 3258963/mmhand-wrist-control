"""腕部绳张力守卫与 τ=Rf 观测 —— 纯函数，无状态，可移植。

输入：三缆张力 f[3]（N）、样本年龄 age_ms、位姿（rad）；
输出：τ=R·f 关节力矩、内预紧分量 f·n̂、逐缆松绳/过载标志。

设计约定（2026-10-25 PLAN）：
- f_min/f_max 无默认值：必须由实机标定给定，不得编造数值；
- 样本过期 / 负值 / NaN / Inf：一律 TENSION_STALE 短路，不用旧数据做
  安全判断（对齐 P4 磁编样本 300ms 年龄口径）；
- 预紧分量依赖全正零空间方向；无全正方向的姿态（1,664/3,621 CAD 网格）
  preload=NaN，但 τ 不依赖零空间、照常计算；
- 本模块只做判定与观测，不驱动执行器：过载后的处置（停闭环/急停）
  由调用方按 TENSION_OVERLOAD 执行。

对应 C 结构：
    typedef struct {
        float f_min_n;      /* 松绳阈值 N，实测给定 */
        float f_max_n;      /* 过载阈值 N，实测给定 */
        float max_age_ms;   /* 样本年龄上限，默认 300 */
    } wrist_tension_config_t;

    /* 返回 flags（TENSION_*）；STALE 时其余字段为 NaN/False */
    int wrist_tension_evaluate(const float f_n[3], float age_ms,
                               const wrist_tension_config_t *cfg,
                               float roll_rad, float pitch_rad,
                               wrist_tension_eval_t *out);
"""
from __future__ import annotations

import math

from wrist_model import PITCH, ROLL, positive_null_direction, wrist_eval

TENSION_OK = 0
TENSION_STALE = 1 << 0     # 样本过期/无效/几何无效：本拍不做安全判断
TENSION_SLACK = 1 << 1     # 任一缆低于 f_min（松绳，仅提示）
TENSION_OVERLOAD = 1 << 2  # 任一缆高于 f_max（过载，调用方应停闭环）


class TensionConfig:
    """守卫阈值。f_min/f_max 无默认值：必须实机给定（构造参数缺省/非法即抛错）。"""

    __slots__ = ("f_min_n", "f_max_n", "max_age_ms")

    def __init__(self, f_min_n: float = None, f_max_n: float = None,
                 max_age_ms: float = 300.0):
        if f_min_n is None or f_max_n is None:
            raise ValueError("f_min_n / f_max_n 无默认值：必须由实机标定显式给定")
        if not (math.isfinite(f_min_n) and math.isfinite(f_max_n)):
            raise ValueError("f_min_n / f_max_n 必须为有限值")
        if f_min_n < 0.0 or f_max_n <= f_min_n:
            raise ValueError("需要 0 ≤ f_min_n < f_max_n")
        if not (math.isfinite(max_age_ms) and max_age_ms > 0.0):
            raise ValueError("max_age_ms 必须为正")
        self.f_min_n = float(f_min_n)
        self.f_max_n = float(f_max_n)
        self.max_age_ms = float(max_age_ms)


class TensionEval:
    """单次评估结果快照。STALE 时 τ/预紧为 NaN、slack/overload 全 False。"""

    __slots__ = ("flags", "tau_roll_nm", "tau_pitch_nm", "preload_n",
                 "slack", "overload")

    def __init__(self) -> None:
        self.flags = TENSION_STALE
        self.tau_roll_nm = math.nan
        self.tau_pitch_nm = math.nan
        self.preload_n = math.nan
        self.slack = [False, False, False]
        self.overload = [False, False, False]


def _stale() -> TensionEval:
    return TensionEval()   # 初值即 STALE 短路结果


def tension_evaluate(f_n, age_ms: float, cfg: TensionConfig,
                     roll_rad: float, pitch_rad: float) -> TensionEval:
    """评估一拍张力：τ=R(θ)·f、预紧 f·n̂、逐缆松绳/过载。"""
    if len(f_n) != 3:
        return _stale()
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0.0
               for v in f_n):
        return _stale()
    if not (math.isfinite(age_ms) and 0.0 <= age_ms <= cfg.max_age_ms):
        return _stale()
    if not (math.isfinite(roll_rad) and math.isfinite(pitch_rad)):
        return _stale()

    out_model = wrist_eval(roll_rad, pitch_rad)
    if not out_model.math_valid:
        return _stale()

    ev = TensionEval()
    ev.flags = TENSION_OK
    ev.tau_roll_nm = sum(out_model.r_m[ROLL][i] * f_n[i] for i in range(3))
    ev.tau_pitch_nm = sum(out_model.r_m[PITCH][i] * f_n[i] for i in range(3))

    n = positive_null_direction(roll_rad, pitch_rad, out_model=out_model)
    if n is not None:
        ev.preload_n = sum(f_n[i] * n[i] for i in range(3))

    for i in range(3):
        if f_n[i] < cfg.f_min_n:
            ev.slack[i] = True
        if f_n[i] > cfg.f_max_n:
            ev.overload[i] = True
    if any(ev.slack):
        ev.flags |= TENSION_SLACK
    if any(ev.overload):
        ev.flags |= TENSION_OVERLOAD
    return ev
