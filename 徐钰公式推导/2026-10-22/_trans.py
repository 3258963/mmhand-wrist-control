import math, sys
sys.path.insert(0, ".")
sys.argv = ["x"]
import importlib.util
spec = importlib.util.spec_from_file_location("d", "计算_不用系数.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for tr in (0, 20):
    trr = math.radians(tr)
    p6 = m.point_pos(m.P["C1"][5], "roll_link", trr, 0.0)
    p7 = m.point_pos(m.P["C1"][6], "palm", trr, 0.0)
    print("roll=%2d  P6=(%.3f, %.3f, %.3f)  P7=(%.3f, %.3f, %.3f)  |P7-P6|=%.6f"
          % (tr, *p6, *p7, math.dist(p6, p7)))
p70 = m.P["C1"][6]
print("P7 位移量 =", round(math.dist(m.point_pos(p70,"palm",math.radians(20),0.0), p70), 3), "mm")
