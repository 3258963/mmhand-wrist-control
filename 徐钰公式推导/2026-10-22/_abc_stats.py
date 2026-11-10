import math, json
d = json.load(open(r"复核数据_extracted\复核数据\model_parameters.json", encoding="utf-8"))
print("%-3s %-6s %12s %12s %12s %10s %10s %10s %9s %8s" % ("绳","段","α","β","γ","ρ","α-ρ","s_min","s_max","ρ/α"))
for c in d["cables"]:
    for tag,key in (("roll","roll_ABC_m2"),("pitch","pitch_ABC_m2")):
        al,be,ga=[v*1e6 for v in c[key]]
        rho=math.hypot(be,ga)
        print("%-3s %-6s %12.4f %12.4f %12.4f %10.4f %10.4f %10.4f %9.4f %8.4f" % (
            c["id"],tag,al,be,ga,rho,al-rho,math.sqrt(al-rho),math.sqrt(al+rho),rho/al))
        print("     φ0=%8.3f deg, r(0)=%+9.5f mm" % (math.degrees(math.atan2(ga,be)), -ga/(2*math.sqrt(al+be))))
