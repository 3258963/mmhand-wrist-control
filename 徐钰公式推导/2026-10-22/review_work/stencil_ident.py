"""Stencil replay on boundary captures + decoupling counterexample + identifiability numerics."""
import json, math, csv

MP="复核数据_extracted/复核数据/model_parameters.json"
BOUND="review_work/pdf_attachments/边界原始记录节选.json"
GRID="复核数据_extracted/复核数据/R_grid_corrected.csv"

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

params=json.load(open(MP,encoding="utf-8"))
ar=(0.,1.,0.); orr=(0.,0.,0.); ap0=(1.,0.,0.); op0=(0.,0.,0.024)
pts=[p["zero_model_m"] for p in params["points"]]
body=[p["body"] for p in params["points"]]

def points(tr,tp):
    out=[]
    for p0,b in zip(pts,body):
        if b=="base": out.append(p0)
        elif b=="roll_link": out.append(rot_about(p0,ar,orr,tr))
        else:
            q=rot_about(p0,ar,orr,tr)
            ap=rodrigues(ap0,ar,tr); op=rot_about(op0,ar,orr,tr)
            out.append(rot_about(q,ap,op,tp))
    return out

def length_full(tr,tp,extra_base_palm=False):
    P=points(tr,tp); tot=[0.,0.,0.]
    for c in range(3):
        s=0.
        for k in range(7):
            i=c*8+k; s+=vnorm(vsub(P[i+1],P[i]))
        if extra_base_palm:
            # counterexample segment: base P03 directly to palm P08 (crosses both joints)
            s+=vnorm(vsub(P[c*8+7],P[c*8+2]))
        tot[c]=s
    return tot

def R_abc(tr,tp):
    rr,rp=[],[]
    for cab in params["cables"]:
        for w,abc,th in (("r",cab["roll_ABC_m2"],tr),("p",cab["pitch_ABC_m2"],tp)):
            A,B,C=abc; D=A+B*math.cos(th)+C*math.sin(th)
            (rr if w=="r" else rp).append((B*math.sin(th)-C*math.cos(th))/(2*math.sqrt(D)))
    return rr,rp

# ---------------- A. captures: CAD lengths vs my model, stencil replay ----------------
bound=json.load(open(BOUND,encoding="utf-8"))
caps=bound["captures"]
print("A. per-capture: max |L_model - L_CADcorrected| (mm)")
mx=0.
for c in caps:
    L=length_full(math.radians(c["actual_roll_deg"]),math.radians(c["actual_pitch_deg"]))
    for i in range(3):
        d=abs(L[i]-c["corrected_lengths_m"][i])*1000
        mx=max(mx,d)
print("  max over 25x3 =",f"{mx:.3e}","mm")

# group into 5 crosses: center plus its roll-line and pitch-line neighbors (|offset|<=0.2deg)
CENTERS=[(-25.,-25.),(25.,-25.),(-25.,45.),(25.,45.),(4.,-25.)]
groups={c:[] for c in CENTERS}
for c in caps:
    cr,cp=c["command_roll_deg"],c["command_pitch_deg"]
    for (CR,CP) in CENTERS:
        on_roll_line=abs(cp-CP)<1e-9 and abs(cr-CR)<=0.4+1e-9
        on_pitch_line=abs(cr-CR)<1e-9 and abs(cp-CP)<=0.4+1e-9
        if on_roll_line or on_pitch_line:
            groups[(CR,CP)].append(c)
            break
print("cross sizes:", {k:len(v) for k,v in groups.items()})

def lag3(xs,ys,xstar):
    # derivative of the quadratic through (xs,ys), evaluated at x=xstar (one of xs)
    (x0,x1,x2),(y0,y1,y2)=xs,ys
    l0=(xstar-x1)/(x0-x1)*(xstar-x2)/(x0-x2)
    l1=(xstar-x0)/(x1-x0)*(xstar-x2)/(x1-x2)
    l2=(xstar-x0)/(x2-x0)*(xstar-x1)/(x2-x1)
    d0=(xstar-x1)/(x0-x1)+(xstar-x2)/(x0-x2)   # d/dx of ell0 at xstar, /((x0-x1)(x0-x2)) times...
    # do it cleanly: derivative of Lagrange basis at xstar
    def d_ell(i,xi,other):
        num=0.
        den=1.
        for j,xj in other:
            den*=(xi-xj)
            num+= 0.0
        return den
    # direct: ell_i'(x) = sum over j!=i of prod_{k!=i,j}(x-x_k) / prod_{k!=i}(xi-x_k)
    def ell_prime(i):
        xi=xs[i]; den=1.
        for j in range(3):
            if j!=i: den*=(xi-xs[j])
        s=0.
        for j in range(3):
            if j!=i:
                prod=1.
                for k in range(3):
                    if k!=i and k!=j: prod*=(xstar-xs[k])
                s+=prod
        return s/den
    return ys[0]*ell_prime(0)+ys[1]*ell_prime(1)+ys[2]*ell_prime(2)

print("\nB. stencil replay: Lagrange-3 on CAD corrected lengths (actual angles) vs my analytic R (mm)")
worst_stencil_vs_ana=0.; worst_stencil_vs_grid=0.; worst_ana_vs_grid=0.; wpos=None
grid={(r["yaw_deg"],r["pitch_deg"]):r for r in csv.DictReader(open(GRID,encoding="utf-8-sig"))}
for key,g in sorted(groups.items()):
    ctr=[c for c in g if c["actual_roll_deg"]==key[0] and c["actual_pitch_deg"]==key[1]][0]
    rline=[c for c in g if abs(c["actual_pitch_deg"]-key[1])<1e-9 and abs(c["actual_roll_deg"]-key[0])>1e-9]
    pline=[c for c in g if abs(c["actual_roll_deg"]-key[0])<1e-9 and abs(c["actual_pitch_deg"]-key[1])>1e-9]
    if len(rline)==2 and len(pline)==2:  # interior center with both neighbors
        rline=[c for c in rline if c["actual_roll_deg"]<key[0]]+[ctr]+[c for c in rline if c["actual_roll_deg"]>key[0]]
        pline=[c for c in pline if c["actual_pitch_deg"]<key[1]]+[ctr]+[c for c in pline if c["actual_pitch_deg"]>key[1]]
    else:  # boundary: one-sided (q, q+h, q+2h)
        rline=sorted(rline+[ctr],key=lambda c:c["actual_roll_deg"])
        pline=sorted(pline+[ctr],key=lambda c:c["actual_pitch_deg"])
    xs_r=[math.radians(c["actual_roll_deg"]) for c in rline]
    xs_p=[math.radians(c["actual_pitch_deg"]) for c in pline]
    rr,rp=R_abc(math.radians(key[0]),math.radians(key[1]))
    grow=grid[(f"{key[0]:.1f}",f"{key[1]:.1f}")] if (f"{key[0]:.1f}",f"{key[1]:.1f}") in grid else grid[(str(key[0]),str(key[1]))]
    for i in range(3):
        ys_r=[c["corrected_lengths_m"][i] for c in rline]
        ys_p=[c["corrected_lengths_m"][i] for c in pline]
        dr=lag3(xs_r,ys_r,math.radians(key[0])); dp=lag3(xs_p,ys_p,math.radians(key[1]))
        Rstencil=[-dr,-dp]
        ana=[rr[i],rp[i]]
        gv=[float(grow[f"R_yaw_C{i+1}_m"]),float(grow[f"R_pitch_C{i+1}_m"])]
        for j in (0,1):
            d1=abs(Rstencil[j]-ana[j])*1000
            d2=abs(Rstencil[j]-gv[j])*1000
            d3=abs(ana[j]-gv[j])*1000
            if d1>worst_stencil_vs_ana: worst_stencil_vs_ana=d1
            if d2>worst_stencil_vs_grid: worst_stencil_vs_grid=d2
            if d3>worst_ana_vs_grid: worst_ana_vs_grid=d3; wpos=(key,i,j)
print(f"  max |stencil(CAD_L) - analytic R|      = {worst_stencil_vs_ana:.3e} mm")
print(f"  max |stencil(CAD_L) - grid R table|   = {worst_stencil_vs_grid:.3e} mm  (doc claim: 0.0 / 1.53e-9 replay)")
print(f"  max |analytic R - grid R table|       = {worst_ana_vs_grid:.3e} mm at {wpos} (doc claim 3.27e-2)")

# ---------------- C. decoupling: current model cross-derivatives ----------------
print("\nC. cross-derivative check of current model (should be 0) and with added base->palm segment")
h=1e-6
def dL_dr(tr,tp): 
    Lp=length_full(tr+h,tp); Lm=length_full(tr-h,tp); return [(Lp[i]-Lm[i])/(2*h) for i in range(3)]
def dL_dp(tr,tp):
    Lp=length_full(tr,tp+h); Lm=length_full(tr,tp-h); return [(Lp[i]-Lm[i])/(2*h) for i in range(3)]
tr,tp=math.radians(7.3),math.radians(-11.1)
# mixed partial of L wrt (r,p): d/dr(dL/dp)
m1=[(a-b)/(2*h) for a,b in zip(dL_dp(tr+h,tp),dL_dp(tr-h,tp))]
print("  current model  d2L/drdp (mm/rad^2):",[f"{v*1000:.3e}" for v in m1])
# with extra segment: analytic closed form no longer valid; show L now varies with both in mixed way
def dLfull_dr(tr,tp):
    Lp=length_full(tr+h,tp,extra_base_palm=True); Lm=length_full(tr-h,tp,extra_base_palm=True); return [(Lp[i]-Lm[i])/(2*h) for i in range(3)]
def dLfull_dp(tr,tp):
    Lp=length_full(tr,tp+h,extra_base_palm=True); Lm=length_full(tr,tp-h,extra_base_palm=True); return [(Lp[i]-Lm[i])/(2*h) for i in range(3)]
m2=[(a-b)/(2*h) for a,b in zip(dLfull_dp(tr+h,tp),dLfull_dp(tr-h,tp))]
print("  with base->palm segment d2L/drdp:",[f"{v*1000:.3e}" for v in m2],"(nonzero -> R_rp would depend on both angles; single-variable decoupling broken)")

# ---------------- D. identifiability: phase coupling numerics ----------------
print("\nD. phase-coupling equivalence demo on C2 roll segment")
A,B,C=params["cables"][1]["roll_ABC_m2"]
delta=math.radians(3.7)
Bp=B*math.cos(delta)+C*math.sin(delta)
Cp=-B*math.sin(delta)+C*math.cos(delta)
mx=0.
for deg in range(-25,26):
    th=math.radians(deg)
    D1=A+B*math.cos(th)+C*math.sin(th)
    D2=A+Bp*math.cos(th+delta)+Cp*math.sin(th+delta)
    mx=max(mx,abs(D1-D2))
print(f"  max|D(theta;beta,gamma) - D(theta+delta;beta',gamma')| over roll in [-25,25]deg: {mx:.3e} m^2 (should be ~0)")

# ---------------- E. sensitivity partials numeric check ----------------
print("\nE. analytic partials of r vs finite differences (C2 roll, theta=15deg)")
th=math.radians(15.)
def r_of(A,B,C,th):
    D=A+B*math.cos(th)+C*math.sin(th)
    return (B*math.sin(th)-C*math.cos(th))/(2*math.sqrt(D))
eps=1e-7
D_=A+B*math.cos(th)+C*math.sin(th); N=B*math.sin(th)-C*math.cos(th)
ana_da=-N/(4*D_**1.5)
ana_db=math.sin(th)/(2*math.sqrt(D_))-N*math.cos(th)/(4*D_**1.5)
ana_dc=-math.cos(th)/(2*math.sqrt(D_))-N*math.sin(th)/(4*D_**1.5)
ana_dth=None
fd_da=(r_of(A+eps,B,C,th)-r_of(A-eps,B,C,th))/(2*eps)
fd_db=(r_of(A,B+eps,C,th)-r_of(A,B-eps,C,th))/(2*eps)
fd_dc=(r_of(A,B,C+eps,th)-r_of(A,B,C-eps,th))/(2*eps)
print(f"  dr/dalpha: ana={ana_da:.9e} fd={fd_da:.9e}")
print(f"  dr/dbeta : ana={ana_db:.9e} fd={fd_db:.9e}")
print(f"  dr/dgamma: ana={ana_dc:.9e} fd={fd_dc:.9e}")
