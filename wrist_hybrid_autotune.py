"""混合模式（C1 张力 + 双轴角度）的**自动调参序列与指标**（纯数学，无 Qt/IO）。

与张力模式的 `wrist_autotune` 同一套思路，但目标不同：

| | 张力模式 | **混合模式** |
|---|---|---|
| 被控量 | 三缆张力（共模） | **C1 张力（单路）** + **ROLL/PITCH 角度（位置环）** |
| 通道 | 3 个张力环 | 1 个张力环 + 2 个角度环 |
| 激励 | 张力 step + 张力正弦 | **张力 step + 张力正弦 + 角度 step** |

序列（总时长见 `total_seconds()`）：

    ① 保持          — 让角度环先稳住（C1/角度都维持起始目标）
    ② C1 阶跃上      — base+3 N，看张力环超调/上升时间
    ③ C1 阶跃下      — base−3 N，看回落/反向
    ④~⑧ C1 正弦      — 0.1/0.2/0.3/0.4/0.5 Hz（≥3 周期且 ≥12 s）
    ⑨~⑫ 角度阶跃      — ROLL +5° → 回位 → PITCH +5° → 回位

约束（与张力模式一致的安全口径）：
* C1 目标一律夹在 `[c1_min, c1_max]`，且起始段不阶跃；
* 角度目标夹在 `±angle_limit`；
* 正弦从相位 0 起算 ⟹ 起点 = 基值，**不会阶跃**。

设计要点：**C1 张力与角度分开调**——C1 只看 C1 自己的指标，ROLL/PITCH 只看角度指标，
两者互不污染（混合模式里它们是两条独立的内环）。
"""

import math

# ---------- 序号 / 类型 ----------
KIND_HOLD = "hold"
KIND_C1_STEP = "c1_step"
KIND_C1_SINE = "c1_sine"
KIND_ANGLE_STEP = "angle_step"

# ---------- 序列参数 ----------
HOLD_S = 6.0                # 开头让角度环稳住
C1_STEP_SPAN_N = 3.0        # 阶跃幅度 ±3 N
C1_STEP_HOLD_S = 8.0
C1_SINE_BASE_N = 5.0        # 正弦基值（若 c1 起始目标差太多，调用方会用它自己的基值）
C1_SINE_AMP_N = 3.0
C1_SINE_FREQS_HZ = (0.1, 0.2, 0.3, 0.4, 0.5)
C1_SINE_MIN_S = 12.0
C1_SINE_CYCLES = 3.0
ANGLE_STEP_DEG = 5.0
ANGLE_HOLD_S = 6.0


def _sine_seconds(hz: float) -> float:
    """一档正弦跑多久：≥3 周期且 ≥12 s，向上取到 2 s 整数倍。"""
    s = max(C1_SINE_MIN_S, C1_SINE_CYCLES / max(1e-6, hz))
    return float(math.ceil(s / 2.0) * 2.0)


def stages():
    """完整序列：`[(name, kind, seconds, payload), ...]`。

    payload 含义：
      · hold / c1_step        → 相对基值的恒定量（N；hold 为 0）
      · c1_sine               → 频率 Hz
      · angle_step            → (axis, 相对基值的角度偏移)
    """
    out = [
        ("保持", KIND_HOLD, HOLD_S, 0.0),
        ("C1 阶跃上", KIND_C1_STEP, C1_STEP_HOLD_S, +C1_STEP_SPAN_N),
        ("C1 阶跃下", KIND_C1_STEP, C1_STEP_HOLD_S, -C1_STEP_SPAN_N),
    ]
    for hz in C1_SINE_FREQS_HZ:
        out.append((f"C1 正弦{hz:g}Hz", KIND_C1_SINE, _sine_seconds(hz), hz))
    out += [
        ("ROLL 阶跃", KIND_ANGLE_STEP, ANGLE_HOLD_S, ("roll", +ANGLE_STEP_DEG)),
        ("ROLL 回位", KIND_ANGLE_STEP, ANGLE_HOLD_S, ("roll", 0.0)),
        ("PITCH 阶跃", KIND_ANGLE_STEP, ANGLE_HOLD_S, ("pitch", +ANGLE_STEP_DEG)),
        ("PITCH 回位", KIND_ANGLE_STEP, ANGLE_HOLD_S, ("pitch", 0.0)),
    ]
    return out


def total_seconds() -> float:
    return sum(s[2] for s in stages())


def stage_count() -> int:
    return len(stages())


def command_at(t_s: float, *, c1_base_n: float,
               roll_base_deg: float = 0.0, pitch_base_deg: float = 0.0,
               c1_min: float = 0.5, c1_max: float = 25.0,
               angle_limit_deg: float = 25.0):
    """按已运行时间给出本拍的目标。

    Args:
        t_s: 从起环算起的秒数
        c1_base_n: C1 的基准张力（一般取界面上填的 `C1 目标 N`）
        roll_base_deg / pitch_base_deg: 角度基准（一般取界面目标角）
        c1_min / c1_max: C1 目标夹紧区间
        angle_limit_deg: 角度目标限幅（±）

    Returns:
        `(idx, name, kind, c1_n, roll_deg, pitch_deg, local_t)`；
        序列跑完返回 `(None, "", "", None, roll_base, pitch_base, 0.0)`。
    """
    if not math.isfinite(t_s) or t_s < 0.0:
        t_s = 0.0
    base_c1 = max(c1_min, min(c1_max, float(c1_base_n)))
    out_t0 = 0.0
    for idx, (name, kind, dur, payload) in enumerate(stages()):
        if t_s < out_t0 + dur:
            local = t_s - out_t0
            c1, roll, pitch = base_c1, float(roll_base_deg), float(pitch_base_deg)
            if kind == KIND_C1_STEP:
                c1 = base_c1 + float(payload)
            elif kind == KIND_C1_SINE:
                c1 = base_c1 + C1_SINE_AMP_N * math.sin(
                    2.0 * math.pi * float(payload) * local)
            elif kind == KIND_ANGLE_STEP:
                axis, delta = payload
                if axis == "roll":
                    roll = float(roll_base_deg) + float(delta)
                else:
                    pitch = float(pitch_base_deg) + float(delta)
            c1 = max(c1_min, min(c1_max, c1))
            lim = abs(float(angle_limit_deg))
            roll = max(-lim, min(lim, roll))
            pitch = max(-lim, min(lim, pitch))
            return idx, name, kind, c1, roll, pitch, local
        out_t0 += dur
    return None, "", "", None, float(roll_base_deg), float(pitch_base_deg), 0.0


def summary_text() -> str:
    parts = [f"{n}={d:g}s" for n, _k, d, _p in stages()]
    return (f"混合自动调参 {stage_count()} 档 / 共 {total_seconds():g}s："
            + "、".join(parts))


# ============================================================
# 指标：从 sine CSV 里按 stage 拆（C1 张力 / ROLL / PITCH 三路各自算）
# ============================================================

def _fit(t, y, hz):
    """单频最小二乘拟合 → (幅值, 相位 deg)。"""
    n = len(t)
    if n < 30:
        return 0.0, 0.0
    w = 2.0 * math.pi * hz
    my = sum(y) / n
    s_ss = s_cc = s_sc = s_ys = s_yc = 0.0
    for k in range(n):
        sn = math.sin(w * t[k])
        cs = math.cos(w * t[k])
        yv = y[k] - my
        s_ss += sn * sn
        s_cc += cs * cs
        s_sc += sn * cs
        s_ys += yv * sn
        s_yc += yv * cs
    det = s_ss * s_cc - s_sc * s_sc
    if abs(det) < 1e-12:
        return 0.0, 0.0
    a = (s_ys * s_cc - s_yc * s_sc) / det
    b = (s_yc * s_ss - s_ys * s_sc) / det
    return math.hypot(a, b), math.degrees(math.atan2(b, a))


def _stage_runs(stage_col):
    """把 stage 列切成连续段：`[(stage_id, [indices]), ...]`。"""
    runs = []
    cur_id, cur_idx = None, []
    for k, v in enumerate(stage_col):
        try:
            sid = int(v)
        except (TypeError, ValueError):
            sid = -1
        if sid != cur_id:
            if cur_idx:
                runs.append((cur_id, cur_idx))
            cur_id, cur_idx = sid, [k]
        else:
            cur_idx.append(k)
    if cur_idx:
        runs.append((cur_id, cur_idx))
    return runs


def metrics(data):
    """按档算指标。

    Returns:
        list[dict]，每档：
          {"stage": idx, "kind": str, "hz": float,
           "c1": {"overshoot","ss_err","ratio","lag_deg","ok"},
           "roll": {...}, "pitch": {...}}
        角度只在 `angle_step` 档给 `overshoot/ss_err`。
    """
    if not data or "stage" not in data:
        return []
    stage_col = data["stage"]
    kinds = data.get("kind") or [""] * len(stage_col)
    t_all = data.get("t_s") or []
    out = []
    seq = stages()
    for sid, idx in _stage_runs(stage_col):
        if len(idx) < 30 or sid < 0:
            continue
        kind = kinds[idx[0]] if idx else ""
        t0 = t_all[idx[0]]
        tt = [t_all[k] - t0 for k in idx]
        row = {"stage": sid, "kind": kind, "hz": 0.0,
               "c1": {}, "roll": {}, "pitch": {}}
        if sid < len(seq):
            _n, k2, _d, payload = seq[sid]
            if k2 == KIND_C1_SINE:
                row["hz"] = float(payload)

        # ---- C1 张力 ----
        try:
            tgt = [data["f1_tgt"][k] for k in idx]
            mea = [data["f1"][k] for k in idx]
        except KeyError:
            tgt = mea = []
        if tgt and mea:
            if kind == KIND_C1_STEP:
                y0, y1 = mea[0], sum(tgt) / len(tgt)
                span = y1 - y0
                if abs(span) < 0.2:
                    row["c1"] = {"ok": False, "overshoot": 0.0, "ss_err": 0.0}
                else:
                    d = 1.0 if span > 0 else -1.0
                    peak = max(d * v for v in mea) * d
                    tail = mea[int(len(mea) * 0.6):]
                    fin = sum(tail) / len(tail)
                    row["c1"] = {
                        "ok": True,
                        "overshoot": (peak - y1) / span * 100.0,
                        "ss_err": (fin - y1) / span * 100.0,
                        "t_settle": _settle_time(tt, mea, y1, abs(span) * 0.05),
                    }
            elif kind == KIND_C1_SINE and row["hz"] > 0:
                a_t, p_t = _fit(tt, tgt, row["hz"])
                a_m, p_m = _fit(tt, mea, row["hz"])
                row["c1"] = {
                    "ok": True,
                    "ratio": (a_m / a_t) if a_t > 1e-9 else 0.0,
                    "lag_deg": (p_t - p_m + 180.0) % 360.0 - 180.0,
                }

        # ---- 角度（ROLL / PITCH）----
        if kind == KIND_ANGLE_STEP:
            for key, mea_col, tgt_col in (("roll", "roll_deg", "roll_tgt_deg"),
                                          ("pitch", "pitch_deg", "pitch_tgt_deg")):
                try:
                    mea = [data[mea_col][k] for k in idx]
                    tgt = [data[tgt_col][k] for k in idx]
                except KeyError:
                    continue
                if not mea or not tgt:
                    continue
                y0, y1 = mea[0], sum(tgt) / len(tgt)
                span = y1 - y0
                if abs(span) < 0.2:
                    row[key] = {"ok": False, "overshoot": 0.0, "ss_err": 0.0}
                else:
                    d = 1.0 if span > 0 else -1.0
                    peak = max(d * v for v in mea) * d
                    tail = mea[int(len(mea) * 0.6):]
                    fin = sum(tail) / len(tail)
                    row[key] = {
                        "ok": True,
                        "overshoot": (peak - y1) / span * 100.0,
                        "ss_err": (fin - y1) / span * 100.0,
                        "t_settle": _settle_time(tt, mea, y1, abs(span) * 0.1),
                    }
        out.append(row)
    return out


def _settle_time(tt, yy, target, band):
    """最后一次离开 `±band` 的时间（秒）；没进过band返回 None。"""
    band = max(1e-6, float(band))
    last = None
    for t, y in zip(tt, yy):
        if abs(y - target) > band:
            last = t
    return last


# ============================================================
# 调参规则
# ============================================================

# C1 张力环的增益范围（与界面 ranges 对齐，留安全余量）
C1_BOUNDS = {
    "kp": (1.0, 200.0),
    "ki": (0.0, 200.0),
    "itl": (1.0, 300.0),
    "kd": (0.0, 2.0),
}
# 角度环只动 Kp / Ki（Kd 默认 0，不擅自引入微分噪声）
ANGLE_BOUNDS = {
    "kp": (0.02, 5.0),
    "ki": (0.0, 100.0),
}


def _clamp(v, bounds):
    return max(bounds[0], min(bounds[1], v))


def tune(metric_rows, gains, max_rounds_hit=False):
    """本轮指标 → 下一轮增益。

    Args:
        metric_rows: `metrics()` 的返回值
        gains: {"c1": {"kp","ki","itl","kd"}, "ang": {"kp","ki"}}
        max_rounds_hit: 轮数用完时只收敛不探索

    Returns:
        `(new_gains, notes, converged)`
    """
    c1 = dict(gains["c1"])
    ang = dict(gains["ang"])
    notes, converged = [], True

    # ---- C1 张力：阶跃超调 / 稳态差 + 0.3/0.5 Hz 幅值比 ----
    steps = [r for r in metric_rows if r["kind"] == KIND_C1_STEP and r["c1"].get("ok")]
    s03 = next((r["c1"] for r in metric_rows if r["kind"] == KIND_C1_SINE
                and abs(r["hz"] - 0.3) < 1e-6), {})
    s05 = next((r["c1"] for r in metric_rows if r["kind"] == KIND_C1_SINE
                and abs(r["hz"] - 0.5) < 1e-6), {})
    os_worst = max([abs(r["c1"].get("overshoot", 0.0)) for r in steps] or [0.0])
    ss_worst = max([abs(r["c1"].get("ss_err", 0.0)) for r in steps] or [0.0])
    r03 = float(s03.get("ratio", 1.0))
    r05 = float(s05.get("ratio", 1.0))

    kp0, ki0, itl0, kd0 = c1["kp"], c1["ki"], c1["itl"], c1["kd"]
    if os_worst > 50.0:
        c1["kp"] *= 0.80
        c1["kd"] = _clamp(c1["kd"] + 0.20, C1_BOUNDS["kd"])
    elif os_worst > 30.0:
        c1["kp"] *= 0.88
        c1["kd"] = _clamp(c1["kd"] + 0.10, C1_BOUNDS["kd"])
    elif os_worst < 12.0 and r03 < 0.92 and not max_rounds_hit:
        c1["kp"] *= 1.10
    if ss_worst > 6.0:
        c1["itl"] = _clamp(c1["itl"] * 1.4, C1_BOUNDS["itl"])
        if ss_worst > 10.0:
            c1["ki"] = _clamp(c1["ki"] * 1.15, C1_BOUNDS["ki"])
    elif ss_worst < 2.0 and c1["itl"] > 25.0:
        c1["itl"] = _clamp(c1["itl"] * 0.9, C1_BOUNDS["itl"])
    if c1["kd"] > 0.0 and os_worst < 12.0 and r05 < 0.85 and not max_rounds_hit:
        c1["kd"] = _clamp(c1["kd"] * 1.1, C1_BOUNDS["kd"])
    for k in ("kp", "ki", "itl", "kd"):
        c1[k] = _clamp(c1[k], C1_BOUNDS[k])
    if (abs(c1["kp"] - kp0) / max(1e-9, kp0) > 0.04
            or abs(c1["itl"] - itl0) / max(1e-9, itl0) > 0.08
            or abs(c1["kd"] - kd0) > 0.04):
        converged = False
    notes.append(
        f"C1: 超调{os_worst:+.0f}% 稳态{ss_worst:.0f}% r(0.3)={r03:.2f} r(0.5)={r05:.2f} → "
        f"kp {kp0:g}→{c1['kp']:g}, itl {itl0:g}→{c1['itl']:g}, kd {kd0:g}→{c1['kd']:g}")

    # ---- 角度环：只看角度阶跃的超调 ----
    ang_steps = [r for r in metric_rows if r["kind"] == KIND_ANGLE_STEP]
    os_a = []
    ss_a = []
    for r in ang_steps:
        for key in ("roll", "pitch"):
            rec = r.get(key) or {}
            if rec.get("ok"):
                os_a.append(abs(rec.get("overshoot", 0.0)))
                ss_a.append(abs(rec.get("ss_err", 0.0)))
    os_a_worst = max(os_a or [0.0])
    ss_a_worst = max(ss_a or [0.0])
    akp0, aki0 = ang["kp"], ang["ki"]
    if os_a_worst > 50.0:
        ang["kp"] *= 0.75
    elif os_a_worst > 25.0:
        ang["kp"] *= 0.88
    elif os_a_worst < 10.0 and not max_rounds_hit:
        ang["kp"] *= 1.10
    if ss_a_worst > 8.0:
        ang["ki"] = _clamp(ang["ki"] + 0.05, ANGLE_BOUNDS["ki"])
    for k in ("kp", "ki"):
        ang[k] = _clamp(ang[k], ANGLE_BOUNDS[k])
    if (abs(ang["kp"] - akp0) / max(1e-9, akp0) > 0.04
            or abs(ang["ki"] - aki0) > 1e-9):
        converged = False
    notes.append(
        f"角度: 超调{os_a_worst:+.0f}% 稳态{ss_a_worst:.0f}% → "
        f"kp {akp0:g}→{ang['kp']:g}, ki {aki0:g}→{ang['ki']:g}")
    return ({"c1": c1, "ang": ang}, notes, converged)


def fmt(values):
    """[1.2, 3] → "1.2,3"（写回输入框用）。"""
    out = []
    for v in values:
        out.append(f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v)))
    return ",".join(out)
