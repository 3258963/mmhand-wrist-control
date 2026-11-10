"""Corrected phase identity + mixed-partial noise scaling + continuous minimum verification."""
import json, math

MP="复核数据_extracted/复核数据/model_parameters.json"
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
pts=[p["zero_model_m"] for p in params["points"]]
body=[p["body"] for p in params["points"]]
def length_full(tr,tp):
    out=[]
    for p0,b in zip(pts,body):
        if b=="base": out.append(p0)
        elif b=="roll_link": out.append(rot_about(p0,ar,orr,tr))
        else:
            q=rot_about(p0,ar,orr,tr)
            ap=rodrigues(ap0,ar,tr); op=rot_about(op0,ar,orr,tr)
            out.append(rot_about(q,ap,op,tp))
    tot=[0.,0.,0.]
    for c in range(3):
        s=0.
        for k in range(7):
            i=c*8+k; s+=vnorm(vsub(out[i+1],out[i]))
        tot[c]=s
    return tot

# ---- 1. corrected phase identity: A+B cos(q+d)+C sin(q+d) == A+Bp cos q+Cp sin q ----
print("1. phase identity (doc form): max over q in [-25,25]deg, C2 roll")
A,B,C=params["cables"][1]["roll_ABC_m2"]
delta=math.radians(3.7)
Bp=B*math.cos(delta)+C*math.sin(delta)
Cp=C*math.cos(delta)-B*math.sin(delta)
mx=0.
for deg in range(-2500,2501):
    q=deg/100.0*math.pi/180
    D1=A+B*math.cos(q+delta)+C*math.sin(q+delta)
    D2=A+Bp*math.cos(q)+Cp*math.sin(q)
    mx=max(mx,abs(D1-D2))
print(f"   max|D1-D2| = {mx:.3e} m^2")

# ---- 2. mixed-partial noise scaling for C1 ----
print("\n2. mixed second partial of L_C1 w.r.t. (roll,pitch) via nested central diff, various h")
tr,tp=math.radians(7.3),math.radians(-11.1)
for h in (1e-3,1e-4,1e-5,1e-6):
    def dL_dp(t):
        Lp=length_full(t,tp+h); Lm=length_full(t,tp-h); return Lp[0]-Lm[0]
    mixed=(dL_dp(tr+h)-dL_dp(tr-h))/(4*h)
    print(f"   h={h:.0e}: d2L1/drdp = {mixed*1000:+.3e} mm/rad^2")
print("   (theory: identically 0; value should scale ~1/h^2 as h shrinks => pure fp noise)")

# ---- 3. continuous minimum of s and D per segment over working range ----
print("\n3. continuous min of s over working angle ranges (doc table C1..C3)")
ranges={"roll":(-25.,25.),"pitch":(-25.,45.)}
docmin={"C1/roll":(13.485763,-2.196570),"C1/pitch":(3.900609,-25.0),
        "C2/roll":(10.485589,-18.488231),"C2/pitch":(11.890136,33.830498),
        "C3/roll":(14.692202,15.149529),"C3/pitch":(13.445385,33.830498)}
def min_over(abc,lo,hi):
    A,B,C=abc
    # D' = -B sin + C cos =0 -> tan = C/B ; candidates: theta0=atan2(C,B) and theta0+pi; plus endpoints
    cands=[math.radians(lo),math.radians(hi)]
    t0=math.atan2(C,-B)  # solve -B sin th + C cos th = 0 -> tan th = C/B -> th = atan2(C,B)+k*pi
    t1=math.atan2(C,B)
    for t in (t1,t1+math.pi,t1-math.pi):
        if math.radians(lo)-1e-12<=t<=math.radians(hi)+1e-12: cands.append(t)
    best=(1e18,None)
    for t in cands:
        D=A+B*math.cos(t)+C*math.sin(t)
        if 0<D<best[0]: best=(D,t)
    return math.sqrt(best[0])*1000, math.degrees(best[1])
for ci,cab in enumerate(params["cables"]):
    for seg in ("roll","pitch"):
        lo,hi=ranges[seg]
        smin,ang=min_over(cab[f"{seg}_ABC_m2"],lo,hi)
        ds,da=docmin[f"{cab['id']}/{seg}"]
        flag="OK" if abs(smin-ds)<2e-6 else "MISMATCH"
        print(f"   {cab['id']}/{seg}: mine min s={smin:.6f} mm at {ang:.6f} deg; doc {ds:.6f} at {da:.6f} deg [{flag}]")

# ---- 4. C1 pitch gradient at -25deg (P06 +1mm Z finite change 16.064268 claim) ----
print("\n4. P06 finite +1mm F0-Z shift effect on R_pitch_C1 at pitch=-25deg (doc: 16.064268 mm)")
p06_i=[i for i,p in enumerate(params["points"]) if p["id"]=="C1-P06"][0]
def R_pitch_C1(pz, tr=0., tp=math.radians(-25.)):
    pts2=list(pts); p=list(pts2[p06_i]); p[2]+=pz; pts2[p06_i]=tuple(p)
    def lf(tr,tp):
        out=[]
        for j,(p0,b) in enumerate(zip(pts2,body)):
            if b=="base": out.append(p0)
            elif b=="roll_link": out.append(rot_about(p0,ar,orr,tr))
            else:
                q=rot_about(p0,ar,orr,tr)
                ap=rodrigues(ap0,ar,tr); op=rot_about(op0,ar,orr,tr)
                out.append(rot_about(q,ap,op,tp))
        s=0.
        for k in range(7):
            i=k; s+=vnorm(vsub(out[i+1],out[i]))
        return s
    h=1e-6
    return -(lf(tr,tp+h)-lf(tr,tp-h))/(2*h)
r0=R_pitch_C1(0.); r1=R_pitch_C1(0.001)
print(f"   finite change = {(r1-r0)*1000:.6f} mm (doc 16.064268)")
# symmetric local derivative
rm=R_pitch_C1(-0.0005); rp=R_pitch_C1(0.0005)
print(f"   symmetric local dR/dz = {(rp-rm)/0.001*1:.6f} mm/mm (doc 15.185639)")
EOF_MARKER_NOT_USED=0
