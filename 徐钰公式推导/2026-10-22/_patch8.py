import io
p = "讲解_绳长到力臂图.py"
s = io.open(p, encoding="utf-8").read()
start = s.index('axT.text(0.0, 0.02, "一句话：')
end = s.index('fig.savefig("讲解图_绳长只是中间量.png"')
s = s[:start] + s[end:]
io.open(p, "w", encoding="utf-8").write(s)
print("removed bottom box")
