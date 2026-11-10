import io
p = "计算示例_一根绳.py"
s = io.open(p, encoding="utf-8").read()
old = '''    print(f"{'绳':<4}{'c_i':>12}   段      {'α':>14}{'β':>14}{'γ':>12}")
    print("-" * 66)'''
new = '''    print(f"{'绳':<4}{'c_i':>12}   段   {'α':>16}{'β':>16}{'γ':>14}")
    print("-" * 68)'''
assert old in s
s = s.replace(old, new)
old2 = '''        print(f"{name:<4}{c:>12.6f}  roll  {cr[0]:>14.8f}{cr[1]:>14.8f}{cr[2]:>12.8f}")
        print(f"{'':<4}{'':>12}  pitch {cp[0]:>14.8f}{cp[1]:>14.8f}{cp[2]:>12.8f}")'''
new2 = '''        print(f"{name:<4}{c:>12.6f}  roll  {cr[0]:>16.6f}{cr[1]:>16.6f}{cr[2]:>14.6f}")
        print(f"{'':<4}{'':>12}  pitch {cp[0]:>16.6f}{cp[1]:>16.6f}{cp[2]:>14.6f}")'''
assert old2 in s
s = s.replace(old2, new2)
old3 = '''    print()
    print("零位（θr=θp=0）力臂矩阵 R / mm")'''
new3 = '''    print()
    print("注：这里用附录里 6 位小数的坐标；与全精度 JSON 相比，系数末几位差 1e-5 量级，属正常。")
    print()
    print("零位（θr=θp=0）力臂矩阵 R / mm")'''
assert old3 in s
s = s.replace(old3, new3)
io.open(p, "w", encoding="utf-8").write(s)
print("patched")
