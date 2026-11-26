"""自动调参的**测试序列**（纯数学，无 Qt / 无 IO，可单测）。

用途（2026-11-24 用户要求）：一次起环就跑完全部工况，把每次的数据落盘，
事后离线算 PID 指标并给下一轮增益。三根缆**同步给同一个目标序列**
（共模），所以三套 PID 在完全相同的激励下比较 —— 这是能横向比的前提。

序列（总时长见 `total_seconds()`）：

    ① 阶跃上  1.5 → 5.5 N   保持 8 s      ← 看上升时间/超调
    ② 阶跃下  5.5 → 1.5 N   保持 8 s      ← 看回落/反向
    ③~⑦ 正弦  A=4、基值 5 N（范围 1~9，**最低 1 N**）
              f = 0.1 / 0.2 / 0.3 / 0.4 / 0.5 Hz
              各跑 ≥3 个整周期（0.1 Hz 用 30 s）

约束：
· 目标一律夹在 `[1.0, f_max]` 与 `[f_min, f_max]` 的交集里 —— 用户要求最低不低于 1 N；
· 正弦从相位 0 起算 ⟹ 起点 = 基值 5 N，**不会阶跃**；
· 阶跃是**故意**的阶跃（这正是要测的东西）。
"""

import math
import re

# 正弦的基值与幅度：基值 5、幅度 4 ⟹ 范围 1~9 N（最低 1 N，满足用户约束）
SINE_BASE_N = 5.0
SINE_AMP_N = 4.0
TARGET_MIN_N = 1.0          # 用户硬约束：目标最低不得低于 1 N

# 2026-11-25 用户定案：阶跃只是**辅助**（主项是正弦跟随，因为这是阻抗的内环），
# 幅度统一 **3 N**：预紧 5 N → 上阶跃 8 N → 下阶跃回 5 N（各 3 N）。
# 之前 5.5/1.5 那一版在预紧之后只有 0.5 N 跳变 → 百分比超调完全失真。
STEP_HIGH_N = 8.0
STEP_LOW_N = 5.0
STEP_SPAN_N = 3.0        # 两段阶跃的幅度（只用于文档/自检）
STEP_HOLD_S = 8.0

# 每档正弦：≥3 个整周期，且至少 12 s（太短拟合不可靠）
SINE_FREQS_HZ = (0.1, 0.2, 0.3, 0.4, 0.5)
SINE_MIN_S = 12.0
SINE_CYCLES = 3.0

KIND_STEP = "step"
KIND_SINE = "sine"
KIND_PRE = "preload"

# 序列开头先**预紧**一段：现场起环时三缆常在 0.0~0.3 N（松绳状态），
# 直接上第一个阶跃的话，前 1~7 s 全在"收绳消除余量"，t90 会被这段吃满
# （2026-11-25 实测 C1 的 t90=6.48 s，其实是松绳收线时间，不是环路响应）。
# 2026-11-25 实测：起环时三缆余量极大 —— 预紧档 5 s @3 N 只走了 ~2500 counts
# （≈21 mm 绳长）张力仍为 0，直到阶跃档 1.5 s 后才开始上升。
# 伺服实际速度 ≈ 13.35×领先量（e=3 N、kp=12 → 领先 36 counts → ~480 c/s），
# 所以**必须给够时间**，并且 `max_trim` 不能被 3000 夹住（否则永远收不完）。
PRELOAD_N = 5.0
PRELOAD_S = 12.0


def _sine_seconds(hz: float) -> float:
    """一档正弦要跑多久：≥3 周期且 ≥12 s，向上取到 2 s 的整数倍。"""
    s = max(SINE_MIN_S, SINE_CYCLES / max(1e-6, hz))
    return float(math.ceil(s / 2.0) * 2.0)


def stages():
    """完整序列：`[(name, kind, seconds, payload), ...]`。

    `payload`：step 为恒定目标张力 [N]；sine 为频率 [Hz]。
    """
    out = [
        ("预紧", KIND_PRE, PRELOAD_S, PRELOAD_N),
        ("阶跃上", KIND_STEP, STEP_HOLD_S, STEP_HIGH_N),
        ("阶跃下", KIND_STEP, STEP_HOLD_S, STEP_LOW_N),
    ]
    for hz in SINE_FREQS_HZ:
        out.append((f"正弦{hz:g}Hz", KIND_SINE, _sine_seconds(hz), hz))
    return out


def total_seconds() -> float:
    return sum(s[2] for s in stages())


def command_at(t_s: float, f_min: float = 0.3, f_max: float = 30.0):
    """按已运行时间 `t_s` 给出本拍的三缆目标张力。

    Args:
        t_s: 从"起环"算起的秒数
        f_min / f_max: 张力界（用于夹紧；同时强制 ≥ `TARGET_MIN_N`）

    Returns:
        `(stage_index, stage_name, kind, targets, local_t)`；序列跑完返回
        `(None, "", "", None, 0.0)` —— 调用方据此正常停环。
    """
    if not math.isfinite(t_s) or t_s < 0.0:
        t_s = 0.0
    t0 = 0.0
    for idx, (name, kind, dur, payload) in enumerate(stages()):
        if t_s < t0 + dur:
            local = t_s - t0
            if kind in (KIND_STEP, KIND_PRE):
                v = float(payload)
            else:
                hz = float(payload)
                v = SINE_BASE_N + SINE_AMP_N * math.sin(
                    2.0 * math.pi * hz * local)
            v = max(TARGET_MIN_N, f_min, min(f_max, v))
            return idx, name, kind, [v, v, v], local
        t0 += dur
    return None, "", "", None, 0.0


def stage_count() -> int:
    return len(stages())


def summary_text() -> str:
    """一行摘要（给状态行/日志）。"""
    parts = [f"{n}={d:g}s" for n, _k, d, _p in stages()]
    return (f"自动调参 {stage_count()} 档 / 共 {total_seconds():g}s："
            + "、".join(parts))


# ============================================================
# 自动迭代：从本轮数据算指标 → 出下一轮增益（2026-11-25 用户要求）
# ============================================================

def read_csv(path):
    """读 `run_data/sine/*.csv` → (meta, data)；data 是 dict[str, list]。

    只依赖标准库（控制线程里也能调用），缺 stage/kind 列时退化为单档。
    """
    import csv as _csv
    hdr, rows = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                hdr.append(line[1:].strip())
            elif line.strip():
                rows.append(line.rstrip("\n"))
    if len(rows) < 20:
        return None, None
    head = rows[0].split(",")
    ncol = len(head)
    data = {h: [] for h in head}
    for r in rows[1:]:
        parts = r.split(",")
        if len(parts) < ncol:
            continue
        for i, h in enumerate(head):
            if h in ("stage", "kind"):
                data[h].append(parts[i])
            else:
                try:
                    data[h].append(float(parts[i]))
                except ValueError:
                    data[h].append(float("nan"))
    meta = {"header": " ".join(hdr)}
    import re as _re
    for key, pat in (("kp", r"kp_f=([-\d.,]+)"), ("ki", r"ki_f=([-\d.,]+)"),
                     ("kd", r"kd_f=([-\d.,]+)"),
                     ("itl", r"i_term_lim=([-\d.,]+)")):
        m = _re.search(pat, meta["header"])
        meta[key] = m.group(1) if m else "?"
    return meta, data


def _num(txt, i, default=0.0):
    """从 "12,20,23" 这类文本里取第 i 个值。"""
    try:
        vals = [float(v) for v in str(txt).replace("，", ",").split(",")]
    except (TypeError, ValueError):
        return default
    if len(vals) == 1:
        return vals[0]
    return vals[i] if i < len(vals) else default


def _fit(t, y, hz):
    """正弦拟合（最小二乘，单频）：返回 (幅值, 相位deg)。"""
    import math as _m
    w = 2.0 * _m.pi * hz
    n = len(t)
    if n < 30:
        return 0.0, 0.0
    mt = sum(t) / n
    my = sum(y) / n
    s_sin = s_cos = s_ss = s_cc = s_sc = s_ys = s_yc = 0.0
    for k in range(n):
        sn = _m.sin(w * t[k]); cs = _m.cos(w * t[k]); yv = y[k] - my
        s_sin += sn; s_cos += cs
        s_ss += sn * sn; s_cc += cs * cs; s_sc += sn * cs
        s_ys += yv * sn; s_yc += yv * cs
    det = s_ss * s_cc - s_sc * s_sc
    if abs(det) < 1e-12:
        return 0.0, 0.0
    a = (s_ys * s_cc - s_yc * s_sc) / det
    b = (s_yc * s_ss - s_ys * s_sc) / det
    return _m.hypot(a, b), _m.degrees(_m.atan2(b, a))


def metrics(data, f_target_hz=None):
    """按档算指标：阶跃给超调/稳态差，正弦给幅值比/滞后。

    Returns:
        list[dict]：每档 {"stage","kind","hz","cables":[{...}]}
    """
    st = data.get("stage") or []
    kinds = data.get("kind") or []
    stages = []
    seen = []
    for v in st:
        s = int(v) if str(v).lstrip("-").isdigit() else -1
        if s not in seen:
            seen.append(s)
    for s in seen:
        idx = [k for k, v in enumerate(st)
               if (int(v) if str(v).lstrip("-").isdigit() else -1) == s]
        if len(idx) < 30:
            continue
        kind = kinds[idx[0]] if kinds else "sine"
        if kind == "preload":
            continue
        t = [data["t_s"][k] - data["t_s"][idx[0]] for k in idx]
        row = {"stage": s, "kind": kind, "cables": []}
        hz = 0.0
        if s >= 0 and s < len(stages_of()):
            name, k2, _d, payload = stages_of()[s]
            if k2 == KIND_SINE:
                hz = float(payload)
        row["hz"] = hz
        for ci in range(3):
            tgt = [data["f%d_tgt" % (ci + 1)][k] for k in idx]
            mea = [data["f%d" % (ci + 1)][k] for k in idx]
            rec = {"cable": ci + 1}
            if kind == "step":
                y0, y1 = mea[0], sum(tgt) / len(tgt)
                span = y1 - y0
                if abs(span) < 0.2:
                    rec.update(overshoot=0.0, ss_err=0.0, ok=False)
                else:
                    d = 1.0 if span > 0 else -1.0
                    peak = max(d * v for v in mea) * d
                    tail = mea[int(len(mea) * 0.6):]
                    fin = sum(tail) / len(tail)
                    rec.update(
                        overshoot=(peak - y1) / span * 100.0,
                        ss_err=(fin - y1) / span * 100.0, ok=True)
            elif kind == "sine" and hz > 0:
                a_t, p_t = _fit(t, tgt, hz)
                a_m, p_m = _fit(t, mea, hz)
                lag = (p_t - p_m + 180.0) % 360.0 - 180.0
                rec.update(ratio=(a_m / a_t) if a_t > 1e-9 else 0.0,
                           lag_deg=lag, ok=True)
            row["cables"].append(rec)
        stages.append(row)
    return stages


def stages_of():
    return stages()


# ---- 增益的允许范围 ----
BOUNDS = {
    "kp": (6.0, 40.0),
    "ki": (0.0, 40.0),
    "itl": (10.0, 80.0),
    "kd": (0.0, 0.30),
}


def _clamp(v, key):
    lo, hi = BOUNDS[key]
    return max(lo, min(hi, v))


def _pick(stages, kind, hz=None):
    """从指标里挑出某类档（阶跃/某频率正弦）。"""
    out = []
    for r in stages:
        if r["kind"] != kind:
            continue
        if hz is not None and abs(r.get("hz", 0.0) - hz) > 1e-6:
            continue
        out.append(r)
    return out


def tune(stage_metrics, gains, max_rounds_hit=False):
    """**规则式自动调参**：本轮指标 → 下一轮增益（三缆各自独立）。

    Args:
        stage_metrics: `metrics()` 的返回值
        gains: `{"kp": [..3], "ki": [..3], "itl": [..3], "kd": [..3]}`
        max_rounds_hit: 轮数用完时只收敛不探索

    Returns:
        `(new_gains, notes, converged)`
        notes: 每缆一行说明（给状态行/日志）
    """
    kp = list(gains["kp"]); ki = list(gains["ki"])
    itl = list(gains["itl"]); kd = list(gains["kd"])
    notes, converged = [], True

    steps = _pick(stage_metrics, "step")
    s03 = _pick(stage_metrics, "sine", 0.3)
    s05 = _pick(stage_metrics, "sine", 0.5)

    for i in range(3):
        os_up = next((c.get("overshoot", 0.0) for r in steps[:1]
                      for c in r["cables"] if c["cable"] == i + 1), 0.0)
        os_dn = next((c.get("overshoot", 0.0) for r in steps[1:2]
                      for c in r["cables"] if c["cable"] == i + 1), 0.0)
        ss_up = next((abs(c.get("ss_err", 0.0)) for r in steps[:1]
                      for c in r["cables"] if c["cable"] == i + 1), 0.0)
        ss_dn = next((abs(c.get("ss_err", 0.0)) for r in steps[1:2]
                      for c in r["cables"] if c["cable"] == i + 1), 0.0)
        r03 = next((c.get("ratio", 1.0) for r in s03
                    for c in r["cables"] if c["cable"] == i + 1), 1.0)
        r05 = next((c.get("ratio", 1.0) for r in s05
                    for c in r["cables"] if c["cable"] == i + 1), 1.0)
        os_worst = max(os_up, os_dn)
        ss_worst = max(ss_up, ss_dn)
        kp0, kd0, itl0 = kp[i], kd[i], itl[i]

        # ① 超调：优先动 Kp，再补一点 D
        if os_worst > 50.0:
            kp[i] *= 0.80
            kd[i] = _clamp(kd[i] + 0.04, "kd")
        elif os_worst > 30.0:
            kp[i] *= 0.88
            kd[i] = _clamp(kd[i] + 0.02, "kd")
        elif os_worst < 12.0 and r03 < 0.92 and not max_rounds_hit:
            kp[i] *= 1.10            # 稳但追不上 → 提速
        # ② 稳态：给积分更多权限
        if ss_worst > 6.0:
            itl[i] = _clamp(itl[i] * 1.4, "itl")
            if ss_worst > 10.0:
                ki[i] = _clamp(ki[i] * 1.15, "ki")
        elif ss_worst < 2.0 and itl[i] > 25.0:
            itl[i] = _clamp(itl[i] * 0.9, "itl")
        # ③ 已经稳了还想更稳 → 轻推 D（只在不许提速时才探索）
        if kd[i] > 0.0 and os_worst < 12.0 and r05 < 0.85 and not max_rounds_hit:
            kd[i] = _clamp(kd[i] * 1.1, "kd")

        kp[i] = _clamp(kp[i], "kp")
        ki[i] = _clamp(ki[i], "ki")
        itl[i] = _clamp(itl[i], "itl")

        d_kp = abs(kp[i] - kp0) / max(1e-9, kp0)
        d_itl = abs(itl[i] - itl0) / max(1e-9, itl0)
        d_kd = abs(kd[i] - kd0)
        if d_kp > 0.04 or d_itl > 0.08 or d_kd > 0.008:
            converged = False
        notes.append(
            f"C{i+1}: 超调{os_worst:+.0f}% 稳态{ss_worst:.0f}% "
            f"r(0.3)={r03:.2f} r(0.5)={r05:.2f} → "
            f"kp {kp0:g}→{kp[i]:g}, itl {itl0:g}→{itl[i]:g}, "
            f"kd {kd0:g}→{kd[i]:g}")
    return ({"kp": kp, "ki": ki, "itl": itl, "kd": kd}, notes, converged)


def fmt(values):
    """[12, 20, 23] → "12,20,23"（写回输入框用；整数不带小数点）。"""
    out = []
    for v in values:
        out.append(f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v)))
    return ",".join(out)
