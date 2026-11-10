# -*- coding: utf-8 -*-
"""生成《绳驱二轴腕部：动态 R 矩阵解算》完整报告（带图）。"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.opc.constants import RELATIONSHIP_TYPE as RT

plt.rcParams["mathtext.fontset"] = "dejavusans"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT = "腕部_动态R矩阵_完整报告.docx"
TMP = "_fml2"
os.makedirs(TMP, exist_ok=True)
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
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(3)
        p.add_run().add_picture(path, width=Cm(min(w / 320 * 2.54, max_w_cm)))
    except Exception as e:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(latex).font.size = Pt(10)
        print("skip:", latex, e)


def figure(doc, path, caption, width=15.0):
    if not os.path.exists(path):
        print("missing:", path)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.add_run().add_picture(path, width=Cm(width))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = c.add_run(caption)
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor.from_string("64748B")



def add_link(doc, text, url):
    """在最后一段末尾追加一个超链接。"""
    part = doc.part
    r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)
    hl = OxmlElement("w:hyperlink")
    hl.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1D4ED8")
    rPr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    hl.append(run)
    doc.paragraphs[-1]._p.append(hl)

def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def table(doc, header, rows, widths=None, center_body=True, bold_cols=()):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h)
        r.bold = True
        r.font.size = Pt(9.5)
        shade(cell, "E8EEF9")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center_body else WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(str(v))
            r.font.size = Pt(9.5)
            if i in bold_cols:
                r.bold = True
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    for ri, row in enumerate(t.rows):
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if ri < len(t.rows) - 1:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
    return t


def para(doc, text, size=10.5, bold=False, color=None, space_after=6, indent=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.4
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    if bold:
        p.paragraph_format.keep_with_next = True
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.35
    p.add_run(text).font.size = Pt(size)
    return p


# ---------------- 文档 ----------------
doc = Document()
sec = doc.sections[0]
sec.top_margin = Cm(2.0)
sec.bottom_margin = Cm(2.0)
sec.left_margin = Cm(2.1)
sec.right_margin = Cm(2.1)

st = doc.styles["Normal"]
st.font.name = "微软雅黑"
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

for name, size, color in (("Heading 1", 15, "1E293B"), ("Heading 2", 12, "1D4ED8")):
    s = doc.styles[name]
    s.font.name = "微软雅黑"
    s.font.size = Pt(size)
    s.font.bold = True
    s.font.color.rgb = RGBColor.from_string(color)
    s.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

fp = sec.footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = fp.add_run()
fld = OxmlElement("w:fldSimple")
fld.set(qn("w:instr"), "PAGE")
run._r.addnext(fld)

# 标题
h = doc.add_heading("绳驱二轴腕部：动态 R 矩阵解算", level=0)
h.paragraph_format.space_after = Pt(4)

t = doc.add_table(rows=1, cols=1)
t.style = "Table Grid"
c = t.rows[0].cells[0]
shade(c, "F1F6FF")
c.text = ""
p = c.paragraphs[0]
r = p.add_run("结论：")
r.bold = True
r.font.size = Pt(10.5)
r2 = p.add_run(
    "由于本腕部为 3 绳驱动 2 自由度的冗余构型，绳与轴的相对位置随姿态变化，力臂不能视为常数，"
    "因此 R 必须是关节角的函数。每段只需 5 个常数（u₁, u₂, v₁, v₂, h）即可实时算出，单段误差 < 1e-4 mm。")
r2.font.size = Pt(10.5)
doc.add_paragraph()

# 1
doc.add_heading("1  需求来源：为什么必须是“动态”R", level=1)

para(doc, "1.1  构型", bold=True)
para(doc, "腕部由 3 根绳驱动 2 个自由度（roll、pitch），属于 n+1 冗余驱动。绳的一端固定在基座，"
          "另一端固定在转子上，中间绕过关节。关节一旦转动，绳与轴心的相对位置就改变，"
          "于是“绳长对角度的变化率”——也就是力臂 r = −ds/dθ——随之改变。", indent=True)

para(doc, "1.2  力臂随姿态变化的事实", bold=True)
para(doc, "以 C2 / roll 段为例，零位力臂为 −22.05 mm，转到 30° 时变为 −27.04 mm：", indent=True)
figure(doc, "讲解图_r随角度变化.png", "图 1  绳长 s 与力臂 r 随关节角的变化（C2 / roll）", 15.0)
para(doc, "曲线说明三件事：r 并非常数；r = 0 的位置正好是绳长的极小点；不同绳的变化趋势并不一致。", indent=True)

para(doc, "1.3  用定常数 R 会带来多大误差", bold=True)
para(doc, "若只用零位标定的 R₀：", indent=True)
bullet(doc, "±30° 范围内，C2 的力臂变化约 23.0%（−22.05 → −27.12），力矩估计同比例失真；")
bullet(doc, "三根绳的力臂量级差两个数量级（C1 约 −0.26，C2 约 −22.05），无法用一个平均系数补偿；")
bullet(doc, "在张力分配（f = R⁺τ + tw）中，R 的误差会直接放大为零空间方向的漂移。")

para(doc, "1.4  目标", bold=True)
para(doc, "给出 R 的解析解：由几何常数与关节角直接算出 2×3 的 R，不依赖查表、不依赖迭代，"
          "可在嵌入式平台上逐周期计算。", indent=True)
para(doc, "范围说明：本文只讨论 R 矩阵本身的解算；控制律（P 矩阵、张力分配策略）不在本文范围内。",
     size=9.5, color="64748B")

# 2
doc.add_heading("2  几何与符号", level=1)
para(doc, "2.1  坐标系与转轴", bold=True)
para(doc, "原点取 roll 轴上、离 pitch 轴最近的点；roll 轴过原点、方向 +Y；pitch 轴过 (0,0,24)、方向 +X，"
          "两者构成右手系。注意 pitch 轴并不过原点。", indent=True)
figure(doc, "viz_shots/sri_cyan.png", "图 2  交互页面（第 2 步：减去轴心）：紫线为零位向量 v，青色虚线为转过 θ 后的 v′", 15.0)

para(doc, "2.2  符号", bold=True)
table(doc, ["符号", "含义", "单位"],
      [["o", "轴心（roll 段 = 原点，pitch 段 = (0,0,24)）", "mm"],
       ["â", "轴方向，单位向量（roll:+Y，pitch:+X）", "—"],
       ["A", "固定端（P4 / P6）", "mm"],
       ["B₀", "动端零位（P5 / P7）", "mm"],
       ["θ", "关节转角，右手为正", "rad"],
       ["a", "固定端到轴的距离", "mm"],
       ["b", "动端到轴的距离", "mm"],
       ["h", "两端沿轴错开量（带符号）", "mm"],
       ["Δ", "两个半径的有向夹角", "rad"],
       ["s", "该段绳长", "mm"],
       ["r", "力臂，r = −ds/dθ", "mm"]],
      widths=[2.0, 10.8, 2.2], center_body=False)

# 3
doc.add_heading("3  单段绳长推导", level=1)
para(doc, "3.1  两个向量", bold=True)
formula(doc, r"\vec{u}=\vec{A}-\vec{o},\qquad \vec{v}=\vec{B}_0-\vec{o}")

para(doc, "3.2  拆成沿轴与垂直", bold=True)
formula(doc, r"h_1=\vec{u}\cdot\hat{a},\qquad \vec{u}_\perp=\vec{u}-h_1\hat{a}")
formula(doc, r"h_2=\vec{v}\cdot\hat{a},\qquad \vec{v}_\perp=\vec{v}-h_2\hat{a}")
para(doc, "三个不变量：")
formula(doc, r"a=\Vert \vec{u}_\perp\Vert,\qquad b=\Vert \vec{v}_\perp\Vert,\qquad h=h_2-h_1")

para(doc, "3.3  动端旋转", bold=True)
para(doc, "绕轴旋转只改变垂直于轴的分量，沿轴分量保持不变：", indent=True)
formula(doc, r"\mathrm{Rot}(\theta)\,\vec{v}_\perp=\vec{v}_\perp\cos\theta+(\hat{a}\times \vec{v}_\perp)\sin\theta")
formula(doc, r"\vec{B}(\theta)=\vec{o}+h_2\hat{a}+\mathrm{Rot}(\theta)\,\vec{v}_\perp")
figure(doc, "讲解图_旋转分解.png", "图 3  垂直平面内的分解：径向 r·cosθ 与切向 r·sinθ", 12.5)

para(doc, "3.4  距离平方", bold=True)
formula(doc, r"\vec{B}-\vec{A}=h\,\hat{a}+\mathrm{Rot}(\theta)\,\vec{v}_\perp-\vec{u}_\perp")
para(doc, "轴向与垂直方向正交，平方时轴向项单独分离：", indent=True)
formula(doc, r"s^2=h^2+\Vert \mathrm{Rot}(\theta)\,\vec{v}_\perp-\vec{u}_\perp\Vert^2")
formula(doc, r"s^2=a^2+b^2+h^2-2\,\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp")

para(doc, "3.5  点积与两角和", bold=True)
formula(doc, r"\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp=(\vec{v}_\perp\cdot \vec{u}_\perp)\cos\theta+((\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp)\sin\theta")
formula(doc, r"\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp=ab\cos(\Delta+\theta)")
para(doc, "其中")
formula(doc, r"\cos\Delta=\frac{\vec{v}_\perp\cdot \vec{u}_\perp}{ab},\qquad \sin\Delta=-\frac{(\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp}{ab}")

para(doc, "3.6  闭式", bold=True)
formula(doc, r"s^2=\alpha+\beta\cos\theta+\gamma\sin\theta")
formula(doc, r"\alpha=a^2+b^2+h^2,\quad \beta=-2(\vec{v}_\perp\cdot \vec{u}_\perp),\quad \gamma=-2((\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp)")

# 4
doc.add_heading("4  从绳长到 R 矩阵", level=1)
para(doc, "4.1  求导", bold=True)
formula(doc, r"\frac{ds}{d\theta}=\frac{\gamma\cos\theta-\beta\sin\theta}{2s}")
para(doc, "论文约定 r = −ds/dθ，因此：")
formula(doc, r"r(\theta)=\frac{\beta\sin\theta-\gamma\cos\theta}{2s},\qquad r(0)=-\frac{\gamma}{2\sqrt{\alpha+\beta}}")

para(doc, "4.2  R 的定义", bold=True)
formula(doc, r"R=-\left(\frac{\partial l}{\partial q}\right)^{\mathrm{T}},\qquad R_{ij}=r_i(\theta_j)")
para(doc, "零位数值（mm）：")
table(doc, ["", "C1", "C2", "C3"],
      [["roll", "−0.259", "−22.050", "+17.372"],
       ["pitch", "−58.105", "+11.805", "+10.990"]],
      widths=[3.0, 4.0, 4.0, 4.0], bold_cols=(1, 2, 3))

para(doc, "4.3  实时算法（每段 5 个常数）", bold=True)
formula(doc, r"d_1=v_1\cos\theta-v_2\sin\theta-u_1")
formula(doc, r"d_2=v_1\sin\theta+v_2\cos\theta-u_2")
formula(doc, r"s=\sqrt{d_1^2+d_2^2+h^2},\qquad r=\frac{u_2d_1-u_1d_2}{s}")
para(doc, "三根绳 × 两段 = 6 次调用，得到 R 的 6 个元素；单段只需 2 次 sin/cos、4 次乘法、1 次开方。")

para(doc, "4.4  精度", bold=True)
bullet(doc, "9,249 个姿态全遍历验证；")
bullet(doc, "float32 与 double 的最大差 4.67×10⁻⁵ mm；")
bullet(doc, "参考实现：src/wrist_r.c。")

# 5
doc.add_heading("5  数值验证", level=1)
para(doc, "5.1  C2 / roll，θ = 30° 手算", bold=True)
formula(doc, r"\vec{v}_\perp=(-32.5,0,18),\qquad \hat{a}\times \vec{v}_\perp=(18,0,32.5)")
formula(doc, r"\mathrm{Rot}\cdot \vec{v}_\perp=0.8660(-32.5,0,18)+0.5(18,0,32.5)=(-19.145,0,31.839)")
formula(doc, r"\vec{B}=(0,0,0)+(0,-12,0)+(-19.145,0,31.839)=(-19.145,-12,31.839)")
formula(doc, r"s=\Vert \vec{B}-\vec{A}\Vert=\sqrt{7.855^2+4^2+26.838^2}=28.249\ \mathrm{mm}")
figure(doc, "讲解图_B三维_30度.png", "图 4  B 点的三维示意：紫色为零位向量 v，青色为转过 30° 的 v′", 14.5)

para(doc, "5.2  多角度对照", bold=True)
table(doc, ["θ", "s (mm)", "r (mm)"],
      [["0°", "14.671", "−22.050"], ["25°", "25.884", "−27.124"], ["30°", "28.249", "−27.042"]],
      widths=[3.0, 4.5, 4.5])
para(doc, "与闭式公式 s² = α + βcosθ + γsinθ 的结果逐点一致。", size=9.5, color="64748B")

# 6
doc.add_heading("6  交互工具", level=1)
para(doc, "推导过程中的每一步都做成了可交互页面，便于核对与讲解：")
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(6)
p.add_run("直接打开： ").font.size = Pt(10.5)
add_link(doc, "3D_拆解_sri.html", "3D_拆解_sri.html")
p.add_run("　　").font.size = Pt(10.5)
add_link(doc, "第4步_动画.html", "第4步_动画.html")
bullet(doc, "3D_拆解_sri.html：六步拆解，可拖动旋转、调角度、开关每层元素；")
bullet(doc, "第4步_动画.html：v⊥ 绕轴旋转的动画，实时显示 cos/sin 两个分量；")
bullet(doc, "打开方式：双击文件用浏览器打开（Chrome / Edge）。")
figure(doc, "viz_shots/step4.png", "图 5  第 4 步动画：绿色为 r·cosθ，青色为 r·sinθ，白箭头为合成结果", 15.0)

# 7
doc.add_heading("7  常见错误", level=1)
table(doc, ["错误", "后果"],
      [["把 pitch 轴心当原点", "力臂全错（差 24 mm 量级）"],
       ["用 ‖v‖ 当半径 b", "少减了轴向分量"],
       ["角度用度", "cos/sin 结果错"],
       ["力臂符号取反", "控制方向反，闭环发散"],
       ["忽略解耦条件", "两段互相干扰"]],
      widths=[6.5, 8.5], center_body=False)

# 8
doc.add_heading("8  修订记录", level=1)
table(doc, ["日期", "版本", "修改"],
      [["2026-10-22", "v1.0", "初稿：推导与标定"],
       ["2026-10-26", "v1.1", "补 30° 算例、r(θ) 曲线"],
       ["2026-10-26", "v1.2", "重写需求来源章节，补图 1–5"]],
      widths=[3.5, 2.5, 9.0])

doc.save(OUT)
print("saved", OUT, os.path.getsize(OUT))
