"""Refined local gradient at P06 (Richardson), zero-pose CAD-diff row, preload count."""
import json, math, csv

MP="复核数据_extracted/复核数据/model_parameters.json"
GRID="复核数据_extracted/复核数据/R_grid_corrected.csv"
params=json.load(open(MP,encoding="utf-8"))

def vsub(a,b): return (a[0]-b[0],a[1]-b[1],a[2]-b[2])
def vadd(a,b): return (a[0]+b[0],a[1]+b[1],a[2]+b[2])
def vmul(a,s): return (a[0]*s,a[1]*s,a[2]*s)
def vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def vcross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def vnorm(a): return math.sqrt(vdot(a,a))
def rodrigues(v,k,th):
    c,s=math.cos(th),math.sin(th)
    return vadd(vadd(vmul(v,c),vmul(vcross(k,v),s)),vmul(k,vdot(k,v)*(1-c)))
def rot_about(p,k,o,th): return vadd(o,rodrigues(vsub(p,o),k,th))

ar=(0.,1.,0.); orr=(0.,0.,0.); ap0=(1.,0.,0.); op0=(0.,0.,0.024)
body=[p["body"] for p in params["points"]]
p06_i=[i for i,p in enumerate(params["points"]) if p["id"]=="C1-P06"][0]
base_pts=[tuple(p["zero_model_m"]) for p in params["points"]]

def R_pitch_C1_from(pts, tr, tp, h=1e-6):
    def lf(tr,tp):
        out=[]
        for p0,b in zip(pts,body):
            if b=="base": out.append(p0)
            elif b=="roll_link": out.append(rot_about(p0,ar,orr,tr))
            else:
                q=rot_about(p0,ar,orr,tr)
                ap=rodrigues(ap0,ar,tr); op=rot_about(op0,ar,orr,tr)
                out.append(rot_about(q,ap,op,tp))
        s=0.
        for k in range(7): s+=vnorm(vsub(out[k+1],out[k]))
        return s
    return -(lf(tr,tp+h)-lf(tr,tp-h))/(2*h)

def shift(pts,i,dv):
    q=list(pts); p=list(q[i]); p[0]+=dv[0]; p[1]+=dv[1]; p[2]+=dv[2]; q[i]=tuple(p); return q

tr,tp=0.0,math.radians(-25.)
print("1. refined dR_pitch_C1/dz(P06) at (0,-25deg), Richardson on central steps")
prev=None
for h in (5e-4,2.5e-4,1.25e-4,6.25e-5):
    rp=R_pitch_C1_from(shift(base_pts,p06_i,(0,0,+h)),tr,tp)
    rm=R_pitch_C1_from(shift(base_pts,p06_i,(0,0,-h)),tr,tp)
    d=(rp-rm)/(2*h)
    print(f"   h={h:.2e}: dR/dz = {d:.6f} mm/mm")
    if prev: print(f"      Richardson: {(4*d-prev)/3:.6f}")
    prev=d

print("\n2. full 3D gradient norm of R_pitch_C1 wrt P06 position at (0,-25deg), h=1e-4")
g=[]
for dv in ((1,0,0),(0,1,0),(0,0,1)):
    rp=R_pitch_C1_from(shift(base_pts,p06_i,tuple(x*1e-4 for x in dv)),tr,tp)
    rm=R_pitch_C1_from(shift(base_pts,p06_i,tuple(-x*1e-4 for x in dv)),tr,tp)
    g.append((rp-rm)/(2e-4))
print("   grad =",[f"{v:.6f}" for v in g]," norm =",f"{math.sqrt(sum(v*v for v in g)):.6f}","(doc 15.745867)")

print("\n3. zero-pose row: analytic vs CAD grid at (0,0)")
grid=list(csv.DictReader(open(GRID,encoding="utf-8-sig")))
zr=[r for r in grid if float(r["yaw_deg"])==0.0 and float(r["pitch_deg"])==0.0][0]
print("   CAD  roll:",[f"{float(zr[f'R_yaw_C{i+1}_m'])*1000:.8f}" for i in range(3)])
print("   CAD  pitch:",[f"{float(zr[f'R_pitch_C{i+1}_m'])*1000:.8f}" for i in range(3)])
print("   doc diff roll: [-0.25943594, -22.04935585, 17.37166016]")
print("   doc diff pitch: [-58.10454990, 11.80482013, 10.99029230]")

pn=sum(1 for r in grid if r["positive_null"]=="True")
print(f"\n4. positive_null: {pn} True / {len(grid)} => {len(grid)-pn} not all-positive (doc: 1664)")

# rank2 check
r2=sum(1 for r in grid if r["rank2"]=="True")
print(f"   rank2 True: {r2}/{len(grid)}")
