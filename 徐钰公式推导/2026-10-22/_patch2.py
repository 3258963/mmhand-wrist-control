import io
p = "讲解_解耦公式图.py"
lines = io.open(p, encoding="utf-8").read().split("\n")
out = [l for l in lines if not l.startswith('ax2.text(5.0, 5.90, "为什么能')]
io.open(p, "w", encoding="utf-8").write("\n".join(out))
print("removed", len(lines)-len(out), "line(s)")
