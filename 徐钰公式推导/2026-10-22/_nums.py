import math
c1=0.0806754857664318
sr=lambda th: math.sqrt(0.00036449999999997856-0.00018249999999996568*math.cos(th)+7e-6*math.sin(th))
sp=lambda th: math.sqrt(0.007263473647415658-0.006537666031418207*math.cos(th)+0.003130771619422389*math.sin(th))
for r,p in [(0,0),(4,-25)]:
    R=math.radians(r); P=math.radians(p)
    print(r,p,"sr=%.6f sp=%.6f c=%.6f total=%.6f mm"%(sr(R)*1e3, sp(P)*1e3, c1*1e3, (c1+sr(R)+sp(P))*1e3))
