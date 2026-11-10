# -*- coding: utf-8 -*-
"""C2 / roll：绳长 s(θ) 与力臂 r(θ) 曲线。"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

al, be, ga = 2150.25, -1935.0, 647.0
th = np.linspace(-40, 100, 400) * np.pi / 180

s2 = al + be * np.cos(th) + ga * np.sin(th)
s = np.sqrt(s2)
r = (be * np.sin(th) - ga * np.cos(th)) / (2 * s)

fig, ax1 = plt.subplots(figsize=(9.6, 5.4), dpi=190)

ax1.plot(th * 180 / np.pi, s, color="#0891b2", lw=2.6, label="绳长 s (mm)")
ax1.set_xlabel("θ (°)", fontsize=11)
ax1.set_ylabel("绳长 s (mm)", color="#0891b2", fontsize=11)
ax1.tick_params(axis="y", labelcolor="#0891b2")
ax1.grid(alpha=0.25, ls="--")

ax2 = ax1.twinx()
ax2.plot(th * 180 / np.pi, r, color="#d97706", lw=2.6, label="力臂 r (mm)")
ax2.set_ylabel("力臂 r = −ds/dθ (mm)", color="#d97706", fontsize=11)
ax2.tick_params(axis="y", labelcolor="#d97706")
ax2.axhline(0, color="0.6", lw=0.8, ls=":")

# 标注三个点
for deg, txt in ((0, "s=14.671\nr=−22.05"), (30, "s=28.249\nr=−27.04")):
    t = deg * np.pi / 180
    ss = np.sqrt(al + be * np.cos(t) + ga * np.sin(t))
    rr = (be * np.sin(t) - ga * np.cos(t)) / (2 * ss)
    ax1.plot(deg, ss, "o", color="#0891b2", ms=6)
    ax2.plot(deg, rr, "o", color="#d97706", ms=6)
    ax1.annotate(txt, (deg, ss), textcoords="offset points", xytext=(10, -28),
                 fontsize=9, color="#0e7490")

ax1.set_title("C2 / roll：绳长与力臂随 θ 的变化", fontsize=13.5)
lines = [l for l in ax1.get_lines()[:1]] + [l for l in ax2.get_lines()[:1]]
ax1.legend(lines, ["绳长 s（左轴）", "力臂 r（右轴）"], loc="upper left", fontsize=10, frameon=False)

fig.tight_layout()
fig.savefig("讲解图_r随角度变化.png", bbox_inches="tight", facecolor="white")
print("ok", s.min(), s.max(), r.min(), r.max())
