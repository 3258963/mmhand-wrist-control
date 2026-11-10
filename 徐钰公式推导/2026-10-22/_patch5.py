import io
p = "讲解_αβγ图.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace('axA.text(-1.28, 1.28, "b = ‖v⊥‖"', 'axA.text(-1.62, 1.22, "b = ‖v⊥‖"')
s = s.replace('''axB.annotate("零位 θ=0：D=215.25\\nr(0)=−γ/(2√D)=−22.05", xy=(0, al + be), xytext=(52, 2050),
             fontsize=10, color="#7b3fa0",
             arrowprops=dict(arrowstyle="->", color="#7b3fa0", lw=1.0))''',
'''axB.annotate("零位 θ=0 时 D=215.25，\\n力臂 r(0)=−γ/(2√D)=−22.05", xy=(0, al + be), xytext=(62, 480),
             fontsize=10, color="#7b3fa0",
             arrowprops=dict(arrowstyle="->", color="#7b3fa0", lw=1.0))''')
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
