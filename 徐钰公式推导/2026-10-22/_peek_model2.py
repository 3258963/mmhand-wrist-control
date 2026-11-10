import json, math, sys
sys.path.insert(0, r"复核数据_extracted\复核数据")
import geometry_model as gm
import inspect
print(inspect.signature(gm.WristGeometry.__init__))
print([n for n in dir(gm.WristGeometry) if not n.startswith("_")])
print(inspect.getsource(gm.WristGeometry)[:1500])
