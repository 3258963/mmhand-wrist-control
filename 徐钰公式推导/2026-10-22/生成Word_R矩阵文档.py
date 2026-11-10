# -*- coding: utf-8 -*-
"""生成《绳驱二轴腕部：动态 R 矩阵解算》Word 文档（公式渲染为图片）。"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

plt.rcParams["mathtext.fontset"] = "dejavusans"
plt.rcParams["font.family"] = "DejaVu Sans"

OUT = "飞书_动态R矩阵_文档.docx"
TMP = "_fml"
os.makedirs(TMP, exist_ok=True)

# ---------------- 公式渲染 ----------------
_n = [0]
def formula(doc, latex, fontsize=15, max_w_cm=15.5):
    _n[0] += 1
    path = os.path.join(TMP, "f%02d.png" % _n[0])
    try:
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, "$%s$" % latex, fontsize=fontsize, color="#16202e")
        fig.savefig(path, dpi=320, bbox_inches="tight", pad_inches=0.04, transparent=True)
        plt.close(fig)
        w, h = Image.open(path).size
        width_cm = min(w / 320 * 2.54, max_w_cm)
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        p.add_run().add_picture(path, width=Cm(width_cm))
    except Exception as e:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(latex)
        r.font.name = "Consolas"
        r.font.size = Pt(10)
        print("skip formula:", latex, e)

# ---------------- 表格 ----------------
def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)

def table(doc, header, rows, widths=None, bold_cols=(), center_body=True):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0].cells
    for i, h in enumerate(header):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h)
        r.bold = True
        r.font.size = Pt(9.5)
        shade(hdr[i], "E8EEF9")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = (WD_ALIGN_PARAGRAPH.CENTER if center_body else WD_ALIGN_PARAGRAPH.LEFT)
            r = p.add_run(str(v))
            r.font.size = Pt(9.5)
            if i in bold_cols:
                r.bold = True
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    # 表格不跨页断行，并尽量整体保持在一页
    for ri, row in enumerate(t.rows):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        if ri < len(t.rows) - 1:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
    return t

def para(doc, text, size=10.5, bold=False, color=None, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.35
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if bold:
        p.paragraph_format.keep_with_next = True
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    return p

def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.3
    r = p.add_run(text)
    r.font.size = Pt(size)
    return p

# ---------------- 文档 ----------------
doc = Document()

# 页面
sec = doc.sections[0]
sec.top_margin = Cm(2.0)
sec.bottom_margin = Cm(2.0)
sec.left_margin = Cm(2.2)
sec.right_margin = Cm(2.2)

# 默认字体
style = doc.styles["Normal"]
style.font.name = "微软雅黑"
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

for name, size, color in (("Heading 1", 18, "1E293B"), ("Heading 2", 13.5, "1D4ED8")):
    st = doc.styles[name]
    st.font.name = "微软雅黑"
    st.font.size = Pt(size)
    st.font.bold = True
    st.font.color.rgb = RGBColor.from_string(color)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

# 页脚页码
footer_p = sec.footer.paragraphs[0]
footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = footer_p.add_run()
fld = OxmlElement("w:fldSimple")
fld.set(qn("w:instr"), "PAGE")
run._r.addnext(fld)

# 标题
h = doc.add_heading("绳驱二轴腕部：动态 R 矩阵解算", level=0)
h.alignment = WD_ALIGN_PARAGRAPH.LEFT

# 结论框
t = doc.add_table(rows=1, cols=1)
t.style = "Table Grid"
c = t.rows[0].cells[0]
shade(c, "F1F6FF")
c.text = ""
p = c.paragraphs[0]
r = p.add_run("一句话结论：")
r.bold = True
r.font.size = Pt(10.5)
r2 = p.add_run("R 是 2 行 3 列，元素为每段绳的力臂 r = −ds/dθ。每段只需 5 个常数（u₁, u₂, v₁, v₂, h），"
               "即可在任意姿态实时算出，单段误差 < 1e-4 mm。")
r2.font.size = Pt(10.5)
doc.add_paragraph()

# 1
doc.add_heading("1  符号约定", level=1)
table(doc,
      ["符号", "含义", "单位"],
      [["o", "轴心（roll 段 = 原点，pitch 段 = (0,0,24)）", "mm"],
       ["â", "轴方向，单位向量（roll:+Y，pitch:+X）", "—"],
       ["A", "固定端（P4 / P6）", "mm"],
       ["B₀", "动端零位（P5 / P7）", "mm"],
       ["θ", "转角，右手为正", "rad"],
       ["a", "固定端到轴的距离", "mm"],
       ["b", "动端到轴的距离", "mm"],
       ["h", "两端沿轴错开量（带符号）", "mm"],
       ["Δ", "两个半径的有向夹角", "rad"],
       ["s", "该段绳长", "mm"],
       ["r", "力臂，r = −ds/dθ", "mm"]],
      widths=[2.0, 10.8, 2.2], center_body=False)

# 2
doc.add_heading("2  几何设定", level=1)
bullet(doc, "roll 轴：过原点，方向 +Y")
bullet(doc, "pitch 轴：过 (0,0,24)，方向 +X")
bullet(doc, "3 根绳 / 2 个自由度，每根绳跨两个关节")
para(doc, "每段绳只跨一个关节，因此绳长可写成两段之和：")
formula(doc, r"l_i(\theta_r,\theta_p)=c_i+s_{ri}(\theta_r)+s_{pi}(\theta_p)")
para(doc, "其中 c 是常数长度。")

# 3
doc.add_heading("3  单段推导", level=1)

para(doc, "① 两个向量", bold=True)
formula(doc, r"u=A-o,\qquad v=B_0-o")

para(doc, "② 拆成沿轴 + 垂直", bold=True)
formula(doc, r"h_1=u\cdot\hat{a},\qquad u_\perp=u-h_1\hat{a}")
formula(doc, r"h_2=v\cdot\hat{a},\qquad v_\perp=v-h_2\hat{a}")
para(doc, "三个不变量：")
formula(doc, r"a=\Vert u_\perp\Vert,\qquad b=\Vert v_\perp\Vert,\qquad h=h_2-h_1")

para(doc, "③ 动端转过去", bold=True)
formula(doc, r"\mathrm{Rot}(\theta)\,v_\perp=v_\perp\cos\theta+(\hat{a}\times v_\perp)\sin\theta")
formula(doc, r"B(\theta)=o+h_2\hat{a}+\mathrm{Rot}(\theta)\,v_\perp")

para(doc, "④ 距离平方", bold=True)
para(doc, "先把 B − A 写出来（注意 h = h₂ − h₁）：")
formula(doc, r"B-A=h\,\hat{a}+\mathrm{Rot}(\theta)\,v_\perp-u_\perp")
para(doc, "â 与两个垂直分量都正交，平方时轴向项单独分离：")
formula(doc, r"s^2=h^2+\Vert \mathrm{Rot}(\theta)\,v_\perp-u_\perp\Vert^2")
para(doc, "垂直部分用 ‖ξ−η‖² = ‖ξ‖² + ‖η‖² − 2ξ·η 展开，代入 ‖Rot·v⊥‖ = b、‖u⊥‖ = a：")
formula(doc, r"s^2=a^2+b^2+h^2-2\,\mathrm{Rot}(\theta)\,v_\perp\cdot u_\perp")

para(doc, "⑤ 点积展开（两角和）", bold=True)
para(doc, "把 Rot(θ)·v⊥ 代入点积：")
formula(doc, r"\mathrm{Rot}(\theta)\,v_\perp\cdot u_\perp=(v_\perp\cdot u_\perp)\cos\theta+((\hat{a}\times v_\perp)\cdot u_\perp)\sin\theta")
para(doc, "再代入 cosΔ、sinΔ 的定义，合并成两角和：")
formula(doc, r"\mathrm{Rot}(\theta)\,v_\perp\cdot u_\perp=ab(\cos\Delta\cos\theta-\sin\Delta\sin\theta)=ab\cos(\Delta+\theta)")
para(doc, "其中")
formula(doc, r"\cos\Delta=\frac{v_\perp\cdot u_\perp}{ab},\qquad \sin\Delta=-\frac{(\hat{a}\times v_\perp)\cdot u_\perp}{ab}")

para(doc, "⑥ 得到闭式", bold=True)
formula(doc, r"s^2=\alpha+\beta\cos\theta+\gamma\sin\theta")
formula(doc, r"\alpha=a^2+b^2+h^2")
formula(doc, r"\beta=-2(v_\perp\cdot u_\perp),\qquad \gamma=-2\,((\hat{a}\times v_\perp)\cdot u_\perp)")

# 图
pic = "讲解图_B三维_30度.png"
if os.path.exists(pic):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.add_run().add_picture(pic, width=Cm(14.2))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cr = cap.add_run("图 1  v 绕轴转 θ 得到 v′（C2 / roll，θ = 30°）")
    cr.font.size = Pt(9)
    cr.font.color.rgb = RGBColor.from_string("64748B")

# 4
doc.add_heading("4  力臂与 R 矩阵", level=1)
para(doc, "对 s 求导：")
formula(doc, r"\frac{ds}{d\theta}=\frac{\gamma\cos\theta-\beta\sin\theta}{2s}")
para(doc, "论文约定 r = −ds/dθ，因此：")
formula(doc, r"r(\theta)=\frac{\beta\sin\theta-\gamma\cos\theta}{2s},\qquad r(0)=-\frac{\gamma}{2\sqrt{\alpha+\beta}}")
para(doc, "R 矩阵（2 行 × 3 列，行 = 关节，列 = 绳）：")
formula(doc, r"R=-\left(\frac{\partial l}{\partial q}\right)^{\mathrm{T}},\qquad R_{ij}=r_i(\theta_j)")
para(doc, "零位时的数值：")
table(doc, ["", "C1", "C2", "C3"],
      [["roll", "−0.259", "−22.050", "+17.372"],
       ["pitch", "−58.105", "+11.805", "+10.990"]],
      widths=[3.0, 4.0, 4.0, 4.0], bold_cols=(1, 2, 3))
doc.add_paragraph()
para(doc, "张力映射：")
formula(doc, r"\tau=Rf,\qquad f=R^{+}\tau+t\,w")

# 5
doc.add_heading("5  零位标定表（mm）", level=1)
table(doc, ["绳", "roll a", "roll b", "roll h", "roll Δ", "r(0) roll", "r(0) pitch"],
      [["C1", "5.02", "18.17", "3.00", "+2.20°", "−0.259", "−58.105"],
       ["C2", "27.46", "37.15", "4.00", "+18.49°", "−22.050", "+11.805"],
       ["C3", "27.46", "41.60", "4.00", "−15.14°", "+17.372", "+10.990"]],
      widths=[1.8, 2.3, 2.3, 2.3, 2.5, 2.9, 2.9])
doc.add_paragraph()
para(doc, "Δ 是有向角，正负由 sinΔ = γ/(2ab) 决定。", size=9.5, color="64748B")

# 6
doc.add_heading("6  算法流程（每段）", level=1)
for i, s in enumerate([
    "取常数 u₁, u₂, v₁, v₂, h",
    "算 cosθ、sinθ",
    "d₁ = v₁·cosθ − v₂·sinθ − u₁",
    "d₂ = v₁·sinθ + v₂·cosθ − u₂",
    "s = √(d₁² + d₂² + h²)",
    "r = (u₂·d₁ − u₁·d₂) / s"], 1):
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.line_spacing = 1.25
    p.add_run(s).font.size = Pt(10.5)
para(doc, "三根绳 × 两段 = 6 次调用，得到 R 的 6 个元素。")

# 7
doc.add_heading("7  数值验证（C2 / roll）", level=1)
table(doc, ["θ", "s (mm)", "r (mm)"],
      [["0°", "14.671", "−22.050"], ["25°", "25.884", "−26.99"], ["30°", "28.249", "−27.04"]],
      widths=[3.0, 4.5, 4.5])
doc.add_paragraph()
para(doc, "手算（θ = 30°）：")
formula(doc, r"v_\perp=(-32.5,\,0,\,18),\qquad \hat{a}\times v_\perp=(18,\,0,\,32.5)")
formula(doc, r"\mathrm{Rot}\cdot v_\perp=0.8660\,(-32.5,0,18)+0.5\,(18,0,32.5)=(-19.145,\,0,\,31.839)")
formula(doc, r"B=(0,0,0)+(0,-12,0)+(-19.145,0,31.839)=(-19.145,\,-12,\,31.839)")
formula(doc, r"s=\Vert B-A\Vert=\sqrt{7.855^2+4^2+26.838^2}=28.249\ \mathrm{mm}")

# 8
doc.add_heading("8  工程实现", level=1)
bullet(doc, "每段 5 个常数，可预计算为 float")
bullet(doc, "单段：2 次 sin/cos + 4 次乘 + 1 次开方")
bullet(doc, "9,249 个姿态验证：float32 与 double 最大差 4.67e-5 mm")
bullet(doc, "参考实现：src/wrist_r.c")

# 9
doc.add_heading("9  常见错误", level=1)
table(doc, ["错误", "后果"],
      [["把 pitch 轴心当原点", "力臂全错（差 24 mm 量级）"],
       ["用 ‖v‖ 当半径 b", "少减了轴向分量"],
       ["角度用度", "cos/sin 结果错"],
       ["力臂符号取反", "控制方向反，闭环发散"]],
      widths=[6.5, 8.5])

# 10
doc.add_heading("10  修订记录", level=1)
table(doc, ["日期", "版本", "修改"],
      [["2026-10-22", "v1.0", "初稿"],
       ["2026-10-26", "v1.1", "补 30° 算例与标定表"],
       ["2026-10-26", "v1.2", "Word 版：公式改为公式图片"]],
      widths=[3.5, 2.5, 9.0])

doc.save(OUT)
print("saved", OUT, os.path.getsize(OUT))
