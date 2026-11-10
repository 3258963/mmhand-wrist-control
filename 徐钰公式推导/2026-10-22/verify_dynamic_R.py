# -*- coding: utf-8 -*-
"""Independent verification / solve for the two-axis cable wrist dynamic R matrix.

Data source: current CAD handoff (2026-10-21, C2/C3 P03/P04 corrected).
Routes compared:
  A. 5-constant planar projection model (firmware form)
  B. 3D rigid-body FK + vector chain-rule Jacobian (independent of A)
  C. alpha/beta/gamma closed form
  D. CAD 0.2-deg central-difference table
  E. float32 simulation vs double

Outputs: out/verify_summary.json, out/*.csv, out/*.png
"""
import csv
import json
import math
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "复核数据_extracted" / "复核数据"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)

CABLE = ("C1", "C2", "C3")
AXES = ("roll", "pitch")
DEG = math.pi / 180.0


# ---------------------------------------------------------------- data loading
def load_model():
    dc = json.loads((ROOT.parent / "H7_腕部R实时算法_20261022" / "H7_腕部R实时算法_20261022"
                     / "data" / "derived_constants.json").read_text(encoding="utf-8"))
    seg = {}
    for s in dc["segments"]:
        seg[(s["axis"], s["cable"])] = {
            "proj": tuple(float(v) for v in s["plane_coefficients_m"]),
            "abc": tuple(float(v) for v in s["alpha_beta_gamma_m2"]),
        }
    mp = json.loads((DATA / "model_parameters.json").read_text(encoding="utf-8"))
    return dc, seg, mp


def load_points(mp):
    pts = {}
    for p in mp["points"]:
        pts[p["id"]] = {
            "body": p["body"],
            "cable": p["cable"],
            "order": p["order"],
            "p0": np.array(p["zero_model_m"], dtype=float) * 1000.0,  # m -> mm
        }
    return pts


# ---------------------------------------------------------------- route B: 3D
ORIGIN_ROLL = np.array([0.0, 0.0, 0.0])
DIR_ROLL = np.array([0.0, 1.0, 0.0])
ORIGIN_PITCH0 = np.array([0.0, 0.0, 24.0])
DIR_PITCH0 = np.array([1.0, 0.0, 0.0])


def rot_x(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def rot_y(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def fk(points, roll, pitch):
    """World/model-frame positions (mm) at (roll,pitch) radians."""
    rp = rot_y(roll)
    rx = rot_x(pitch)
    out = {}
    for pid, p in points.items():
        p0 = p["p0"]
        v = p0
        if p["body"] == "palm":
            v = ORIGIN_PITCH0 + rx @ (v - ORIGIN_PITCH0)
        if p["body"] != "base":
            v = rp @ v
        out[pid] = v
    return out


def r_3d(points, roll, pitch):
    """2x3 R (mm) from vector chain rule; independent of planar constants."""
    pos = fk(points, roll, pitch)
    rp = rot_y(roll)
    a_p = rp @ DIR_PITCH0
    o_p = rp @ ORIGIN_PITCH0
    dpos = {}
    for pid, p in points.items():
        dr = np.cross(DIR_ROLL, pos[pid]) if p["body"] != "base" else np.zeros(3)
        dp = np.cross(a_p, pos[pid] - o_p) if p["body"] == "palm" else np.zeros(3)
        dpos[pid] = (dr, dp)

    R = np.zeros((2, 3))
    for ci in range(1, 4):
        ids = [f"C{ci}-P{k:02d}" for k in range(1, 9)]
        for k in range(7):
            d = pos[ids[k + 1]] - pos[ids[k]]
            u = d / np.linalg.norm(d)
            for j in range(2):
                R[j, ci - 1] -= float(u @ (dpos[ids[k + 1]][j] - dpos[ids[k]][j]))
    return R, pos


def lengths_3d(points, roll, pitch):
    pos = fk(points, roll, pitch)
    out = []
    for ci in range(1, 4):
        ids = [f"C{ci}-P{k:02d}" for k in range(1, 9)]
        out.append(sum(float(np.linalg.norm(pos[ids[k + 1]] - pos[ids[k]])) for k in range(7)))
    return np.array(out)


# ---------------------------------------------------------------- route A/C
def seg_eval(seg, axis, cable, theta):
    u1, u2, v1, v2, h = seg[(axis, cable)]["proj"]
    c, s = math.cos(theta), math.sin(theta)
    vp1 = v1 * c - v2 * s
    vp2 = v1 * s + v2 * c
    d1 = vp1 - u1
    d2 = vp2 - u2
    s_len = math.sqrt(d1 * d1 + d2 * d2 + h * h)
    r = (d1 * vp2 - d2 * vp1) / s_len
    return s_len, r


def model_R(seg, roll, pitch):
    R = np.zeros((2, 3))
    for j, th in enumerate((roll, pitch)):
        for i in range(3):
            R[j, i] = seg_eval(seg, AXES[j], CABLE[i], th)[1]
    return R


def model_lengths(seg, roll, pitch, const):
    out = np.zeros(3)
    for i in range(3):
        out[i] = (const[i] + seg_eval(seg, "roll", CABLE[i], roll)[0]
                  + seg_eval(seg, "pitch", CABLE[i], pitch)[0])
    return out


def abc_eval(seg, axis, cable, theta):
    a2, b, g = seg[(axis, cable)]["abc"]
    c, s = math.cos(theta), math.sin(theta)
    s_len = math.sqrt(a2 + b * c + g * s)
    r = (b * s - g * c) / (2.0 * s_len)
    return s_len, r


def abc_R(seg, roll, pitch):
    R = np.zeros((2, 3))
    for j, th in enumerate((roll, pitch)):
        for i in range(3):
            R[j, i] = abc_eval(seg, AXES[j], CABLE[i], th)[1]
    return R


def geometry_table(seg):
    rows = []
    for axis in AXES:
        for cable in CABLE:
            u1, u2, v1, v2, h = seg[(axis, cable)]["proj"]
            a = math.hypot(u1, u2)
            b = math.hypot(v1, v2)
            ca = (u1 * v1 + u2 * v2) / (a * b)
            sa = (u1 * v2 - u2 * v1) / (a * b)
            delta = math.atan2(sa, ca)
            alpha = a * a + b * b + h * h
            beta = -2 * a * b * ca
            gamma = 2 * a * b * sa
            rows.append(dict(axis=axis, cable=cable, u1=u1, u2=u2, v1=v1, v2=v2, h=h,
                             a=a, b=b, delta_deg=delta / DEG,
                             alpha=alpha, beta=beta, gamma=gamma,
                             r0=(beta * 0 - gamma * 1) / (2 * math.sqrt(alpha + beta))))
    return rows


# ---------------------------------------------------------------- float32
def f32(x):
    return np.float32(x)


def seg_eval_f32(seg, axis, cable, theta):
    u1, u2, v1, v2, h = (f32(v) for v in seg[(axis, cable)]["proj"])
    th = f32(theta)
    c, s = np.cos(th), np.sin(th)
    vp1 = v1 * c - v2 * s
    vp2 = v1 * s + v2 * c
    d1 = vp1 - u1
    d2 = vp2 - u2
    s_len = np.sqrt(d1 * d1 + d2 * d2 + h * h)
    r = (d1 * vp2 - d2 * vp1) / s_len
    return np.float32(s_len), np.float32(r)


def model_R_f32(seg, roll, pitch):
    R = np.zeros((2, 3), dtype=np.float32)
    for j, th in enumerate((f32(roll), f32(pitch))):
        for i in range(3):
            R[j, i] = seg_eval_f32(seg, AXES[j], CABLE[i], th)[1]
    return R


# ---------------------------------------------------------------- matrix utils
def null_vector(R):
    a = R[0] / np.linalg.norm(R[0])
    b = R[1] / np.linalg.norm(R[1])
    w = np.cross(a, b)
    nw = np.linalg.norm(w)
    if nw <= 1e-12:
        return None, 0.0
    n = w / nw
    if n.sum() < 0:
        n = -n
    return n, nw


def condition(R):
    sv = np.linalg.svd(R, compute_uv=False)
    return float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf")


def tension_solve(R, tau, fmin, fmax):
    """min-norm particular solution + nullspace preload, box constrained.

    Returns dict with feasible flag, f, t range, residual, preload.
    """
    A = R @ R.T
    fp = R.T @ np.linalg.solve(A, tau)
    n, _ = null_vector(R)
    if n is None:
        return dict(feasible=False, reason="rank<2", fp=fp, f=None, n=None)
    # f = fp + t n,  fmin<=f_i<=fmax
    lo, hi = -np.inf, np.inf
    for i in range(3):
        if abs(n[i]) < 1e-15:
            if not (fmin <= fp[i] <= fmax):
                return dict(feasible=False, reason="null component zero, fp outside", fp=fp, f=None, n=n)
            continue
        t1 = (fmin - fp[i]) / n[i]
        t2 = (fmax - fp[i]) / n[i]
        lo = max(lo, min(t1, t2))
        hi = min(hi, max(t1, t2))
    if lo > hi + 1e-12:
        return dict(feasible=False, reason="empty interval", fp=fp, f=None, n=n, t_lo=lo, t_hi=hi)
    # choose the middle of the feasible interval: keeps preload margin on both sides
    if np.isfinite(lo) and np.isfinite(hi):
        t = 0.5 * (lo + hi)
    elif np.isfinite(hi):
        t = hi
    else:
        t = max(0.0, lo)
    f = fp + t * n
    return dict(feasible=True, fp=fp, f=f, n=n, t=float(t), t_lo=float(lo), t_hi=float(hi),
                preload=float(f @ n), residual=float(np.linalg.norm(R @ f - tau)),
                residual_inf=float(np.max(np.abs(R @ f - tau))))


# ---------------------------------------------------------------- main
def main():
    dc, seg, mp = load_model()
    points = load_points(mp)
    const = np.zeros(3)
    for i in range(3):
        const[i] = (lengths_3d(points, 0.0, 0.0)[i] / 1000.0
                    - seg_eval(seg, "roll", CABLE[i], 0.0)[0]
                    - seg_eval(seg, "pitch", CABLE[i], 0.0)[0])

    summary = {"source_sha256": dc["source_sha256"], "constants_mm": []}
    for axis in AXES:
        for cable in CABLE:
            u1, u2, v1, v2, h = seg[(axis, cable)]["proj"]
            summary["constants_mm"].append([axis, cable, u1 * 1e3, u2 * 1e3,
                                            v1 * 1e3, v2 * 1e3, h * 1e3])

    # zero pose
    R0 = model_R(seg, 0.0, 0.0) * 1e3
    R0_3d = r_3d(points, 0.0, 0.0)[0]
    R0_abc = abc_R(seg, 0.0, 0.0) * 1e3
    summary["R0_mm"] = R0.tolist()
    summary["R0_3d_mm"] = R0_3d.tolist()
    summary["zero_max_abs_diff_model_vs_3d_mm"] = float(np.max(np.abs(R0 - R0_3d)))
    summary["zero_max_abs_diff_model_vs_abc_mm"] = float(np.max(np.abs(R0 - R0_abc)))
    n0, rank0 = null_vector(R0)
    summary["null0"] = n0.tolist() if n0 is not None else None
    summary["rank0"] = rank0
    summary["cond0"] = condition(R0)

    # geometry table
    gtab = geometry_table(seg)
    summary["geometry_table"] = gtab
    # check abc closure
    closure = 0.0
    for axis in AXES:
        for cable in CABLE:
            a2, b, g = seg[(axis, cable)]["abc"]
            u1, u2, v1, v2, h = seg[(axis, cable)]["proj"]
            alpha2 = u1 * u1 + u2 * u2 + v1 * v1 + v2 * v2 + h * h
            beta2 = -2 * (u1 * v1 + u2 * v2)
            gamma2 = 2 * (u1 * v2 - u2 * v1)
            closure = max(closure, abs(a2 - alpha2), abs(b - beta2), abs(g - gamma2))
    summary["abc_closure_max_abs_m2"] = closure

    # grid
    rows = []
    with open(DATA / "R_grid_corrected.csv", newline="", encoding="utf-8-sig") as fh:
        for rec in csv.DictReader(fh):
            rows.append(rec)
    diffs_model_cad, diffs_3d_cad, diffs_model_3d, diffs_len_model_cad, diffs_len_3d_cad = [], [], [], [], []
    cad_int, cad_bnd = [], []
    worst = {"model_cad": (0, None), "3d_cad": (0, None), "model_3d": (0, None)}
    conds, null_pos, null_nonpos = [], 0, 0
    Rmin = np.full((2, 3), np.inf)
    Rmax = np.full((2, 3), -np.inf)
    len0_3d = lengths_3d(points, 0.0, 0.0)
    len0_model = model_lengths(seg, 0.0, 0.0, const)
    for rec in rows:
        rd, pd = float(rec["yaw_deg"]), float(rec["pitch_deg"])
        rr, pp = rd * DEG, pd * DEG
        Rm = model_R(seg, rr, pp) * 1e3
        R3 = r_3d(points, rr, pp)[0]
        Rc = np.array([[float(rec["R_yaw_C1_m"]) * 1e3, float(rec["R_yaw_C2_m"]) * 1e3,
                        float(rec["R_yaw_C3_m"]) * 1e3],
                       [float(rec["R_pitch_C1_m"]) * 1e3, float(rec["R_pitch_C2_m"]) * 1e3,
                        float(rec["R_pitch_C3_m"]) * 1e3]])
        for name, A in (("model_cad", Rm - Rc), ("3d_cad", R3 - Rc), ("model_3d", Rm - R3)):
            d = float(np.max(np.abs(A)))
            if d > worst[name][0]:
                worst[name] = (d, (rd, pd, A.copy()))
        diffs_model_cad.append(np.abs(Rm - Rc))
        (cad_bnd if (abs(rd) >= 25 - 1e-9 or abs(pd + 25) < 1e-9 or abs(pd - 45) < 1e-9)
         else cad_int).append(np.abs(Rm - Rc))
        diffs_3d_cad.append(np.abs(R3 - Rc))
        diffs_model_3d.append(np.abs(Rm - R3))
        lm = (model_lengths(seg, rr, pp, const) - len0_model) * 1000.0
        l3 = lengths_3d(points, rr, pp) - len0_3d
        lc = np.array([float(rec["L1_m"]), float(rec["L2_m"]), float(rec["L3_m"])]) * 1e3 - \
             np.array([float(rows[0]["L1_m"]), float(rows[0]["L2_m"]), float(rows[0]["L3_m"])]) * 1e3
        # reference zero lengths are the row at (0,0), find it separately below
        diffs_len_model_cad.append(np.abs(lm - lc))
        diffs_len_3d_cad.append(np.abs(l3 - lc))
        conds.append(condition(Rm))
        n, _ = null_vector(Rm)
        if n is not None and np.all(n > 1e-6):
            null_pos += 1
        else:
            null_nonpos += 1
        Rmin = np.minimum(Rmin, Rm)
        Rmax = np.maximum(Rmax, Rm)

    # fix length reference: zero row
    zero_rec = min(rows, key=lambda r: abs(float(r["yaw_deg"])) + abs(float(r["pitch_deg"])))
    Lzero = np.array([float(zero_rec["L1_m"]), float(zero_rec["L2_m"]), float(zero_rec["L3_m"])]) * 1e3
    diffs_len_model_cad, diffs_len_3d_cad = [], []
    for rec in rows:
        rd, pd = float(rec["yaw_deg"]), float(rec["pitch_deg"])
        rr, pp = rd * DEG, pd * DEG
        lc = np.array([float(rec["L1_m"]), float(rec["L2_m"]), float(rec["L3_m"])]) * 1e3 - Lzero
        lm = (model_lengths(seg, rr, pp, const) - len0_model) * 1000.0
        l3 = lengths_3d(points, rr, pp) - len0_3d
        diffs_len_model_cad.append(np.abs(lm - lc))
        diffs_len_3d_cad.append(np.abs(l3 - lc))

    summary["grid"] = {
        "rows": len(rows),
        "model_vs_cad_max_mm": float(np.max(diffs_model_cad)),
        "model_vs_cad_rms_mm": float(np.sqrt(np.mean(np.square(diffs_model_cad)))),
        "model_vs_cad_interior_max_mm": float(np.max(cad_int)),
        "model_vs_cad_boundary_max_mm": float(np.max(cad_bnd)),
        "model_vs_cad_worst": [worst["model_cad"][0], worst["model_cad"][1][:2]] if worst["model_cad"][1] else None,
        "model_vs_3d_max_mm": float(np.max(diffs_model_3d)),
        "model_vs_3d_rms_mm": float(np.sqrt(np.mean(np.square(diffs_model_3d)))),
        "length_model_vs_cad_max_mm": float(np.max(diffs_len_model_cad)),
        "length_3d_vs_cad_max_mm": float(np.max(diffs_len_3d_cad)),
        "positive_null": null_pos,
        "nonpositive_null": null_nonpos,
        "cond_min": float(np.min(conds)),
        "cond_max": float(np.max(conds)),
        "R_min_mm": Rmin.tolist(),
        "R_max_mm": Rmax.tolist(),
    }

    # 3D vs CAD worst
    summary["grid"]["3d_vs_cad_max_mm"] = float(np.max(diffs_3d_cad))
    if worst["3d_cad"][1]:
        summary["grid"]["3d_vs_cad_worst"] = [worst["3d_cad"][0], worst["3d_cad"][1][:2]]

    # -------- finite-difference method of the CAD reference table
    wr = worst["model_cad"][1]
    fd_info = {}
    if wr:
        rd, pd, _ = wr
        Rm = model_R(seg, rd * DEG, pd * DEG) * 1e3
        Rc = None
        for rec in rows:
            if abs(float(rec["yaw_deg"]) - rd) < 1e-9 and abs(float(rec["pitch_deg"]) - pd) < 1e-9:
                Rc = np.array([[float(rec["R_yaw_C1_m"]) * 1e3, float(rec["R_yaw_C2_m"]) * 1e3,
                                float(rec["R_yaw_C3_m"]) * 1e3],
                               [float(rec["R_pitch_C1_m"]) * 1e3, float(rec["R_pitch_C2_m"]) * 1e3,
                                float(rec["R_pitch_C3_m"]) * 1e3]])
                break
        idx = np.unravel_index(np.argmax(np.abs(Rm - Rc)), Rm.shape)
        j, i = int(idx[0]), int(idx[1])
        axis = AXES[j]
        base = (rd if j == 0 else pd) * DEG
        h = 0.2 * DEG

        def L(th):
            if j == 0:
                return lengths_3d(points, th, pd * DEG)[i]
            return lengths_3d(points, rd * DEG, th)[i]

        f0, f1, f2 = L(base), L(base + h), L(base + 2 * h)
        fd_2f = -(-3 * f0 + 4 * f1 - f2) / (2 * h)          # 2nd-order forward, 0.2 deg
        fd_c1 = -(L(base + 0.1 * DEG) - L(base - 0.1 * DEG)) / (0.2 * DEG)
        fd_c2 = -(L(base + 0.2 * DEG) - L(base - 0.2 * DEG)) / (0.4 * DEG)
        ra = Rm[j, i]
        fd_info = {"pose": [rd, pd], "element": [axis, CABLE[i]],
                   "analytic_mm": float(ra), "cad_mm": float(Rc[j, i]),
                   "fd_2nd_forward_0p2_mm": float(fd_2f),
                   "cad_minus_2nd_forward_mm": float(Rc[j, i] - fd_2f),
                   "fd_central_0p2_mm": float(fd_c1),
                   "fd_central_0p4_mm": float(fd_c2),
                   "fd_truncation_0p2_mm": float(fd_2f - ra)}
        scan = []
        for hd in (0.4, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.001):
            hh = hd * DEG
            if j == 0:
                fdv = -(lengths_3d(points, base + hh, pd * DEG)[i]
                        - lengths_3d(points, base - hh, pd * DEG)[i]) / (2 * hh)
            else:
                fdv = -(lengths_3d(points, rd * DEG, base + hh)[i]
                        - lengths_3d(points, rd * DEG, base - hh)[i]) / (2 * hh)
            scan.append([hd, float(fdv - ra)])
        fd_info["central_step_scan"] = scan

        # zero-pose check: does central 0.2 deg reproduce the table exactly?
        zr, zp = 0.0, 0.0
        Rcz = np.array([[float(zero_rec["R_yaw_C1_m"]) * 1e3, float(zero_rec["R_yaw_C2_m"]) * 1e3,
                         float(zero_rec["R_yaw_C3_m"]) * 1e3],
                        [float(zero_rec["R_pitch_C1_m"]) * 1e3, float(zero_rec["R_pitch_C2_m"]) * 1e3,
                         float(zero_rec["R_pitch_C3_m"]) * 1e3]])
        Rfd0 = np.zeros((2, 3))
        for jj, ax in enumerate((0, 1)):
            for ii in range(3):
                if ax == 0:
                    Rfd0[jj, ii] = -(lengths_3d(points, zr + 0.1 * DEG, zp)[ii]
                                     - lengths_3d(points, zr - 0.1 * DEG, zp)[ii]) / (0.2 * DEG)
                else:
                    Rfd0[jj, ii] = -(lengths_3d(points, zr, zp + 0.1 * DEG)[ii]
                                     - lengths_3d(points, zr, zp - 0.1 * DEG)[ii]) / (0.2 * DEG)
        fd_info["zero_central_vs_cad_max_mm"] = float(np.max(np.abs(Rfd0 - Rcz)))
        fd_info["zero_central_vs_analytic_max_mm"] = float(np.max(np.abs(Rfd0 - R0)))
    summary["fd_info"] = fd_info

    # -------- float32
    f32_diffs = []
    f32_len_diffs = []
    f32_worst = (0, None)
    # grid + random
    rng = np.random.default_rng(20261026)
    test_angles = [(float(r["yaw_deg"]), float(r["pitch_deg"])) for r in rows]
    for _ in range(5000):
        test_angles.append((float(rng.uniform(-25, 25)), float(rng.uniform(-25, 45))))
    for _ in range(603):
        test_angles.append((float(rng.uniform(-25, 25)), float(rng.uniform(-25, -23))))
    for rd, pd in test_angles:
        Rm = model_R(seg, rd * DEG, pd * DEG) * 1e3
        Rf = model_R_f32(seg, rd * DEG, pd * DEG).astype(float) * 1e3
        d = np.max(np.abs(Rm - Rf))
        f32_diffs.append(np.abs(Rm - Rf))
        if d > f32_worst[0]:
            f32_worst = (d, (rd, pd, np.unravel_index(np.argmax(np.abs(Rm - Rf)), Rm.shape)))
        # length sum in float32 vs double (constant c_i cancels)
        l32 = np.float32(0.0)
        l64 = 0.0
        for j, ax in enumerate(AXES):
            th = (rd if j == 0 else pd) * DEG
            for i in range(3):
                l32 = np.float32(l32 + seg_eval_f32(seg, ax, CABLE[i], f32(th))[0])
                l64 += seg_eval(seg, ax, CABLE[i], th)[0]
        f32_len_diffs.append(abs(float(l32) - l64) * 1e3)
    summary["float32"] = {
        "cases": len(test_angles),
        "max_abs_mm": float(np.max(f32_diffs)),
        "rms_mm": float(np.sqrt(np.mean(np.square(f32_diffs)))),
        "length_max_abs_mm": float(np.max(f32_len_diffs)),
        "worst": [f32_worst[0], f32_worst[1][:2] if f32_worst[1] else None],
    }

    # -------- dynamic sweeps
    roll_sweep = np.linspace(-25, 25, 101)
    pitch_sweep = np.linspace(-25, 45, 141)
    sweep = []
    for rd in roll_sweep:
        R = model_R(seg, rd * DEG, 0.0) * 1e3
        n, _ = null_vector(R)
        sweep.append([float(rd), *R[0].tolist(), *R[1].tolist(), condition(R),
                      float(n[0]) if n is not None else None,
                      float(n[1]) if n is not None else None,
                      float(n[2]) if n is not None else None])
    np.savetxt(OUT / "sweep_roll.csv", np.array(sweep), delimiter=",",
               header="roll_deg,Rr_C1,Rr_C2,Rr_C3,Rp_C1,Rp_C2,Rp_C3,cond,n1,n2,n3", comments="")
    sweep_p = []
    for pd in pitch_sweep:
        R = model_R(seg, 0.0, pd * DEG) * 1e3
        n, _ = null_vector(R)
        sweep_p.append([float(pd), *R[0].tolist(), *R[1].tolist(), condition(R),
                        float(n[0]) if n is not None else None,
                        float(n[1]) if n is not None else None,
                        float(n[2]) if n is not None else None])
    np.savetxt(OUT / "sweep_pitch.csv", np.array(sweep_p), delimiter=",",
               header="pitch_deg,Rr_C1,Rr_C2,Rr_C3,Rp_C1,Rp_C2,Rp_C3,cond,n1,n2,n3", comments="")

    # -------- trajectory
    traj = []
    for t in np.linspace(0, 2, 201):
        rd = 20 * math.sin(2 * math.pi * t)
        pd = 10 + 30 * math.sin(2 * math.pi * t + 0.6)
        R = model_R(seg, rd * DEG, pd * DEG) * 1e3
        n, _ = null_vector(R)
        traj.append([float(t), rd, pd, *R[0].tolist(), *R[1].tolist(), condition(R),
                     float(n[0]) if n is not None else None,
                     float(n[1]) if n is not None else None,
                     float(n[2]) if n is not None else None])
    np.savetxt(OUT / "trajectory.csv", np.array(traj), delimiter=",",
               header="t,roll_deg,pitch_deg,Rr_C1,Rr_C2,Rr_C3,Rp_C1,Rp_C2,Rp_C3,cond,n1,n2,n3", comments="")
    conds_traj = [row[9] for row in traj]
    summary["trajectory"] = {"cond_min": float(min(conds_traj)), "cond_max": float(max(conds_traj)),
                             "roll_min": float(min(r[1] for r in traj)), "roll_max": float(max(r[1] for r in traj)),
                             "pitch_min": float(min(r[2] for r in traj)), "pitch_max": float(max(r[2] for r in traj))}

    # -------- tension solve demo
    tau = np.array([0.10, 0.20])  # N*m illustrative
    fmin, fmax = 5.0, 40.0
    tension_demo = {}
    for name, (rd, pd) in {"zero": (0, 0), "low": (5, 10), "mid": (10, 20),
                           "mix": (15, 30), "neg": (-20, -20), "highp": (0, 44)}.items():
        R = model_R(seg, rd * DEG, pd * DEG)  # m
        sol = tension_solve(R, tau, fmin, fmax)
        tension_demo[name] = {
            "pose": [rd, pd],
            "cond": condition(R),
            "n": sol["n"].tolist() if sol.get("n") is not None else None,
            "fp": sol["fp"].tolist(),
            "feasible": sol["feasible"],
            "reason": sol.get("reason"),
            "t": sol.get("t"),
            "t_lo": sol.get("t_lo"),
            "t_hi": sol.get("t_hi"),
            "f": sol["f"].tolist() if sol.get("f") is not None else None,
            "preload": sol.get("preload"),
            "residual_inf": sol.get("residual_inf"),
        }
    summary["tension_demo"] = {"tau": tau.tolist(), "fmin": fmin, "fmax": fmax, "cases": tension_demo}

    # -------- IK demo (separable Gauss-Newton)
    target = (15 * DEG, 30 * DEG)
    lt = lengths_3d(points, *target)
    l0 = lengths_3d(points, 0.0, 0.0)
    th = np.array([0.0, 0.0])
    hist = []
    for it in range(8):
        lc = lengths_3d(points, th[0], th[1])
        res = lt - lc
        R = model_R(seg, th[0], th[1]) * 1e3
        dth = np.array([-R[j] @ res / (R[j] @ R[j]) for j in range(2)])
        hist.append([it, th[0] / DEG, th[1] / DEG, float(np.linalg.norm(res)), *res.tolist()])
        th = th + dth
    summary["ik"] = {"target_deg": [15, 30], "history": hist,
                     "final_deg": (th / DEG).tolist()}

    # -------- save
    def conv(o):
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        raise TypeError(type(o))
    (OUT / "verify_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=conv), encoding="utf-8")

    # print readable digest
    print(json.dumps({k: summary[k] for k in (
        "R0_mm", "R0_3d_mm", "zero_max_abs_diff_model_vs_3d_mm",
        "zero_max_abs_diff_model_vs_abc_mm", "null0", "cond0",
        "abc_closure_max_abs_m2", "grid", "float32", "trajectory", "fd_info")},
        ensure_ascii=False, indent=2, default=conv))
    print("\ngeometry table")
    for r in gtab:
        print(f"{r['axis']:5s} {r['cable']} a={r['a']:.6f} b={r['b']:.6f} h={r['h']:.6f} "
              f"delta={r['delta_deg']:+.4f} r0={r['r0']:+.6f}")
    print("\ntension demo")
    print(json.dumps(summary["tension_demo"], ensure_ascii=False, indent=2, default=conv))
    print("\nik")
    print(json.dumps(summary["ik"], ensure_ascii=False, indent=2, default=conv))


if __name__ == "__main__":
    main()

