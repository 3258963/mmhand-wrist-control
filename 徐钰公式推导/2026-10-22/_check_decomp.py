import math, sys
sys.path.insert(0, r"复核数据_extracted\复核数据")
import geometry_model as gm
g = gm.WristGeometry.load()
def polylen(xyz, i):
    # points for cable i in order
    pts=[p for p in g.p['points'] if p['cable']==i]
    pts.sort(key=lambda p:p['order'])
    idx=[g.p['points'].index(p) for p in pts]
    L=0
    for a,b in zip(idx, idx[1:]):
        L+=math.dist(xyz[a],xyz[b])
    return L
for (rd,pd) in [(0,0),(4,-25),(-25,-25),(25,45)]:
    out=g.evaluate_degrees(rd,pd)
    print("angles", rd, pd)
    for i in (1,2,3):
        cat=out['lengths_m'][i-1]
        raw=polylen(out['points_world_m'], i)
        print("  C%d  c+sr+sp=%.9f mm  raw polyline=%.9f mm  diff=%.2e" % (i, cat*1e3, raw*1e3, cat-raw))
    print("  R mm:", [[round(v*1e3,6) for v in row] for row in out['R_m']])
