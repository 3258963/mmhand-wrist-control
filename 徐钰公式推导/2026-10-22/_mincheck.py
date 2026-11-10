import json, math
d = json.load(open(r"复核数据_extracted\复核数据\model_parameters.json", encoding="utf-8"))
rows=[]
for c in d["cables"]:
    i=c["id"][1]
    for tag,key,rng in (("roll","roll_ABC_m2",(-25,25)),("pitch","pitch_ABC_m2",(-25,45))):
        al,be,ga = c[key]
        rho=math.hypot(be,ga); phi=math.degrees(math.atan2(ga,be))
        Dmin=al-rho
        # scan for min on range
        best=(1e9,None)
        for n in range(0,70001):
            th=rng[0]+(rng[1]-rng[0])*n/70000.0
            D=al+be*math.cos(math.radians(th))+ga*math.sin(math.radians(th))
            if D<best[0]: best=(D,th)
        print("%s/%-5s alpha-rho=%12.4f  -> s_ideal=%8.6f  at theta=%+8.3f deg (range %d..%d) | min on range s=%8.6f at %+.6f deg"
              % (c["id"],tag,Dmin*1e6, math.sqrt(Dmin)*1e3, phi+180 if phi+180<=180 else phi-180, rng[0],rng[1], math.sqrt(best[0])*1e3, best[1]))
