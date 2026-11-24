"""Analyze batch test CSV files (test_*.csv): step metrics + amplitude ratios."""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FREQS = [0.05, 0.1, 0.2, 0.25]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXP = os.path.join(ROOT, "run_data", "scope_exports")


def load(path):
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    d = {k: i for i, k in enumerate(rows[0])}
    T = np.array([float(r[d["t_s"]]) for r in rows[1:]])
    def c(k):
        return np.array([float(r[d[k]]) for r in rows[1:]])
    return T, c("roll_deg"), c("pitch_deg"), c("tgt_roll_deg"), c("tgt_pitch_deg")


def plateaus(T, rt, pt):
    start = 0
    out = []
    for i in range(1, len(rt)):
        if abs(rt[i] - rt[i - 1]) > 0.05:
            if T[i - 1] - T[start] > 3:
                out.append((T[start], T[i - 1], rt[start], pt[start]))
            start = i
    if T[-1] - T[start] > 3:
        out.append((T[start], T[-1], rt[start], pt[start]))
    return out


def amp(x, t, f):
    w = 2 * math.pi * f
    M = np.column_stack([np.ones(len(t)), np.sin(w * t), np.cos(w * t)])
    ca, *_ = np.linalg.lstsq(M, x, rcond=None)
    return math.hypot(ca[1], ca[2])


def analyse(path):
    T, roll, pitch, rt, pt = load(path)
    plats = plateaus(T, rt, pt)
    res = {"file": os.path.basename(path), "steps": [], "sine": {}}
    for a, b, vr, vp in plats:
        s = (T >= b - 2.0) & (T <= b)
        seg = (T >= a) & (T <= b)
        if s.sum() < 5:
            continue
        res["steps"].append({
            "tgt_roll": float(vr), "tgt_pitch": float(vp),
            "settle_roll": float(roll[s].mean()), "settle_pitch": float(pitch[s].mean()),
            "peak_roll": float(roll[seg].max()), "min_roll": float(roll[seg].min()),
            "peak_pitch": float(pitch[seg].max()), "min_pitch": float(pitch[seg].min()),
        })
    if len(plats) >= 3:
        t_sine = plats[2][1]
        for k, f in enumerate(FREQS):
            a = t_sine + k * 20.0 + 2.0
            b = a + 17.0
            s = (T >= a) & (T <= b)
            if s.sum() < 100:
                continue
            t = T[s]
            tr, ar = amp(rt[s], t, f), amp(roll[s], t, f)
            tp, ap = amp(pt[s], t, f), amp(pitch[s], t, f)
            res["sine"][str(f)] = {
                "roll": round(ar / max(tr, 1e-9), 2),
                "pitch": round(ap / max(tp, 1e-9), 2),
            }
    return res


def main():
    files = sorted(glob.glob(os.path.join(EXP, "test_*.csv")))
    if not files:
        print("no test_*.csv")
        return 1
    results = [analyse(f) for f in files]
    json.dump(results, open(os.path.join(EXP, "batch_results.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"{'config':32s} {'0.05':>12s} {'0.1':>12s} {'0.2':>12s} {'0.25':>12s}  step(roll)")
    for r in results:
        tag = r["file"][5:-4]
        ratios = []
        for f in FREQS:
            v = r["sine"].get(str(f), {})
            ratios.append(f"{v.get('roll', 0):.2f}/{v.get('pitch', 0):.2f}")
        steps = [s for s in r["steps"] if abs(s["tgt_roll"]) > 1]
        step_txt = ""
        if steps:
            s = steps[0]
            step_txt = (f"+{s['tgt_roll']:.0f}: {s['settle_roll']:.2f} "
                        f"(peak {s['peak_roll']:.2f})")
        print(f"{tag:32s} " + " ".join(f"{x:>12s}" for x in ratios) + f"  {step_txt}")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for r in results:
        tag = r["file"][5:-4]
        for ax, key in ((axes[0], "roll"), (axes[1], "pitch")):
            xs, ys = [], []
            for f in FREQS:
                v = r["sine"].get(str(f))
                if v:
                    xs.append(f); ys.append(v[key])
            if xs:
                ax.semilogx(xs, ys, "o-", lw=1.0, ms=4, label=tag)
    for ax, name in zip(axes, ("ROLL", "PITCH")):
        ax.axhline(0.707, color="r", ls=":", lw=1)
        ax.axhline(1.0, color="0.8", lw=0.8)
        ax.set_title(f"{name} amplitude ratio")
        ax.set_xlabel("frequency (Hz)")
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel("actual / target")
    axes[0].legend(fontsize=6)
    fig.suptitle("Batch comparison")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(EXP, "analysis_batch.png")
    fig.savefig(out, dpi=100)
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
