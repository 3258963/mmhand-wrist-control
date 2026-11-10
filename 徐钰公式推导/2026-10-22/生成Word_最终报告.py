# -*- coding: utf-8 -*-
"""生成《动态 R 矩阵：完整报告 v2》——含虚功原理与详细求导。"""
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
TMP = "_fml4"
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
        w, _ = Image.open(path).size
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


def figure(doc, path, caption, width=14.6):
    if not os.path.exists(path):
        print("missing", path)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(5)
    p.add_run().add_picture(path, width=Cm(width))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = c.add_run(caption)
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor.from_string("64748B")


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


def para(doc, text, size=10.5, bold=False, color=None, after=5, indent=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.42
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
    p.paragraph_format.line_spacing = 1.32
    p.add_run(text).font.size = Pt(size)


def numbered(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.line_spacing = 1.3
    p.add_run(text).font.size = Pt(size)


def add_link(doc, text, url):
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


# ---------------- 文档 ----------------
doc = Document()
sec = doc.sections[0]
sec.top_margin = Cm(1.9)
sec.bottom_margin = Cm(1.9)
sec.left_margin = Cm(2.0)
sec.right_margin = Cm(2.0)

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

doc.add_heading("绳驱二轴腕部：动态 R 矩阵解算", level=0)

_au = doc.add_paragraph()
_au.alignment = WD_ALIGN_PARAGRAPH.CENTER
_au.paragraph_format.space_before = Pt(2)
_au.paragraph_format.space_after = Pt(2)
_r = _au.add_run("徐钰　陈梓贤")
_r.font.size = Pt(12)
_r.font.color.rgb = RGBColor.from_string("1F2937")

_u = doc.add_paragraph()
_u.alignment = WD_ALIGN_PARAGRAPH.CENTER
_u.paragraph_format.space_after = Pt(2)
_ru = _u.add_run("SLAIHAND")
_ru.font.size = Pt(10)
_ru.font.color.rgb = RGBColor.from_string("475569")

_meta = doc.add_paragraph()
_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
_meta.paragraph_format.space_after = Pt(10)
_r2 = _meta.add_run("技术报告　TR-WRIST-2026-01　|　2026 年 10 月 29 日")
_r2.font.size = Pt(9.5)
_r2.font.color.rgb = RGBColor.from_string("64748B")

t = doc.add_table(rows=1, cols=1)
t.style = "Table Grid"
c = t.rows[0].cells[0]
shade(c, "F1F6FF")
c.text = ""
p = c.paragraphs[0]
r = p.add_run("结论：")
r.bold = True
r.font.size = Pt(10.5)
r2 = p.add_run("3 绳驱动 2 自由度的冗余构型使力臂随姿态变化（±30° 内变化 23.0%），因此 R 必须是关节角的函数。"
               "由虚功原理得 R = −(∂l/∂q)ᵀ；每格由 r = −ds/dθ 给出，每段只需 5 个常数即可实时计算。")
r2.font.size = Pt(10.5)
doc.add_paragraph()

# ============ 1 ============
doc.add_heading("1  需求来源：为什么必须是“动态”R", level=1)
para(doc, "1.1  构型", bold=True)
para(doc, "腕部由 3 根绳驱动 2 个自由度（roll、pitch），属于 n+1 冗余驱动。绳的一端固定在基座，另一端固定在转子上，"
          "中间绕过关节。关节一转，绳与轴心的相对位置就变，力臂 r = −ds/dθ 随之改变。", indent=True)

para(doc, "1.2  力臂随姿态变化的事实", bold=True)
para(doc, "C2 的 roll 段：零位 −22.05 mm，30° 时 −27.04 mm。", indent=True)
figure(doc, "讲解图_r随角度变化.png", "图 1  绳长 s 与力臂 r 随关节角的变化（C2 / roll）", 14.6)
para(doc, "r 不是常数；r = 0 处正好是 s 的极小点；三根绳的变化趋势并不一致。", indent=True)

para(doc, "1.3  用定常数 R 的误差", bold=True)
bullet(doc, "±30° 内力臂变化约 23.0%，力矩估计同比例失真；")
bullet(doc, "三根绳的力臂量级差两个数量级（C1 约 −0.26，C2 约 −22.05），无法用一个平均系数补偿；")
bullet(doc, "张力分配 f = R⁺τ + tw 中，R 的误差会放大为零空间方向的漂移。")

para(doc, "1.4  目标", bold=True)
para(doc, "给出 R 的解析解：由几何常数与关节角直接算出 2×3 的 R，不依赖查表、不依赖迭代。", indent=True)
para(doc, "范围：本文只讨论 R 矩阵本身的解算；控制律（P 矩阵、张力分配策略）不在范围内。", size=9.5, color="64748B")

# ============ 2 ============
doc.add_heading("2  R 矩阵的定义与推导", level=1)

para(doc, "2.1  问题", bold=True)
para(doc, "给定三根绳的张力 f（3×1），求两个关节的力矩 τ（2×1）。需要一个线性映射：", indent=True)
formula(doc, r"\tau=Rf")

para(doc, "2.2  用虚功原理推导", bold=True)
para(doc, "设关节角速度 q̇ = (θ̇r, θ̇p)，绳长变化率由链式法则：", indent=True)
formula(doc, r"\dot{l}=J\dot{q},\qquad J=\frac{\partial l}{\partial q}\ (3\times2)")
para(doc, "张力做功率：绳缩短才对外做功，故", indent=True)
formula(doc, r"P_{rope}=-f^{T}\dot{l}=-f^{T}J\dot{q}")
para(doc, "关节侧功率：", indent=True)
formula(doc, r"P_{joint}=\tau^{T}\dot{q}")
para(doc, "两者相等，且对任意 q̇ 成立：", indent=True)
formula(doc, r"\tau^{T}=-f^{T}J\quad\Longrightarrow\quad\tau=-J^{T}f")

para(doc, "2.3  定义 R", bold=True)
formula(doc, r"R=-J^{T}=-\left(\frac{\partial l}{\partial q}\right)^{T}")
para(doc, "于是 τ = R f，f_i ≥ 0（绳只能拉）。R 的每一格就是一个力臂。", indent=True)

para(doc, "2.4  维度与冗余", bold=True)
table(doc, ["维度", "含义"],
      [["2 行", "两个关节（roll、pitch）"],
       ["3 列", "三根绳（C1、C2、C3）"]],
      widths=[4.0, 11.0], center_body=False)
doc.add_paragraph()
para(doc, "矩阵不是方阵，反解用伪逆并加零空间偏置：", indent=True)
formula(doc, r"f=R^{+}\tau+t\,w")
para(doc, "w 为零空间向量（不产生关节力矩的张力组合），t 保证所有张力为正（预张紧）。", size=9.5, color="64748B")

# ============ 3 ============
doc.add_heading("3  几何与符号", level=1)
para(doc, "3.1  坐标系", bold=True)
para(doc, "原点取 roll 轴上离 pitch 轴最近的点；roll 轴过原点、方向 +Y；pitch 轴过 (0,0,24)、方向 +X；右手系。"
          "注意 pitch 轴不过原点。", indent=True)
table(doc, ["符号", "含义", "单位"],
      [["o", "轴心（roll 段 = 原点，pitch 段 = (0,0,24)）", "mm"],
       ["â", "轴方向，单位向量（roll:+Y，pitch:+X）", "—"],
       ["A", "固定端（P4 / P6）", "mm"],
       ["B₀", "动端零位（P5 / P7）", "mm"],
       ["θ", "关节转角，右手为正", "rad"],
       ["a、b", "两端到轴的距离（半径）", "mm"],
       ["h", "两端沿轴错开量（带符号）", "mm"],
       ["Δ", "两条半径的有向夹角", "rad"],
       ["s", "该段绳长", "mm"],
       ["r", "力臂 r = −ds/dθ", "mm"]],
      widths=[2.0, 10.8, 2.2], center_body=False)

para(doc, "3.2  交互页面", bold=True)
para(doc, "推导的每一步都对应页面上的一个步骤，可直接对照查看。", indent=True)
figure(doc, "viz_shots/sri_cyan.png", "图 2  交互页面第 2 步：紫线为零位向量 v，青虚线为转过 θ 后的 v′", 13.0)

# ============ 4 ============
doc.add_heading("4  绳长推导", level=1)

para(doc, "4.1  分段", bold=True)
para(doc, "每根绳跨两个关节，但每段只跨一个，因此", indent=True)
formula(doc, r"l=c+s_r(\theta_r)+s_p(\theta_p)")

para(doc, "4.2  减去轴心", bold=True)
formula(doc, r"\vec{u}=\vec{A}-\vec{o},\qquad \vec{v}=\vec{B}_0-\vec{o}")

para(doc, "4.3  拆出半径与轴向", bold=True)
formula(doc, r"h_1=\vec{u}\cdot\hat{a},\qquad \vec{u}_\perp=\vec{u}-h_1\hat{a}")
formula(doc, r"h_2=\vec{v}\cdot\hat{a},\qquad \vec{v}_\perp=\vec{v}-h_2\hat{a}")
formula(doc, r"a=\Vert \vec{u}_\perp\Vert,\qquad b=\Vert \vec{v}_\perp\Vert,\qquad h=h_2-h_1")
para(doc, "这三个量与 θ 无关，是几何常数。", indent=True)

para(doc, "4.4  旋转", bold=True)
para(doc, "绕轴旋转只改变垂直分量，沿轴分量不变：", indent=True)
formula(doc, r"\mathrm{Rot}(\theta)\,\vec{v}_\perp=\vec{v}_\perp\cos\theta+(\hat{a}\times \vec{v}_\perp)\sin\theta")
formula(doc, r"\vec{B}(\theta)=\vec{o}+h_2\hat{a}+\mathrm{Rot}(\theta)\,\vec{v}_\perp")
figure(doc, "讲解图_旋转分解.png", "图 3  垂直平面内的分解：径向 r·cosθ 与切向 r·sinθ", 12.0)

para(doc, "4.5  距离平方", bold=True)
formula(doc, r"\vec{B}-\vec{A}=h\,\hat{a}+\left(\mathrm{Rot}(\theta)\,\vec{v}_\perp-\vec{u}_\perp\right)")
para(doc, "轴向与垂直方向正交，平方可分离：", indent=True)
formula(doc, r"s^2=h^2+\Vert \mathrm{Rot}(\theta)\,\vec{v}_\perp-\vec{u}_\perp\Vert^2")
formula(doc, r"s^2=a^2+b^2+h^2-2\,\mathrm{Rot}(\theta)\,\vec{v}_\perp\cdot \vec{u}_\perp")

para(doc, "4.6  余弦定理与夹角", bold=True)
para(doc, "垂直平面内两条半径的夹角为 Δ + θ，于是", indent=True)
formula(doc, r"s^2=a^2+b^2+h^2-2ab\cos(\Delta+\theta)")
para(doc, "其中 Δ 由点乘与叉乘共同确定（叉乘提供符号）：", indent=True)
formula(doc, r"\cos\Delta=\frac{\vec{v}_\perp\cdot \vec{u}_\perp}{ab},\qquad \sin\Delta=-\frac{(\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp}{ab}")
figure(doc, "讲解图_sinDelta.png", "图 4  sinΔ 的几何解释：叉乘转 90° 后投影为负，故公式含负号", 14.2)

para(doc, "4.7  闭式", bold=True)
formula(doc, r"s^2=\alpha+\beta\cos\theta+\gamma\sin\theta")
formula(doc, r"\alpha=a^2+b^2+h^2,\quad \beta=-2\,\vec{v}_\perp\cdot \vec{u}_\perp,\quad \gamma=2ab\sin\Delta")

# ============ 5 ============
doc.add_heading("5  力臂 r 的推导（详细）", level=1)

para(doc, "5.1  求导所需的规则", bold=True)
table(doc, ["规则", "式子"],
      [["常数", "(α)′ = 0"],
       ["余弦", "(cosθ)′ = −sinθ"],
       ["正弦", "(sinθ)′ = +cosθ"],
       ["常数倍", "(βcosθ)′ = −βsinθ"],
       ["链式", "[f(θ)ⁿ]′ = n f(θ)ⁿ⁻¹ f′(θ)"]],
      widths=[4.0, 11.0], center_body=False)

para(doc, "5.2  先求 f′(θ)", bold=True)
formula(doc, r"f(\theta)=\alpha+\beta\cos\theta+\gamma\sin\theta")
formula(doc, r"f'(\theta)=0+(-\beta\sin\theta)+\gamma\cos\theta=\gamma\cos\theta-\beta\sin\theta")

para(doc, "5.3  再对开方求导（链式）", bold=True)
formula(doc, r"s=f(\theta)^{1/2}\quad\Longrightarrow\quad\frac{ds}{d\theta}=\frac{1}{2}f^{-1/2}f'(\theta)=\frac{f'(\theta)}{2s}")
formula(doc, r"\frac{ds}{d\theta}=\frac{\gamma\cos\theta-\beta\sin\theta}{2s}")

para(doc, "5.4  另一种写法（对 s² 隐式求导）", bold=True)
formula(doc, r"2s\frac{ds}{d\theta}=-\beta\sin\theta+\gamma\cos\theta")
para(doc, "两式完全等价，后者更短。", indent=True)

para(doc, "5.5  逐步代入数字（C2 / roll，θ = 30°）", bold=True)
table(doc, ["步骤", "计算", "结果"],
      [["cos30° / sin30°", "—", "0.86603 / 0.50000"],
       ["γcosθ", "647 × 0.86603", "560.32"],
       ["−βsinθ", "−(−1935) × 0.5", "+967.50"],
       ["分子 f′", "560.32 + 967.50", "1527.82"],
       ["分母 2s", "2 × 28.249", "56.498"],
       ["ds/dθ", "1527.82 / 56.498", "27.04 mm/rad"],
       ["r = −ds/dθ", "—", "−27.04 mm"]],
      widths=[4.2, 6.4, 4.4], center_body=False)

para(doc, "5.6  差分验证", bold=True)
para(doc, "取 θ = 30° 和 31° 直接算绳长：", indent=True)
formula(doc, r"s(30^\circ)=28.249,\qquad s(31^\circ)=28.720")
formula(doc, r"\frac{\Delta s}{\Delta\theta}=\frac{0.471}{\pi/180}\approx26.99\ \mathrm{mm/rad}")
para(doc, "与解析值 27.04 相差 0.2%（差分步长较大所致）。", size=9.5, color="64748B")

para(doc, "5.7  零位特例", bold=True)
formula(doc, r"\left.\frac{ds}{d\theta}\right|_0=\frac{\gamma}{2s_0},\qquad r(0)=-\frac{\gamma}{2\sqrt{\alpha+\beta}}")
para(doc, "C2 代入：−647/(2×14.671) = −22.05 mm。", indent=True)

para(doc, "5.8  力臂对角度的导数（线性化用）", bold=True)
formula(doc, r"r'(\theta)=\frac{(\beta\cos\theta+\gamma\sin\theta)s+(\beta\sin\theta-\gamma\cos\theta)s'}{2s^2}")

para(doc, "5.9  常见错误", bold=True)
table(doc, ["错误", "后果"],
      [["忘记链式，写成 f′ 本身", "少 1/(2s)，量级差约 50 倍"],
       ["符号写反：+βsinθ", "r 变号，控制方向反"],
       ["分母写成 2 或 s", "数值不对"],
       ["角度用度直接代入", "三角函数全错"]],
      widths=[6.5, 8.5], center_body=False)

# ============ 6 ============
doc.add_heading("6  R 的拼装", level=1)
para(doc, "6.1  每一格", bold=True)
formula(doc, r"R_{ij}=-\frac{\partial l_i}{\partial q_j}=-\frac{ds_{ij}}{d\theta_j}=r_{ij}(\theta_j)")
para(doc, "6.2  零位数值（mm）", bold=True)
table(doc, ["", "C1", "C2", "C3"],
      [["roll", "−0.259", "−22.050", "+17.372"],
       ["pitch", "−58.105", "+11.805", "+10.990"]],
      widths=[3.0, 4.0, 4.0, 4.0], bold_cols=(1, 2, 3))
doc.add_paragraph()
para(doc, "6.3  pitch 段的差异", bold=True)
table(doc, ["项", "roll", "pitch"],
      [["轴心 o", "(0,0,0)", "(0,0,24)"],
       ["轴 â", "+Y", "+X"],
       ["端点", "P4、P5", "P6、P7"]],
      widths=[4.0, 5.5, 5.5], center_body=False)

# ============ 7 ============
doc.add_heading("7  工程实现", level=1)
para(doc, "7.1  每段 5 个常数", bold=True)
para(doc, "把第 4 章的结果压成 u₁、u₂、v₁、v₂、h，运行时只需：", indent=True)
formula(doc, r"d_1=v_1\cos\theta-v_2\sin\theta-u_1")
formula(doc, r"d_2=v_1\sin\theta+v_2\cos\theta-u_2")
formula(doc, r"s=\sqrt{d_1^2+d_2^2+h^2},\qquad r=\frac{u_2d_1-u_1d_2}{s}")
para(doc, "7.2  计算量", bold=True)
bullet(doc, "每段：2 次 sin/cos + 4 次乘法 + 1 次开方；")
bullet(doc, "三根绳 × 两段 = 6 次调用，得到 R 的 6 个元素；")
bullet(doc, "9,249 个姿态验证：float32 与 double 最大差 4.67×10⁻⁵ mm。")

# ============ 8 ============
doc.add_heading("8  数值验证", level=1)
para(doc, "8.1  C2 / roll，θ = 30° 全流程", bold=True)
formula(doc, r"\vec{v}=(-32.5,-12,18),\qquad \vec{v}_\perp=(-32.5,0,18),\qquad h=-12")
formula(doc, r"\mathrm{Rot}(\theta)\vec{v}_\perp=(-19.145,0,31.839)")
formula(doc, r"\vec{B}=(0,0,0)+(0,-12,0)+(-19.145,0,31.839)=(-19.145,-12,31.839)")
formula(doc, r"s=\Vert \vec{B}-\vec{A}\Vert=\sqrt{7.855^2+4^2+26.838^2}=28.249\ \mathrm{mm}")
figure(doc, "讲解图_B三维_30度.png", "图 5  B 点的三维示意（C2 / roll，θ = 30°）", 14.0)

para(doc, "8.2  多角度对照", bold=True)
table(doc, ["θ", "s (mm)", "r (mm)"],
      [["0°", "14.671", "−22.050"], ["25°", "25.884", "−27.124"], ["30°", "28.249", "−27.042"]],
      widths=[3.0, 4.5, 4.5])

# ============ 9 ============
doc.add_heading("9  常见错误", level=1)
table(doc, ["错误", "后果"],
      [["把 pitch 轴心当原点", "力臂全错（差 24 mm 量级）"],
       ["用 ‖v‖ 当半径 b", "少减了轴向分量"],
       ["r 写成 +ds/dθ", "控制方向反，闭环发散"],
       ["角度用度", "cos/sin 结果错"],
       ["忽略解耦条件", "两段互相干扰"]],
      widths=[6.5, 8.5], center_body=False)

# ============ 10 ============
doc.add_heading("10  交互工具", level=1)
para(doc, "推导的每一步都做成了可交互页面：", indent=True)
bullet(doc, "3D_拆解_sri.html：六步拆解，可拖动、调角度、开关元素；")
bullet(doc, "第4步_动画.html：v⊥ 绕轴旋转的动画，实时显示 cos/sin 分量。")
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
p.add_run("直接打开：").font.size = Pt(10.5)
add_link(doc, "3D_拆解_sri.html", "3D_拆解_sri.html")
p.add_run("　　").font.size = Pt(10.5)
add_link(doc, "第4步_动画.html", "第4步_动画.html")
figure(doc, "viz_shots/step4.png", "图 6  第 4 步动画：绿色 r·cosθ、青色 r·sinθ、白色合成结果", 14.6)

doc.add_heading("11  修订记录", level=1)
table(doc, ["日期", "版本", "修改"],
      [["2026-10-22", "v1.0", "初稿：推导与标定"],
       ["2026-10-26", "v1.1", "补 30° 算例、r(θ) 曲线"],
       ["2026-10-27", "v1.2", "重写需求来源，补图"],
       ["2026-10-28", "v2.0", "新增虚功原理推导 R、详细求导章节"],
       ["2026-10-29", "v2.1", "补充作者署名"],
       ["2026-10-29", "v2.2", "修正 25° 力臂（−26.99 → −27.124），相对变化同步改 23.0%"]],
      widths=[3.2, 2.4, 9.4])

for _p in doc.paragraphs:
    if _p.style.name.startswith("Heading"):
        _p.paragraph_format.keep_with_next = True

doc.save(OUT)
print("saved", OUT, os.path.getsize(OUT))
