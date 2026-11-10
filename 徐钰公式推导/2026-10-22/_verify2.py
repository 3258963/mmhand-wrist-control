import json
d = json.load(open(r"复核数据_extracted\复核数据\model_parameters.json", encoding="utf-8"))
print(json.dumps(d["cables"], ensure_ascii=False, indent=1)[:2000])
print("frame:", json.dumps(d["frame"], ensure_ascii=False))
