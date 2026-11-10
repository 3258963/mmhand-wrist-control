import json, math
d = json.load(open(r"复核数据_extracted\复核数据\model_parameters.json", encoding="utf-8"))
P = {p["id"]: p["zero_model_m"] for p in d["points"]}
def sub(a,b): return [a[i]-b[i] for i in range(3)]
def dot(a,b): return sum(a[i]*b[i] for i in range(3))
def cross(a,b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def abc(A,B,o,a):
    u=sub(A,o); v=sub(B,o)
    return (dot(u,u)+dot(v,v)-2*dot(u,a)*dot(v,a),
            -2*(dot(u,v)-dot(u,a)*dot(v,a)),
            -2*dot(u,cross(a,v)))
o_r=[0,0,0]; a_r=[0,1,0]
o_p=[0,0,0.024]; a_p=[1,0,0]
print("%-6s %-10s %14s %14s %14s | %12s %12s %12s" % ("cable","axis","alpha mm2","beta mm2","gamma mm2","ref_a","ref_b","ref_g"))
R=[]
for c in d["cables"]:
    i=c["id"][1]
    for tag,(A,B,o,a,key) in {"roll":(f"C{i}-P04",f"C{i}-P05",o_r,a_r,"roll_ABC_m2"),
                              "pitch":(f"C{i}-P06",f"C{i}-P07",o_p,a_p,"pitch_ABC_m2")}.items():
        al,be,ga = abc(P[A],P[B],o,a)
        ref = c[key]
        print("%-6s %-10s %14.6f %14.6f %14.6f | %12.6f %12.6f %12.6f" % (c["id"],tag,al*1e6,be*1e6,ga*1e6,ref[0]*1e6,ref[1]*1e6,ref[2]*1e6))
        D = al+be
        r0 = -ga/(2*math.sqrt(D))
        R.append((c["id"],tag,al,be,ga,r0*1e3, math.sqrt(D)*1e3))
print()
for row in R:
    print("%-3s %-6s alpha=%12.6f mm2 beta=%12.6f gamma=%12.6f  s(0)=%9.6f mm  r(0)=%+11.8f mm" % row)
print()
print("R(0) roll row:", ["%+.8f"%row[5] for row in R if row[1]=="roll"])
print("R(0) pitch row:", ["%+.8f"%row[5] for row in R if row[1]=="pitch"])
# arc-length sweep check of r formula vs numerical derivative
def r(th, al,be,ga):
    return (be*math.sin(th)-ga*math.cos(th))/(2*math.sqrt(al+be*math.cos(th)+ga*math.sin(th)))
for row in R:
    _,tag,al,be,ga,_,_ = row
    for th in (-0.3, 0.0, 0.5):
        h=1e-7
        f=lambda t: math.sqrt(al+be*math.cos(t)+ga*math.sin(t))
        num = -(f(th+h)-f(th-h))/(2*h)
        print("%-6s %-6s th=%+.1f  r_analytic=%+.9f  -dl/dth=%+.9f  diff=%.2e" % (row[0],tag,th,r(th,al,be,ga),num,abs(r(th,al,be,ga)-num)))
