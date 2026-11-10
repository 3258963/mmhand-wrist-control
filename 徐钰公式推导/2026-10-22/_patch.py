import io, re
p = "讲解_解耦公式图.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace('ax2.text(5.1, 5.95, "为什么能“消掉”一个角"', 'ax2.text(5.1, 5.55, "为什么能“消掉”一个角"')
s = s.replace('ax2.text(5.1, 5.30, "‖Q_r·w‖ = ‖w‖"', 'ax2.text(5.1, 4.95, "‖Q_r·w‖ = ‖w‖"')
s = s.replace('ax2.text(5.1, 4.75, "旋转只改方向', 'ax2.text(5.1, 4.40, "旋转只改方向')
io.open(p, "w", encoding="utf-8").write(s)
print("patched")
