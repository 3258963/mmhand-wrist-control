import json, math
d = json.load(open(r"复核数据_extracted\复核数据\model_parameters.json", encoding="utf-8"))
P = {p["id"]: p["zero_model_m"] for p in d["points"]}
axes = d["axes"]
print("axes:", json.dumps(axes, ensure_ascii=False))
def sub(a,b): return [a[i]-b[i] for i in range(3)]
def dot(a,b): return sum(a[i]*b[i] for i in range(3))
def cross(a,b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def abc(A,B,o,a):
    u=sub(A,o); v=sub(B,o)
    alpha = dot(u,u)+dot(v,v)-2*dot(u,a)*dot(v,a)
    beta  = -2*(dot(u,v)-dot(u,a)*dot(v,a))
    gamma = -2*dot(u,cross(a,v))
    return alpha,beta,gamma
def r(th, al,be,ga):
    D = al+be*math.cos(th)+ga*math.sin(th)
    return (be*math.sin(th)-ga*math.cos(th))/(2*math.sqrt(D)), math.sqrt(D)
rows=[]
for c in d["cables"]:
    cr=c["cable"]
    A=P[f"C{cr}-P04"]; B=P[f"C{cr}-P05"]
    ro=axes["roll"]["origin"] if isinstance(axes["roll"],dict) else None
    print("----", c["id"])
    print("cable keys:", list(c.keys()))
    break
