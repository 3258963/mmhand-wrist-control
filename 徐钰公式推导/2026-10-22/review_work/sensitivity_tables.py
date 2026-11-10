"""Final checks: doc §C3 tables (+1mm trial, gradient norms), axis-origin sensitivities,
two 24mm-offset conventions, and the -25deg 0.05mm-budget example."""
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

ar=(0.,1.,0.); ap0=(1.,0.,0.)
base_pts=[tuple(p["zero_model_m"]) for p in params["points"]]
body=[p["body"] for p in params["points"]]
PIDS=[p["id"] for p in params["points"]]

def R_vector(pts, orr=(0.,0.,0.), op0=(0.,0.,0.024), tr=0., tp=0., h=1e-6):
    def length(tr,tp):
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
    Lp=length(tr+h,tp); Lm=length(tr-h,tp)
    rr=[-(Lp[i]-Lm[i])/(2*h) for i in range(3)]
    Lp=length(tr,tp+h); Lm=length(tr,tp-h)
    rp=[-(Lp[i]-Lm[i])/(2*h) for i in range(3)]
    return rr,rp   # meters

def shift_pt(pts,i,d): 
    q=list(pts); p=list(q[i]); p[0]+=d[0]; p[1]+=d[1]; p[2]+=d[2]; q[i]=tuple(p); return q

print("A. zero-pose single-point +1mm trial: max|dR| (mm); doc P04:1.3432/1.7841/1.7050 P05:0.3621/0.8798/0.8939 P06:0.7609/1.4146/1.3120 P07:0.1395/0.3748/0.3489")
r0=R_vector(base_pts)
for pid in ("C1-P04","C2-P04","C3-P04","C1-P05","C2-P05","C3-P05","C1-P06","C2-P06","C3-P06","C1-P07","C2-P07","C3-P07"):
    i=PIDS.index(pid); row=[]
    for d in ((0.001,0,0),(0,0.001,0),(0,0,0.001)):
        r1=R_vector(shift_pt(base_pts,i,d))
        for j in (0,1):
            for c in range(3): row.append(abs(r1[j][c]-r0[j][c])*1000)
    print(f"   {pid}: max = {max(row):.4f}")

print("\nB. zero-pose position-gradient norms (mm/mm); doc P04:1.3469/2.0380/2.1996 P05:0.3720/1.1154/1.2376 P06:0.8194/1.3979/1.3253 P07:0.1813/0.3982/0.4475")
hs=1e-4
for pid in ("C1-P04","C2-P04","C3-P04","C1-P05","C2-P05","C3-P05","C1-P06","C2-P06","C3-P06","C1-P07","C2-P07","C3-P07"):
    i=PIDS.index(pid); cable=int(pid[1])-1
    g=[[[0.]*3 for _ in range(2)] for _ in range(1)]  # per joint row gradients of R_{row,cable}
    grows=[]
    for j in (0,1):
        gg=[]
        for ax in (0,1,2):
            dv=[0.,0.,0.]; dv[ax]=hs
            rp=R_vector(shift_pt(base_pts,i,dv)); rm=R_vector(shift_pt(base_pts,i,tuple(-x for x in dv)))
            gg.append((rp[j][cable]-rm[j][cable])/(2*hs))
        grows.append(vnorm(gg))
    combined=math.sqrt(grows[0]**2+grows[1]**2)
    print(f"   {pid}: roll={grows[0]:.4f} pitch={grows[1]:.4f} combined={combined:.4f}")

print("\nC. axis-origin dR/doY at zero, endpoints fixed (mm/mm); doc pitch: 0.982605/0.999355/0.930400, roll: 0")
for name,axis_o,which in (("roll",None,"r"),("pitch",None,"p")):
    if which=="r":
        def mk(dy): return R_vector(base_pts, orr=(0.,dy,0.))
    else:
        def mk(dy): return R_vector(base_pts, op0=(0.,dy,0.024))
    rp=mk(+hs); rm=mk(-hs)
    vals=[(rp[j][c]-rm[j][c])/(2*hs)*1 for j,c in ((0,0),(0,1),(0,2))] if which=="r" else \
         [(rp[1][c]-rm[1][c])/(2*hs) for c in range(3)]
    print(f"   {name} row dR/doY:",[f"{v:.6f}" for v in vals])

print("\nD. 24mm-offset conventions (dR_pitch per mm Z-shift); doc conv1: 0.185592/0.031230/0.029075 conv2: 0.151958/0.043892/0.132267")
# conv1: only pitch axis origin moves in Z
rp=R_vector(base_pts, op0=(0.,0.,0.024+hs)); rm=R_vector(base_pts, op0=(0.,0.,0.024-hs))
conv1=[(rp[1][c]-rm[1][c])/(2*hs) for c in range(3)]
# conv2: axis origin and both palm points of each cable move together in Z
palm_idx=[PIDS.index(f"C{k}-P0{n}") for k in (1,2,3) for n in (7,8)]
pts2=list(base_pts)
for i in palm_idx:
    p=list(pts2[i]); p[2]+=hs; pts2[i]=tuple(p)
rp=R_vector(pts2, op0=(0.,0.,0.024+hs))
pts2=list(base_pts)
for i in palm_idx:
    p=list(pts2[i]); p[2]-=hs; pts2[i]=tuple(p)
rm=R_vector(pts2, op0=(0.,0.,0.024-hs))
conv2=[(rp[1][c]-rm[1][c])/(2*hs) for c in range(3)]
print("   conv1:",[f"{v:.6f}" for v in conv1])
print("   conv2:",[f"{v:.6f}" for v in conv2])

print("\nE. budget example at (0,-25deg): 0.05*(||grad P06 R_p1|| + ||grad P07 R_p1||); doc ~1.5246 mm")
tp=math.radians(-25.)
def grad_Rp1_of(i):
    gg=[]
    for ax in (0,1,2):
        dv=[0.,0.,0.]; dv[ax]=hs
        a=R_vector(shift_pt(base_pts,i,dv),tp=tp)[1][0]
        b=R_vector(shift_pt(base_pts,i,tuple(-x for x in dv)),tp=tp)[1][0]
        gg.append((a-b)/(2*hs))
    return vnorm(gg)
g6=grad_Rp1_of(PIDS.index("C1-P06")); g7=grad_Rp1_of(PIDS.index("C1-P07"))
print(f"   ||grad P06||={g6:.4f} ||grad P07||={g7:.4f} budget={0.05*(g6+g7):.4f} mm (doc 1.5246)")
