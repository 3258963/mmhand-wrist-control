import io
p = "讲解_绳长到力臂图.py"
s = io.open(p, encoding="utf-8").read()

s = s.replace('axP.set_ylim(0, 26)', 'axP.set_ylim(-4, 26)')
s = s.replace('axP.text(50, 0.2, "绳长走到第 ② 步就够了吗？不够——控制要的是第 ③ 步的力臂",',
              'axP.text(50, -2.2, "绳长走到第 ② 步就够了吗？不够——控制要的是第 ③ 步的力臂",')

s = s.replace('axR.set_ylim(-24, 24)', 'axR.set_ylim(-28, 24)')
s = s.replace('''axR.annotate("同一姿态：r = −19.64 mm\\n（负号 = 张力阻碍正转）",
             xy=(t0, float(r_of(np.radians(t0)))), xytext=(18, -20),''',
'''axR.annotate("同一姿态：r = −19.64 mm\\n（负号 = 张力阻碍正转）",
             xy=(t0, float(r_of(np.radians(t0)))), xytext=(24, -26),''')

s = s.replace('''y = 0.80
for name, body, col in items:
    axT.text(0.02, y, name, fontsize=12, color=col, va="top", fontweight="bold")
    axT.text(0.02, y - 0.055, body, fontsize=10, color="#555", va="top", linespacing=1.65)
    y -= 0.26''',
'''y = 0.86
for name, body, col in items:
    axT.text(0.02, y, name, fontsize=12, color=col, va="top", fontweight="bold")
    axT.text(0.02, y - 0.055, body, fontsize=10, color="#555", va="top", linespacing=1.65)
    y -= 0.215''')
io.open(p, "w", encoding="utf-8").write(s)
print("patched")
