import json
p = r"复核数据_extracted\复核数据\model_parameters.json"
d = json.load(open(p, encoding="utf-8"))
def walk(o, pre="", depth=0):
    if depth>1: return
    if isinstance(o, dict):
        for k,v in o.items():
            if isinstance(v,(dict,list)):
                print(pre+k, type(v).__name__, (len(v) if hasattr(v,"__len__") else ""))
                walk(v, pre+k+".", depth+1)
            else:
                print(pre+k, "=", v)
    elif isinstance(o, list):
        print(pre, "list len", len(o), "first:", str(o[0])[:200] if o else "")
walk(d)
