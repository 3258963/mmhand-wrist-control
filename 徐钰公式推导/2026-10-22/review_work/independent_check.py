"""Independent reviewer implementation. Written from first principles:
- model frame F0: roll axis origin (0,0,0), dir (0,1,0); pitch_zero origin (0,0,0.024), dir (1,0,0)
- kinematics: roll_link rotates about roll axis by +roll; palm rotates additionally about the
  roll-carried pitch axis by +pitch (right-hand active rotations, column vectors).
- Standard library only.
"""
import json, math, csv, sys

MP = "复核数据_extracted/复核数据/model_parameters.json"

def load():
    with open(MP, encoding="utf-8") as f:
        return json.load(f)

# --- minimal 3-vector algebra (own code, deliberately not copied) ---
def vsub(a,b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def vadd(a,b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def vmul(a,s): return (a[0]*s, a[1]*s, a[2]*s)
def vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def vcross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def vnorm(a): return math.sqrt(vdot(a,a))

def rodrigues(v, k, th):
    # active rotation of vector v about unit axis k by angle th (right-hand rule)
    c, s = math.cos(th), math.sin(th)
    return vadd(vadd(vmul(v,c), vmul(vcross(k,v),s)), vmul(k, vdot(k,v)*(1.0-c)))

def rot_about(p, k, o, th):
    return vadd(o, rodrigues(vsub(p,o), k, th))

# --- geometry from the JSON but rebuilt in F0 model coordinates ---
class Model:
    def __init__(self, params):
        self.params = params
        # F0 axes per document section 4 (in model coordinates):
        self.ar = (0.0, 1.0, 0.0)   # roll direction
        self.orr = (0.0, 0.0, 0.0)  # roll origin
        self.ap0 = (1.0, 0.0, 0.0)  # pitch direction at zero
        self.op0 = (0.0, 0.0, 0.024) # pitch origin at zero (24 mm offset)
        self.pts = [p["zero_model_m"] for p in params["points"]]
        self.body = [p["body"] for p in params["points"]]

    def points(self, th_r, th_p):
        out = []
        for p0, body in zip(self.pts, self.body):
            if body == "base":
                out.append(p0)
            elif body == "roll_link":
                out.append(rot_about(p0, self.ar, self.orr, th_r))
            else:  # palm: carried by roll, then pitched about the roll-carried pitch axis
                q = rot_about(p0, self.ar, self.orr, th_r)
                ap = rodrigues(self.ap0, self.ar, th_r)
                op = rot_about(self.op0, self.ar, self.orr, th_r)
                out.append(rot_about(q, ap, op, th_p))
        return out

    def length(self, th_r, th_p):
        P = self.points(th_r, th_p)
        total = [0.0,0.0,0.0]
        for c in range(3):
            s = 0.0
            for k in range(7):
                i = c*8+k
                s += vnorm(vsub(P[i+1], P[i]))
            total[c] = s
        return total

    def R_central_diff(self, th_r, th_p, h=1e-6):
        # R[j][i] = -dl_i/dq_j, central difference
        Lp = self.length(th_r+h, th_p); Lm = self.length(th_r-h, th_p)
        dldr = [(Lp[i]-Lm[i])/(2*h) for i in range(3)]
        Lp = self.length(th_r, th_p+h); Lm = self.length(th_r, th_p-h)
        dldp = [(Lp[i]-Lm[i])/(2*h) for i in range(3)]
        return [[-dldr[0],-dldr[1],-dldr[2]], [-dldp[0],-dldp[1],-dldp[2]]]

    def R_via_abc(self, th_r, th_p):
        # closed form from cables' ABC, r = (B*sin - C*cos)/(2 sqrt(D))
        row_r, row_p = [], []
        for cab in self.params["cables"]:
            for which, abc, th in (("r", cab["roll_ABC_m2"], th_r), ("p", cab["pitch_ABC_m2"], th_p)):
                A,B,C = abc
                D = A + B*math.cos(th) + C*math.sin(th)
                r = (B*math.sin(th) - C*math.cos(th))/(2*math.sqrt(D))
                (row_r if which=="r" else row_p).append(r)
        return [row_r, row_p]

def main():
    params = load()
    m = Model(params)

    # 1) recompute ABC from points myself and compare with JSON
    print("=== ABC recomputation from points (mine vs JSON), mm^2 ===")
    segs = {"roll": ("P04","P05", m.ar, m.orr), "pitch": ("P06","P07", m.ap0, m.op0)}
    idx = {}
    for p in params["points"]:
        idx[(p["cable"], p["id"].split("-")[1])] = p["zero_model_m"]
    for cab in params["cables"]:
        c = cab["id"][-1]
        for segname,(pa,pb,axis,orig) in segs.items():
            A = idx[(int(c),pa)]; B0 = idx[(int(c),pb)]
            u = vsub(A,orig); v = vsub(B0,orig)
            aat = lambda w: vmul(axis, vdot(axis,w))
            perp = lambda w: vsub(w, aat(w))
            alpha = vdot(u,u)+vdot(v,v)-2*vdot(aat(u),aat(v))
            beta  = -2*vdot(perp(u),perp(v))
            gamma = -2*vdot(u, vcross(axis,v))
            got = cab[f"{segname}_ABC_m2"]
            conv = 1e6  # m^2 -> mm^2
            print(f"{cab['id']}/{segname}: mine(mm2)=({alpha*conv:.6f},{beta*conv:.6f},{gamma*conv:.6f}) json=({got[0]*conv:.6f},{got[1]*conv:.6f},{got[2]*conv:.6f})")

    # 2) C2 roll instance
    A,B,C = params["cables"][1]["roll_ABC_m2"]
    D0 = A + B*1.0 + C*0.0  # D at theta=0
    r0 = (B*0.0 - C*1.0)/(2*math.sqrt(D0))
    print(f"\n=== C2 roll at 0: D0={D0*1e6:.2f} mm2, r(0)={r0*1000:.8f} mm (doc: -22.04970101)")

    # 3) zero-pose matrix: closed form vs my central difference vs doc
    R_abc = m.R_via_abc(0.0,0.0)
    R_fd  = m.R_central_diff(0.0,0.0)
    doc = [[-0.25943726,-22.04970101,17.37198247],[-58.10461556,11.80488412,10.99035112]]
    print("\n=== zero-pose R (mm) ===")
    for name,M in (("abc",R_abc),("fd ",R_fd),("doc",doc)):
        if name=="doc":
            print(name, [[f"{v:.8f}" for v in row] for row in M])
        else:
            print(name, [[f"{v*1000:.8f}" for v in row] for row in M])

    # sign test at a nonzero angle to discriminate (23) vs S4-transcription
    th = math.radians(17.3)
    Lp = m.length(th+1e-6, 0.0); Lm = m.length(th-1e-6, 0.0)
    ds = (Lp[1]-Lm[1])/2e-6
    A,B,C = params["cables"][1]["roll_ABC_m2"]
    D = A+B*math.cos(th)+C*math.sin(th)
    r_abc = (B*math.sin(th)-C*math.cos(th))/(2*math.sqrt(D))
    print(f"\n=== sign discrimination at roll=17.3deg: ds/dth={ds*1000:.6f} mm/rad, r=-ds/dth={-ds*1000:.6f}, abc r={r_abc*1000:.6f}")

if __name__ == "__main__":
    main()
