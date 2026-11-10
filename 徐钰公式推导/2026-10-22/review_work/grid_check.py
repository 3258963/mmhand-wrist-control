"""Full-grid and stencil comparisons, decoupling counterexample, identifiability numerics.
Independent reviewer code (no reuse of author's geometry_model.py)."""
import json, math, csv, random

MP = "复核数据_extracted/复核数据/model_parameters.json"
GRID = "复核数据_extracted/复核数据/R_grid_corrected.csv"
BOUND = "review_work/pdf_attachments/边界原始记录节选.json"

def vsub(a,b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def vadd(a,b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def vmul(a,s): return (a[0]*s, a[1]*s, a[2]*s)
def vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def vcross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def vnorm(a): return math.sqrt(vdot(a,a))
def rodrigues(v,k,th):
    c,s = math.cos(th), math.sin(th)
    return vadd(vadd(vmul(v,c), vmul(vcross(k,v),s)), vmul(k, vdot(k,v)*(1-c)))
def rot_about(p,k,o,th): return vadd(o, rodrigues(vsub(p,o),k,th))

class Model:
    def __init__(self, params, extra_direct_segment=False):
        self.ar=(0.,1.,0.); self.orr=(0.,0.,0.)
        self.ap0=(1.,0.,0.); self.op0=(0.,0.,0.024)
        self.pts=[p["zero_model_m"] for p in params["points"]]
        self.body=[p["body"] for p in params["points"]]
        self.cabs=params["cables"]
        self.extra=extra_direct_segment
    def points(self, tr, tp):
        out=[]
        for p0,body in zip(self.pts,self.body):
            if body=="base": out.append(p0)
            elif body=="roll_link": out.append(rot_about(p0,self.ar,self.orr,tr))
            else:
                q=rot_about(p0,self.ar,self.orr,tr)
                ap=rodrigues(self.ap0,self.ar,tr); op=rot_about(self.op0,self.ar,self.orr,tr)
                out.append(rot_about(q,ap,op,tp))
        return out
    def length_full(self, tr, tp):
        P=self.points(tr,tp); tot=[0.,0.,0.]
        for c in range(3):
            s=0.
            for k in range(7):
                i=c*8+k; s+=vnorm(vsub(P[i+1],P[i]))
            tot[c]=s
        return tot
    def R(self, tr, tp):
        rr,rp=[],[]
        for cab in self.cabs:
            for which,abc,th in (("r",cab["roll_ABC_m2"],tr),("p",cab["pitch_ABC_m2"],tp)):
                A,B,C=abc; D=A+B*math.cos(th)+C*math.sin(th)
                rr.append((B*math.sin(th)-C*math.cos(th))/(2*math.sqrt(D))) if which=="r" \
                else rp.append((B*math.sin(th)-C*math.cos(th))/(2*math.sqrt(D)))
        return rr,rp

def main():
    params=json.load(open(MP,encoding="utf-8"))
    m=Model(params)

    # ---------- 1. full 3621-pose grid: my analytic vs CAD ----------
    rows=list(csv.DictReader(open(GRID,encoding="utf-8-sig")))
    maxes={"L":[0]*3,"R":[[0]*3,[0]*3]}; sums={"L":[0.]*3,"R":[[0.]*3,[0.]*3]}
    worst=None
    n=0
    for r in rows:
        tr=math.radians(float(r["yaw_deg"])); tp=math.radians(float(r["pitch_deg"]))
        L=m.length_full(tr,tp); rr,rp=m.R(tr,tp)
        for i in range(3):
            dl=abs(L[i]-float(r[f"L{i+1}_m"]))*1000
            if dl>maxes["L"][i]: maxes["L"][i]=dl
            sums["L"][i]+=dl*dl
            for j,Rv in ((0,rr[i]),(1,rp[i])):
                d=abs(Rv-float(r[f"R_{'yaw' if j==0 else 'pitch'}_C{i+1}_m"]))*1000
                if d>maxes["R"][j][i]:
                    maxes["R"][j][i]=d
                    worst=(r["yaw_deg"],r["pitch_deg"],j,i,d)
                sums["R"][j][i]+=d*d
        n+=1
    print(f"grid poses: {n}")
    print("max |L_mine - L_CAD| (mm):", [f"{v:.3e}" for v in maxes["L"]])
    for j,name in ((0,"roll"),(1,"pitch")):
        print(f"max |R_{name} mine-CAD| (mm):", [f"{v:.3e}" for v in maxes["R"][j]])
        print(f"rmse R_{name} (mm):", [f"{math.sqrt(sums['R'][j][i]/n):.3e}" for i in range(3)])
    print("worst R cell:", worst)

    # ---------- 2. doc claims: roll/C1 2.47e-5, roll/C2 9.65e-4, roll/C3 6.34e-4,
    # pitch/C1 3.267e-2, pitch/C2 1.48e-4, pitch/C3 1.11e-4
    print("\ndoc-claimed max diffs (mm): roll/C1 2.47e-05 roll/C2 9.65e-04 roll/C3 6.34e-04",
          "pitch/C1 3.267e-02 pitch/C2 1.48e-04 pitch/C3 1.11e-04")

    # ---------- 3. my closed form vs my vector central diff on 200 random non-grid poses ----------
    random.seed(20261022)
    worst=0.; wpos=None
    for _ in range(200):
        tr=math.radians(random.uniform(-25,25)); tp=math.radians(random.uniform(-25,45))
        rr,rp=m.R(tr,tp)
        h=1e-6
        Lp=m.length_full(tr+h,tp); Lm=m.length_full(tr-h,tp)
        dldr=[(Lp[i]-Lm[i])/(2*h) for i in range(3)]
        Lp=m.length_full(tr,tp+h); Lm=m.length_full(tr,tp-h)
        dldp=[(Lp[i]-Lm[i])/(2*h) for i in range(3)]
        for i in range(3):
            for j,ana,fd in ((0,rr[i],-dldr[i]),(1,rp[i],-dldp[i])):
                d=abs(ana-fd)*1000
                if d>worst: worst=d; wpos=(math.degrees(tr),math.degrees(tp),j,i)
    print(f"\n200 non-grid poses, closed-form vs central-diff h=1e-6 rad: max {worst:.3e} mm at {wpos}")

    # ---------- 4. 0.2-degree stencil replay on boundary records ----------
    bound=json.load(open(BOUND,encoding="utf-8"))
    # structure exploration
    def show(o,p="",d=0):
        if d>2: return
        if isinstance(o,dict):
            for k,v in list(o.items())[:8]: show(v,p+"/"+k,d+1)
        elif isinstance(o,list):
            print(p,"len",len(o)); show(o[0],p+"[0]",d+1) if o else None
        else: print(p,"=",o)
    show(bound)

if __name__=="__main__":
    main()
