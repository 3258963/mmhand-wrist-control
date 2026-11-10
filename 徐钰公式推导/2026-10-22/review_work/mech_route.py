"""Independent vector-mechanics route: torque = a . [(P_moving - o) x (-f u)] per crossing segment.
Compare with R from analytic closed form at generic poses. Also verify constant lengths c_i."""
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
pts=[tuple(p["zero_model_m"]) for p in params["points"]]
body=[p["body"] for p in params["points"]]

# constant length check: sum of 5 same-body segments per cable at zero
print("1. constant lengths c_i (mm): json vs my polyline sum of 5 same-body segments")
for ci,cab in enumerate(params["cables"]):
    s=0.
    for k in (0,1,2,4,6):  # P1P2,P2P3,P3P4,P5P6,P7P8
        i=ci*8+k; s+=vnorm(vsub(pts[i+1],pts[i]))
    print(f"   {cab['id']}: mine={s*1000:.10f} json={cab['constant_length_m']*1000:.10f}")

def pose(tr,tp):
    out=[]
    for p0,b in zip(pts,body):
        if b=="base": out.append(p0)
        elif b=="roll_link": out.append(rot_about(p0,ar,orr,tr))
        else:
            q=rot_about(p0,ar,orr,tr)
            ap=rodrigues(ap0,ar,tr); op=rot_about(op0,ar,orr,tr)
            out.append(rot_about(q,ap,op,tp))
    return out

def R_mech(tr,tp):
    """R[j][i] per pure tension 1N: roll torque from segment P4P5 about roll axis;
    pitch torque from segment P6P7 about (roll-carried) pitch axis."""
    P=pose(tr,tp)
    ap=rodrigues(ap0,ar,tr); op=rot_about(op0,ar,orr,tr)
    rr=[]; rp=[]
    for c in range(3):
        u45=vsub(P[c*8+4],P[c*8+3]); u45=vmul(u45,1/vnorm(u45))
        tau_roll=vdot(ar,vcross(vsub(P[c*8+4],orr),vmul(u45,-1.)))
        u67=vsub(P[c*8+6],P[c*8+5]); u67=vmul(u67,1/vnorm(u67))
        tau_pitch=vdot(ap,vcross(vsub(P[c*8+6],op),vmul(u67,-1.)))
        rr.append(tau_roll); rp.append(tau_pitch)
    return rr,rp

def R_abc(tr,tp):
    rr,rp=[],[]
    for cab in params["cables"]:
        for w,abc,th in (("r",cab["roll_ABC_m2"],tr),("p",cab["pitch_ABC_m2"],tp)):
            A,B,C=abc; D=A+B*math.cos(th)+C*math.sin(th)
            (rr if w=="r" else rp).append((B*math.sin(th)-C*math.cos(th))/(2*math.sqrt(D)))
    return rr,rp

print("\n2. torque-mechanics R vs closed-form R at several poses (mm), plus zero pose")
for (dr,dp) in ((0.,0.),(7.3,-11.1),(-19.0,33.0),(25.,45.)):
    tr,tp=math.radians(dr),math.radians(dp)
    rm=R_mech(tr,tp); ra=R_abc(tr,tp)
    mx=max(abs(a-b) for a,b in zip(rm[0]+rm[1],ra[0]+ra[1]))
    print(f"   pose({dr},{dp}): max|R_mech - R_abc| = {mx*1000:.3e} mm")
print("   zero pose R_mech (mm):")
rm=R_mech(0.,0.)
print("   roll :",[f"{v*1000:.8f}" for v in rm[0]])
print("   pitch:",[f"{v*1000:.8f}" for v in rm[1]])
print("   doc:   [-0.25943726, -22.04970101, 17.37198247] / [-58.10461556, 11.80488412, 10.99035112]")
