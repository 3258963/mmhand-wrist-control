import io
p = "计算示例_一根绳.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace("import math\n", "import math\nimport sys\n\nif hasattr(sys.stdout, \"reconfigure\"):\n    sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"replace\")\n", 1)
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
