import json, math
d = json.load(open(r"复核数据_extracted\复核数据\model_parameters.json", encoding="utf-8"))
P = {p["id"]: p["zero_model_m"] for p in d["points"]}
A=P["C1-P04"]; B=P["C1-P05"]
a=(0,1,0); o=(0,0,0)
def sub(x,y): return [x[i]-y[i] for i in range(3)]
def dot(x,y): return sum(x[i]*y[i] for i in range(3))
u=sub(A,o); v=sub(B,o)
d3=sub(B,A); L=math.sqrt(dot(d3,d3))
vel=[a[1]*v[2]-a[2]*v[1], a[2]*v[0]-a[0]*v[2], a[0]*v[1]-a[1]*v[0]]
print("L =",L, " D(0)^0.5 =", math.sqrt(364.5-182.5))
print("u", [round(x,6) for x in u], "v", [round(x,6) for x in v])
print("velocity a x v =", [round(x,6) for x in vel])
print("u_hat . vel =", dot(d3,vel)/L)
print("analytic r(0) =", -7/(2*math.sqrt(182)))
print("3D distance axis-to-line =", abs(dot(u,[0,1,0])*0 + dot(A,[ (1*13-0*3)/L, 0, (0*3-1*2)/L ])))
