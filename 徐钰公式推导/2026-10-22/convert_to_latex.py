# -*- coding: utf-8 -*-
"""Convert the focused note from plain-text formulas to the LaTeX style of
飞书_动态R矩阵_验证与解算.md (single-line $$...$$ blocks)."""
import re
from pathlib import Path

src = Path("飞书_动态R矩阵_原理与实现_纯文本.md").read_text(encoding="utf-8")

REPL = [
    r"$$l_i(\theta_r,\theta_p)=c_i+s_{ri}(\theta_r)+s_{pi}(\theta_p)$$",

    "$$R_{ji}=-\\frac{\\partial l_i}{\\partial q_j},\\qquad \\tau=Rf$$\n\n"
    "其中 $j=\\mathrm{roll},\\mathrm{pitch}$；$i=C1,C2,C3$。",

    r"$$R=\begin{bmatrix} r_{r,C1} & r_{r,C2} & r_{r,C3}\\ r_{p,C1} & r_{p,C2} & r_{p,C3}\end{bmatrix}$$",

    r"$$R=\begin{bmatrix} r_{r,C1}(\theta_r) & r_{r,C2}(\theta_r) & r_{r,C3}(\theta_r)\\ r_{p,C1}(\theta_p) & r_{p,C2}(\theta_p) & r_{p,C3}(\theta_p)\end{bmatrix}$$",

    "$$u=A-o,\\qquad v=B_0-o$$\n\n"
    "$$h_1=u\\cdot\\hat a,\\quad u_\\perp=u-h_1\\hat a,\\quad h_2=v\\cdot\\hat a,\\quad v_\\perp=v-h_2\\hat a$$\n\n"
    "$$a=\\lVert u_\\perp\\rVert,\\quad b=\\lVert v_\\perp\\rVert,\\quad h=h_2-h_1$$",

    "$$v'_\\perp=v_\\perp\\cos\\theta+(\\hat a\\times v_\\perp)\\sin\\theta,\\qquad B(\\theta)=o+h_2\\hat a+v'_\\perp$$",

    r"$$B-A=h\hat a+v'_\perp-u_\perp$$",

    r"$$s^2=h^2+\lVert v'_\perp-u_\perp\rVert^2=a^2+b^2+h^2-2v'_\perp\cdot u_\perp$$",

    r"$$v'_\perp\cdot u_\perp=(v_\perp\cdot u_\perp)\cos\theta+((\hat a\times v_\perp)\cdot u_\perp)\sin\theta$$",

    r"$$\cos\Delta=\frac{v_\perp\cdot u_\perp}{ab},\qquad \sin\Delta=-\frac{(\hat a\times v_\perp)\cdot u_\perp}{ab}$$",

    r"$$v'_\perp\cdot u_\perp=ab\cos(\Delta+\theta),\qquad s^2=a^2+b^2+h^2-2ab\cos(\Delta+\theta)$$",

    r"$$s^2=\alpha+\beta\cos\theta+\gamma\sin\theta,\qquad \alpha=a^2+b^2+h^2,\quad \beta=-2ab\cos\Delta,\quad \gamma=+2ab\sin\Delta$$",

    r"$$s=\sqrt{\alpha+\beta\cos\theta+\gamma\sin\theta},\qquad \frac{\mathrm ds}{\mathrm d\theta}=\frac{\gamma\cos\theta-\beta\sin\theta}{2s}$$",

    r"$$r(\theta)=-\frac{\mathrm ds}{\mathrm d\theta}=\frac{\beta\sin\theta-\gamma\cos\theta}{2s},\qquad r(0)=-\frac{\gamma}{2\sqrt{\alpha+\beta}}$$",

    r"$$R=\begin{bmatrix} r_{r,C1} & r_{r,C2} & r_{r,C3}\\ r_{p,C1} & r_{p,C2} & r_{p,C3}\end{bmatrix},\qquad r_{r,Ci}=r_i(\theta_r),\quad r_{p,Ci}=r_i(\theta_p)$$",

    r"$$u=(-27,-5),\qquad v=(-32.5,-18)$$",

    "$$v'_1=v_1\\cos30^\\circ-v_2\\sin30^\\circ=-19.146,\\qquad v'_2=v_1\\sin30^\\circ+v_2\\cos30^\\circ=-31.838$$\n\n"
    "$$d=v'-u=(7.854,-26.838),\\qquad s=\\sqrt{7.854^2+26.838^2+4^2}=28.249\\ \\mathrm{mm}$$\n\n"
    "$$r=\\frac{d_1v'_2-d_2v'_1}{s}=\\frac{7.854\\times(-31.838)-(-26.838)\\times(-19.146)}{28.249}=-27.042\\ \\mathrm{mm}$$",

    r"$$r(30^\circ)=\frac{-1935\times0.5-647\times0.8660}{2\times28.249}=-27.042\ \mathrm{mm}$$",

    r"$$u_1=u\cdot e_1,\quad u_2=u\cdot e_2,\quad v_1=v\cdot e_1,\quad v_2=v\cdot e_2,\quad h=(v-u)\cdot\hat a$$",

    "$$v'_1=v_1\\cos\\theta-v_2\\sin\\theta,\\qquad v'_2=v_1\\sin\\theta+v_2\\cos\\theta$$\n\n"
    "$$d_1=v'_1-u_1,\\quad d_2=v'_2-u_2,\\quad s=\\sqrt{d_1^2+d_2^2+h^2},\\quad r=\\frac{d_1v'_2-d_2v'_1}{s}$$",

    r"$$r=\frac{d_1v'_2-d_2v'_1}{s},\qquad -r=\frac{u_1d_2-u_2d_1}{s}$$",

    r"$$\tau=Rf$$",

    r"$$f=R^{+}\tau+t\,n$$",

    None,  # keep pseudocode block
]

parts = re.split(r"```text\n(.*?)```", src, flags=re.S)
# parts: text, block0, text, block1, ...; len = 2*blocks+1
assert len(parts) == 2 * len(REPL) + 1, (len(parts), len(REPL))

out = [parts[0]]
for i, block in enumerate(REPL):
    if block is None:
        out.append("```text\n" + parts[2 * i + 1] + "```")
    else:
        out.append(block)
    out.append(parts[2 * i + 2])

new = "".join(out)
Path("飞书_动态R矩阵_原理与实现.md").write_text(new, encoding="utf-8", newline="\n")
print("written", len(new), "dollars", new.count("$$"))
