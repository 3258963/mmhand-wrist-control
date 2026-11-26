"""自动调参数据分析：把 `run_data/sine/*.csv`（带 stage/kind 列）算成 PID 指标。

用法：
    python tools/analyze_autotune.py                 # 读最新一个文件
    python tools/analyze_autotune.py <csv> [...]     # 读指定文件

输出：
    · 阶跃档：上升时间、超调、稳态误差、稳定时间
    · 正弦档：幅值比、相位滞后（度 & 毫秒）、RMS 误差
    · 每缆一条**调参建议**（比例/积分/微分该往哪走）

设计原则：只读数据、只给建议，不改参数（参数由人决定）。
"""

from __future__ import annotations

import csv
import math
import os
import re
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINE_DIR = os.path.join(REPO, "run_data", "sine")


def load(path):
    """返回 (meta, data)；meta 从 `#` 注释行解析，data 是 dict[str, ndarray]。"""
    hdr, rows = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#"):
                hdr.append(line[1:].strip())
            elif line.strip():
                rows.append(line.strip())
    if len(rows) < 3:
        return None, None
    head = rows[0].split(",")
    body = np.array([[float(v) if v not in ("", "nan") else float("nan")
                      for v in r.split(",")[:len(head) - 2]] for r in rows[1:]])
    data = {name: body[:, i] for i, name in enumerate(head[:len(head) - 2])}
    # stage / kind 两列是文本
    try:
        data["stage"] = np.array([int(r.split(",")[head.index("stage")])
                                  for r in rows[1:]])
        data["kind"] = np.array([r.split(",")[head.index("kind")]
                                 for r in rows[1:]])
    except (ValueError, IndexError):
        data["stage"] = np.full(len(body), -1)
        data["kind"] = np.array([""] * len(body))
    meta = {"header": hdr}
    text = " ".join(hdr)
    for key, pat in (("amp", r"幅度A=([\d.]+)"), ("hz", r"频率f=([\d.]+)"),
                     ("kp", r"kp_f=([-\d.,]+)"), ("ki", r"ki_f=([-\d.,]+)"),
                     ("kd", r"kd_f=([-\d.,]+)"),
                     ("itl", r"i_term_lim=([-\d.,]+)"),
                     ("mst", r"max_step_f=([-\d.,]+)"),
                     ("fmin", r"f_min=([-\d.]+)"), ("fmax", r"fmax_f=([-\d.]+)")):
        m = re.search(pat, text)
        meta[key] = m.group(1) if m else "?"
    return meta, data


def fit_sine(t, y, hz):
    w = 2 * math.pi * hz
    A = np.column_stack([np.ones_like(t), np.sin(w * t), np.cos(w * t)])
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    return c[0], math.hypot(c[1], c[2]), math.degrees(math.atan2(c[2], c[1]))


def step_metrics(t, y, t0, y_lo, y_hi):
    """阶跃指标（相对该档起点 t0 的局部时间）。"""
    m = t >= t0
    tt, yy = t[m] - t0, y[m]
    if len(tt) < 20:
        return None
    span = y_hi - y_lo
    d = 1.0 if y_hi > y_lo else -1.0
    final = float(np.median(yy[tt > tt[-1] * 0.6]))
    # 上升时间：10% → 90%
    lo_th = y_lo + 0.1 * span
    hi_th = y_lo + 0.9 * span
    def cross(th):
        idx = np.where((d * (yy - th)) >= 0)[0]
        return float(tt[idx[0]]) if len(idx) else float("nan")
    t10, t90 = cross(lo_th), cross(hi_th)
    peak = float(np.max(d * yy)) * d
    overshoot = (peak - y_hi) / span * 100.0 if span else float("nan")
    ss_err = (final - y_hi) / span * 100.0 if span else float("nan")
    return dict(t90=t90, t10=t10, rise=(t90 - t10), overshoot=overshoot,
                ss_err=ss_err, final=final)


def analyze(meta, data):
    t = data["t_s"]
    out = []
    stages = sorted(set(int(s) for s in data["stage"] if s >= 0))
    if not stages:                       # 旧文件（无 stage 列）：整段当正弦
        stages = [-1]
    for st in stages:
        m = data["stage"] == st
        if m.sum() < 30:
            continue
        kind = data["kind"][m][0] if "kind" in data else "sine"
        if kind == "preload":        # 预紧档只用来收绳，不做指标
            continue
        tt = t[m] - t[m][0]
        row = {"stage": st, "kind": kind, "n": int(m.sum()), "cables": []}
        for i in range(3):
            tg = data[f"f{i+1}_tgt"][m]
            me = data[f"f{i+1}"][m]
            rec = {"cable": i + 1}
            if kind == "step":
                # 阶跃档的目标在本档内是**常数**，所以起止必须取
                # "首拍实测 → 目标"，不能用目标的首末值（那样 span=0 → nan）。
                y0 = float(me[0])
                y1 = float(np.median(tg))
                met = step_metrics(tt, me, 0.0, y0, y1)
                rec.update(met or {})
            else:
                hz = float(meta.get("hz") or 0.5)
                if st >= 0:
                    hm = re.search(r"正弦([\d.]+)Hz", "?")
                    hz = _stage_hz(st, meta)
                c_t, a_t, p_t = fit_sine(tt, tg, hz)
                c_m, a_m, p_m = fit_sine(tt, me, hz)
                lag = (p_t - p_m + 180) % 360 - 180
                rec.update(hz=hz, ratio=a_m / a_t if a_t > 1e-9 else float("nan"),
                           lag_deg=lag, lag_ms=lag / 360.0 / hz * 1000.0,
                           rms=float(np.sqrt(np.mean((tg - me) ** 2))),
                           dc=float(c_m - c_t))
            row["cables"].append(rec)
        out.append(row)
    return out


def _stage_hz(stage_index, meta):
    """从 `wrist_autotune` 的序列反查该档频率（stage 0/1 是阶跃）。"""
    try:
        sys.path.insert(0, REPO)
        import wrist_autotune as at
        st = at.stages()
        if 0 <= stage_index < len(st):
            name, kind, _dur, payload = st[stage_index]
            return float(payload) if kind == at.KIND_SINE else 0.0
    except Exception:
        pass
    return float(meta.get("hz") or 0.5)


def advice(rec, kind):
    """单缆调参建议（保守、只动一个量级）。"""
    if kind == "step":
        os_, ss = rec.get("overshoot", 0.0), rec.get("ss_err", 0.0)
        if not math.isfinite(os_):
            return "数据不足"
        if os_ > 25:
            return "超调大 → Kp 降 25%，或加 Kd（0.1~0.3）"
        if os_ < 5 and abs(ss) > 5:
            return "无超调但不到目标 → Ki 加倍（或提积分上限）"
        if abs(ss) > 5:
            return "稳态偏低 → 提 Ki / 积分上限"
        return "阶跃良好"
    ratio, lag = rec.get("ratio", float("nan")), rec.get("lag_deg", float("nan"))
    if not math.isfinite(ratio):
        return "数据不足"
    if ratio < 0.7:
        return f"幅值仅 {ratio:.2f} → Kp 提到 1.6×（带宽不足）"
    if ratio > 1.2:
        return f"幅值 {ratio:.2f} 过冲 → Kp 降 25%"
    if abs(lag) > 45:
        return f"滞后 {lag:.0f}° → 提 Kp 20% 或加 Kd"
    if abs(rec.get("dc", 0.0)) > 0.3:
        return f"有 {rec['dc']:+.2f} N 直流偏差 → 提 Ki"
    return "跟随良好"


def main(argv):
    paths = argv[1:]
    if not paths:
        cand = [os.path.join(SINE_DIR, f) for f in os.listdir(SINE_DIR)
                if f.endswith(".csv")] if os.path.isdir(SINE_DIR) else []
        if not cand:
            print("没有找到 run_data/sine/*.csv")
            return 1
        paths = [max(cand, key=os.path.getmtime)]
    for path in paths:
        meta, data = load(path)
        if meta is None:
            print(f"{os.path.basename(path)}: 数据太少")
            continue
        print("=" * 78)
        print(os.path.basename(path))
        print(f"  参数: kp={meta['kp']} ki={meta['ki']} kd={meta['kd']} "
              f"itl={meta['itl']} max_step={meta['mst']} "
              f"A={meta['amp']} f={meta['hz']}")
        for row in analyze(meta, data):
            tag = "阶跃" if row["kind"] == "step" else "正弦"
            print(f"\n  档 {row['stage']} [{tag}]  {row['n']} 点")
            for rec in row["cables"]:
                c = rec["cable"]
                if row["kind"] == "step":
                    print(f"    C{c}: t90={rec.get('t90', float('nan')):.2f}s "
                          f"超调={rec.get('overshoot', float('nan')):+.0f}% "
                          f"稳态差={rec.get('ss_err', float('nan')):+.0f}%  "
                          f"→ {advice(rec, 'step')}")
                else:
                    print(f"    C{c}: 幅值比={rec.get('ratio', float('nan')):.2f} "
                          f"滞后={rec.get('lag_deg', float('nan')):+.0f}° "
                          f"({rec.get('lag_ms', float('nan')):+.0f} ms) "
                          f"RMS={rec.get('rms', float('nan')):.2f}N  "
                          f"→ {advice(rec, 'sine')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
