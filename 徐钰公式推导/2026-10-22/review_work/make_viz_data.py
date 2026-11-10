"""Precompute chart data for the visual review report -> review_work/viz_data.json
All paths are fixed literals under the project folder; no user input used."""
import json, math, csv
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PARAMS_PATH = BASE / "复核数据_extracted" / "复核数据" / "model_parameters.json"
GRID_PATH = BASE / "复核数据_extracted" / "复核数据" / "R_grid_corrected.csv"
OUT_PATH = BASE / "review_work" / "viz_data.json"

params = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))

def vsub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def vadd(a, b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def vmul(a, s): return (a[0]*s, a[1]*s, a[2]*s)
def vdot(a, b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def vcross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def vnorm(a): return math.sqrt(vdot(a, a))
def rodrigues(v, k, th):
    c, s = math.cos(th), math.sin(th)
    return vadd(vadd(vmul(v, c), vmul(vcross(k, v), s)), vmul(k, vdot(k, v)*(1-c)))
def rot_about(p, k, o, th): return vadd(o, rodrigues(vsub(p, o), k, th))

ar = (0., 1., 0.); orr = (0., 0., 0.); ap0 = (1., 0., 0.); op0 = (0., 0., 0.024)
pts = [tuple(p["zero_model_m"]) for p in params["points"]]
body = [p["body"] for p in params["points"]]

def length_full(tr, tp):
    out = []
    for p0, b in zip(pts, body):
        if b == "base":
            out.append(p0)
        elif b == "roll_link":
            out.append(rot_about(p0, ar, orr, tr))
        else:
            q = rot_about(p0, ar, orr, tr)
            ap = rodrigues(ap0, ar, tr); op = rot_about(op0, ar, orr, tr)
            out.append(rot_about(q, ap, op, tp))
    tot = [0., 0., 0.]
    for c in range(3):
        s = 0.
        for k in range(7):
            i = c*8 + k
            s += vnorm(vsub(out[i+1], out[i]))
        tot[c] = s
    return tot

# ---- grid stats: my finite-difference R vs CAD R table ----
rows = list(csv.DictReader(GRID_PATH.open(encoding="utf-8-sig")))
n = len(rows)
mx = [[0.0]*3 for _ in range(2)]
ss = [[0.0]*3 for _ in range(2)]
for r in rows:
    tr = math.radians(float(r["yaw_deg"])); tp = math.radians(float(r["pitch_deg"]))
    Lp = length_full(tr+1e-6, tp); Lm = length_full(tr-1e-6, tp)
    rr = [-(Lp[i]-Lm[i])/2e-6 for i in range(3)]
    Lp = length_full(tr, tp+1e-6); Lm = length_full(tr, tp-1e-6)
    rp = [-(Lp[i]-Lm[i])/2e-6 for i in range(3)]
    for i in range(3):
        d = abs(rr[i]-float(r[f"R_yaw_C{i+1}_m"]))*1000
        mx[0][i] = max(mx[0][i], d); ss[0][i] += d*d
        d = abs(rp[i]-float(r[f"R_pitch_C{i+1}_m"]))*1000
        mx[1][i] = max(mx[1][i], d); ss[1][i] += d*d
myMax = mx[0] + mx[1]
myRmse = [math.sqrt(ss[0][0]/n), math.sqrt(ss[0][1]/n), math.sqrt(ss[0][2]/n),
          math.sqrt(ss[1][0]/n), math.sqrt(ss[1][1]/n), math.sqrt(ss[1][2]/n)]
docMax = [2.47135696e-05, 0.00096527662, 0.000634235294, 0.0326679971, 0.000147911374, 0.000110579499]
docRmse = [8.6846282e-06, 0.000331367224, 0.000238092193, 0.00616803578, 6.12482662e-05, 5.11998422e-05]

# ---- CAD R_yaw_C2 at pitch=0 across roll ----
cad = [(float(r["yaw_deg"]), float(r["R_yaw_C2_m"])*1000) for r in rows if float(r["pitch_deg"]) == 0.0]
cad.sort()

# ---- preload map ----
rolls = sorted({round(float(r["yaw_deg"])) for r in rows})
pitches = sorted({round(float(r["pitch_deg"])) for r in rows})
rmap = {p: ["0"]*len(rolls) for p in pitches}
for r in rows:
    j = rolls.index(round(float(r["yaw_deg"])))
    rmap[round(float(r["pitch_deg"]))][j] = "1" if r["positive_null"] == "True" else "0"
pmap = ["".join(rmap[p]) for p in pitches]
bad = sum(row.count("0") for row in pmap)

# ---- C1-pitch stencil truncation series ----
A, B, C = [v*1e6 for v in params["cables"][0]["pitch_ABC_m2"]]
def s_of(th): return math.sqrt(A + B*math.cos(th) + C*math.sin(th))
h = math.radians(0.2)
angs, rana, rst, dif = [], [], [], []
d = math.radians(-25)
while d <= math.radians(45) + 1e-9:
    deg = math.degrees(d)
    r_ana = (B*math.sin(d) - C*math.cos(d)) / (2*s_of(d))
    if abs(deg + 25) < 1e-9:
        st = (-3*s_of(d) + 4*s_of(d+h) - s_of(d+2*h)) / (2*h)
    elif abs(deg - 45) < 1e-9:
        st = (3*s_of(d) - 4*s_of(d-h) + s_of(d-2*h)) / (2*h)
    else:
        st = (s_of(d+h) - s_of(d-h)) / (2*h)
    angs.append(round(deg, 2))
    rana.append(round(r_ana, 6))
    rst.append(round(-st, 6))
    dif.append(round(abs(r_ana + st), 7))
    d += math.radians(0.5)

# ---- 24 zero points in mm ----
pts24 = [{"id": p["id"], "cable": p["cable"], "body": p["body"],
          "x": round(p["zero_model_m"][0]*1000, 3),
          "y": round(p["zero_model_m"][1]*1000, 3),
          "z": round(p["zero_model_m"][2]*1000, 3)} for p in params["points"]]

# ---- ABC coefficients + documented minima ----
mins = {"C1/roll": (13.485763, -2.196570), "C1/pitch": (3.900609, -25.0),
        "C2/roll": (10.485589, -18.488231), "C2/pitch": (11.890136, 33.830498),
        "C3/roll": (14.692202, 15.149529), "C3/pitch": (13.445385, 33.830498)}
abc = []
for cab in params["cables"]:
    for seg in ("roll", "pitch"):
        a, b, c = [v*1e6 for v in cab[f"{seg}_ABC_m2"]]
        m, ma = mins[f"{cab['id']}/{seg}"]
        abc.append({"cable": cab["id"], "seg": seg, "A": round(a, 6), "B": round(b, 6),
                    "C": round(c, 6), "minS": m, "minAng": ma})

grad = {"P04": [1.3469, 2.0380, 2.1996], "P05": [0.3720, 1.1154, 1.2376],
        "P06": [0.8194, 1.3979, 1.3253], "P07": [0.1813, 0.3982, 0.4475]}

out = {"pts24": pts24, "abc": abc,
       "myMax": [float(f"{v:.8g}") for v in myMax],
       "myRmse": [float(f"{v:.8g}") for v in myRmse],
       "docMax": docMax, "docRmse": docRmse,
       "cadC2roll": [[a, float(f"{b:.6f}")] for a, b in cad],
       "rolls": rolls, "pitches": pitches, "pmap": pmap, "bad": bad,
       "stencil": {"ang": angs, "rana": rana, "rst": rst, "dif": dif},
       "grad": grad, "decoupleCounter": [0.0694, 1.367, 1.242]}
OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print("maxdiff ana vs stencil peak:", max(dif), "at", angs[dif.index(max(dif))])
print("myMax:", [f"{v:.6g}" for v in myMax])
print("bad:", bad, "of", n, "; cad pts:", len(cad))
