import io
p = "讲解_绳长到力臂图.py"
s = io.open(p, encoding="utf-8").read()
old = '''items = [
    ("绳长 s", "这根绳现在多长？\\n→ 电机要收放多少线\\n→ 会不会短到危险", "#d9822b"),
    ("力臂 r", "每 1 N 张力\\n给关节多大扭矩？\\n→ 控制真正用这个", "#c0392b"),
    ("力矩 τ", "三根绳加起来\\n关节实际受多大力？\\nτ = R·f", "#7b3fa0"),
]'''
new = '''items = [
    ("绳长 s", "现在多长？→ 决定收放线量\\n→ 会不会短到危险", "#d9822b"),
    ("力臂 r", "每 1 N 给多大扭矩？\\n→ 控制真正用这个", "#c0392b"),
    ("力矩 τ", "关节实际受多大力？\\nτ = R·f", "#7b3fa0"),
]'''
assert old in s
s = s.replace(old, new)
s = s.replace("    y -= 0.215", "    y -= 0.245")
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
