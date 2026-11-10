import io
p = "讲解_αβγ定义图.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace('ax2.text(-0.10, 2.10, "B 转一圈的轨迹", fontsize=9.5, color="#999", ha="center")',
              'ax2.text(0.30, 2.42, "B 转一圈的轨迹", fontsize=9.5, color="#999", ha="left")')
s = s.replace('ax1.text(-1.4, 2.95, "投影长度：u⊥ = ‖u‖·sin，u∥ = a·u", fontsize=9.5, color="#777")',
              'ax1.text(-1.4, 2.95, "沿轴分量 u∥ = (a·u)·a ；垂直分量 u⊥ = u − u∥", fontsize=9.5, color="#777")')
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
