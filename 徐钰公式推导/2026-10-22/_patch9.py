import io
p = "讲解_αβγ定义图.py"
s = io.open(p, encoding="utf-8").read()

s = s.replace('''ax1.text((A[0] + B[0]) / 2, 0.42, "u∥ − v∥（沿轴错位）", fontsize=10, color="#2e8b57",
         ha="center")''',
'''ax1.text((A[0] + B[0]) / 2, -0.52, "u∥ − v∥（沿轴错位）", fontsize=10, color="#2e8b57",
         ha="center")''')

s = s.replace('ax1.text(2.34, -0.86, "v", fontsize=12, color="#e07b1a")',
              'ax1.text(1.92, -0.98, "v", fontsize=12, color="#e07b1a")')

s = s.replace('ax1.text(-0.25, -0.36, "o（轴上任意一点）", fontsize=10, color="#333", ha="left")',
              'ax1.text(-0.30, -0.62, "o（轴上一点）", fontsize=10, color="#333", ha="left")')

s = s.replace('ax2.text(-2.85, 1.10, "B 转一圈的轨迹", fontsize=9.5, color="#999", rotation=88, va="center")',
              'ax2.text(-0.10, 2.10, "B 转一圈的轨迹", fontsize=9.5, color="#999", ha="center")')
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
