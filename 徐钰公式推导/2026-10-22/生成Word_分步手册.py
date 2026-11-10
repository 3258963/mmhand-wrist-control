# -*- coding: utf-8 -*-
"""生成《动态 R 矩阵：3D 分步手册》（每步配网页截图）。"""
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

OUT = "腕部_动态R矩阵_分步手册.docx"
TMP = "_fml3"
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


def figure(doc, path, caption, width=14.8):
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


def para(doc, text, size=10.5, bold=False, color=None, after=5, indent=False, keep=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.4
    if indent:
        p.paragraph_format.first_line_indent = Cm(0.74)
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    if bold or keep:
        p.paragraph_format.keep_with_next = True
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.32
    p.add_run(text).font.size = Pt(size)


def label_block(doc, tag, text, color="1D4ED8"):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    r = p.add_run(tag)
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor.from_string(color)
    r2 = p.add_run(text)
    r2.font.size = Pt(10.5)


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

doc.add_heading("动态 R 矩阵：3D 分步手册", level=0)

t = doc.add_table(rows=1, cols=1)
t.style = "Table Grid"
c = t.rows[0].cells[0]
shade(c, "F1F6FF")
c.text = ""
p = c.paragraphs[0]
r = p.add_run("怎么用这本手册：")
r.bold = True
r.font.size = Pt(10.5)
r2 = p.add_run("左边打开 3D 页面，右边看对应的一节。每节分五块——在网页上做什么、看到什么、"
               "公式怎么来、数字是多少、容易错在哪。全部数据以 C2 / roll / 30° 为例。")
r2.font.size = Pt(10.5)
doc.add_paragraph()

para(doc, "页面地址（可改参数直接跳到某一步）：", bold=True)
para(doc, "file:///E:/SLAHAND/mmhand_wrist_control_1.0/徐钰公式推导/2026-10-22/3D_拆解_sri.html"
          "?step=2&c=1&j=roll&tr=30&clean=1", size=9.5, color="334155")
para(doc, "参数：step 0–6、c 选绳（0/1/2）、j 选段（roll/pitch）、tr 角度、clean=1 精简界面。",
     size=9)

# ---------------- 第 0 步 ----------------
doc.add_heading("第 0 步  概览：一根绳，7 段", level=1)
figure(doc, "viz_shots/steps/step0.png", "图 0  整根绳：8 个导向点把它分成 7 段")
label_block(doc, "在网页上：", "点步骤点「0」，关掉「刚体」「坐标轴」，只留「其他绳」。")
label_block(doc, "看到：", "一根绳从底板穿到手掌，中途经过 8 个白点（导向点），被切成 7 段。")
label_block(doc, "公式：", "整根绳长等于 7 段之和。")
formula(doc, r"l=\sum_{k=1}^{7}\Vert P_{k+1}-P_k\Vert")
label_block(doc, "数字：", "C2 整根绳在 30° 时约 105.2 mm。")
label_block(doc, "为什么先看这个：", "只有先分清“哪几段会动”，后面才知道要算几段。")

# ---------------- 第 1 步 ----------------
doc.add_heading("第 1 步  只有两段会变", level=1)
figure(doc, "viz_shots/steps/step1.png", "图 1  只有跨关节的两段会随角度变化")
label_block(doc, "在网页上：", "点「1」。")
label_block(doc, "看到：", "只有 P4–P5（跨 roll）和 P6–P7（跨 pitch）会变长；其余 5 段两端在同一零件上，长度恒定。")
label_block(doc, "公式：", "把常数部分合并成 c，问题化为两个单变量函数之和：")
formula(doc, r"l=c+s_r(\theta_r)+s_p(\theta_p)")
label_block(doc, "数字：", "C2 的 c = 61.26 mm。")
label_block(doc, "为什么能这样拆：", "每段的两端分别固定在关节两侧的零件上，只受一个关节影响——这就是“解耦”。")
label_block(doc, "容易错：", "若绳绕过导向轮被折弯，或者一段跨两个关节，这个拆分就不成立。", color="B45309")

# ---------------- 第 2 步 ----------------
doc.add_heading("第 2 步  减去轴心", level=1)
figure(doc, "viz_shots/steps/step2.png", "图 2  减去轴心：得到 u（固定端）与 v（动端零位）")
label_block(doc, "在网页上：", "点「2」，然后拖动 θ 从 0° 到 30°。")
label_block(doc, "看到：", "黄色点是轴心 o；紫色箭头 u 指向 P4，紫色 v 指向零位 P5；青色虚线是转过 θ 后的 v′，随角度转动。")
label_block(doc, "公式：", "旋转是绕“一条线”，所以先把点写成相对这条线的位置：")
formula(doc, r"\vec{u}=\vec{A}-\vec{o},\qquad \vec{v}=\vec{B}_0-\vec{o}")
label_block(doc, "数字：", "C2 / roll，o 取原点：v = (−32.5, −12, 18)，长度 39.04 mm。")
label_block(doc, "为什么减轴心：", "同一条轴线可以用任意点作参考，但必须减去“这条线上的一个点”，后面的拆分才有意义。")
label_block(doc, "容易错：", "pitch 段的轴心是 (0,0,24)，不是原点；选错整段都错。", color="B45309")

# ---------------- 第 3 步 ----------------
doc.add_heading("第 3 步  量两个半径", level=1)
figure(doc, "viz_shots/steps/step3.png", "图 3  红色虚线是到转轴的垂线，长度就是 a、b")
label_block(doc, "在网页上：", "点「3」，再拖动 θ。")
label_block(doc, "看到：", "两条红色虚线从 P4、P5 垂直落到轴上，交点叫垂足 F；拖动 θ 时虚线的长度不变。")
label_block(doc, "公式：", "先算沿轴分量，再从向量里减掉它：")
formula(doc, r"h_1=\vec{u}\cdot\hat{a},\qquad \vec{u}_\perp=\vec{u}-h_1\hat{a}")
formula(doc, r"a=\Vert \vec{u}_\perp\Vert,\qquad b=\Vert \vec{v}_\perp\Vert")
label_block(doc, "数字：", "a = 27.459 mm，b = 37.152 mm。")
label_block(doc, "为什么不变：", "绕轴转动等于在垂直平面里画圆，圆心在轴上，半径就是“到轴的距离”，转多少都不变。")
label_block(doc, "容易错：", "把 39.04（到轴心的距离）当成 b。到轴心的距离不是半径，必须减掉沿轴分量。", color="B45309")

# ---------------- 第 4 步 ----------------
doc.add_heading("第 4 步  量沿轴错位", level=1)
figure(doc, "viz_shots/steps/step4.png", "图 4  橙色线段 h：两个垂足沿轴方向的差")
label_block(doc, "在网页上：", "点「4」。")
label_block(doc, "看到：", "两个垂足 F 之间沿轴方向的橙色线段，就是 h。")
label_block(doc, "公式：", "两端沿轴坐标之差：")
formula(doc, r"h=h_2-h_1")
label_block(doc, "数字：", "h = 4.000 mm（带符号）。")
label_block(doc, "为什么需要它：", "两点不在同一个“垂直平面”里，差出来的这一段在旋转中不变，最后用勾股定理加回去。")
label_block(doc, "容易错：", "丢掉符号；或者把 h 与半径混在一起。", color="B45309")

# ---------------- 第 5 步 ----------------
doc.add_heading("第 5 步  量夹角", level=1)
figure(doc, "viz_shots/steps/step5.png", "图 5  两条半径在垂直平面内的有向夹角 Δ")
label_block(doc, "在网页上：", "点「5」。")
label_block(doc, "看到：", "两条半径投影到垂直平面后，中间的那段角弧就是 Δ。")
label_block(doc, "公式：", "余弦由点乘给出，正弦由叉乘再点乘给出：")
formula(doc, r"\cos\Delta=\frac{\vec{v}_\perp\cdot \vec{u}_\perp}{ab}")
formula(doc, r"\sin\Delta=-\frac{(\hat{a}\times \vec{v}_\perp)\cdot \vec{u}_\perp}{ab}")
label_block(doc, "数字：", "Δ = 18.49°。")
label_block(doc, "为什么要符号：", "acos 只能给出 0°–180°，分不清偏向哪侧；而力臂的正负取决于偏向，所以必须用 atan2 得到有向角。")
label_block(doc, "容易错：", "只用 acos，导致力臂符号错、闭环反向。", color="B45309")

# ---------------- 第 6 步 ----------------
doc.add_heading("第 6 步  合成绳长与力臂", level=1)
figure(doc, "viz_shots/steps/step6.png", "图 6  合成结果：s、r 与双路校验")
label_block(doc, "在网页上：", "点「6」，下面会显示 s、r 与“双路校验”的差值。")
label_block(doc, "公式：", "垂直平面用余弦定理，轴向用勾股定理：")
formula(doc, r"s^2=a^2+b^2+h^2-2ab\cos(\Delta+\theta)")
formula(doc, r"s^2=\alpha+\beta\cos\theta+\gamma\sin\theta")
formula(doc, r"\alpha=a^2+b^2+h^2,\quad \beta=-2ab\cos\Delta,\quad \gamma=2ab\sin\Delta")
label_block(doc, "数字：", "α = 2150.25，β = −1935，γ = 647；s(30°) = 28.249 mm。")
label_block(doc, "为什么是 Δ+θ：", "转动让两条半径的夹角从 Δ 增加到 Δ+θ。")
label_block(doc, "容易错：", "θ 用度直接代入三角函数；或者把 h 漏掉。", color="B45309")

# ---------------- 第 7 步 ----------------
doc.add_heading("第 7 步  从 s 求力臂 r（网页不显示）", level=1)
label_block(doc, "公式：", "对 s 求导，再按论文约定取负：")
formula(doc, r"\frac{ds}{d\theta}=\frac{\gamma\cos\theta-\beta\sin\theta}{2s}")
formula(doc, r"r=-\frac{ds}{d\theta}=\frac{\beta\sin\theta-\gamma\cos\theta}{2s}")
label_block(doc, "数字：", "r(30°) = −27.04 mm。")
label_block(doc, "物理意义：", "r < 0 表示角度增大时这根绳会变短；r 的绝对值就是“每弧度收多少绳”。")
label_block(doc, "容易错：", "漏掉负号，得到的其实是 +ds/dθ。", color="B45309")

# ---------------- 第 8 步 ----------------
doc.add_heading("第 8 步  六段拼成 R 矩阵", level=1)
para(doc, "对每根绳的每一段重复第 2–7 步，得到 6 个力臂，填进 2×3 的表：")
formula(doc, r"R=-\left(\frac{\partial l}{\partial q}\right)^{\mathrm{T}},\qquad R_{ij}=r_i(\theta_j)")
table(doc, ["", "C1", "C2", "C3"],
      [["roll", "−0.259", "−22.050", "+17.372"],
       ["pitch", "−58.105", "+11.805", "+10.990"]],
      widths=[3.0, 4.0, 4.0, 4.0], bold_cols=(1, 2, 3))
para(doc, "pitch 段只需把轴心换成 (0,0,24)、轴换成 +X、端点换成 P6/P7，其余步骤完全相同。", size=9.5, color="64748B")

# ---------------- 第 9 步 ----------------
doc.add_heading("第 9 步  工程实现：每段 5 个常数", level=1)
para(doc, "把第 3–5 步的结果压成 5 个数：u₁, u₂, v₁, v₂, h。运行时只需：")
formula(doc, r"d_1=v_1\cos\theta-v_2\sin\theta-u_1")
formula(doc, r"d_2=v_1\sin\theta+v_2\cos\theta-u_2")
formula(doc, r"s=\sqrt{d_1^2+d_2^2+h^2},\qquad r=\frac{u_2d_1-u_1d_2}{s}")
para(doc, "三根绳 × 两段 = 6 次调用；单段 2 次 sin/cos、4 次乘法、1 次开方。", size=9.5, color="64748B")

# ---------------- 第 10 步 ----------------
doc.add_heading("第 10 步  自检", level=1)
table(doc, ["检查", "方法", "期望"],
      [["零位绳长", "s(0) 与 CAD 直接量对比", "14.671 mm"],
       ["力臂", "数值微分 −Δs/(2ε) 对比解析式", "误差 < 1e-3"],
       ["符号", "关节正转时该绳应缩短", "r < 0"],
       ["双路", "几何实测 vs c+s_r+s_p", "差 ≈ 1e-14"]],
      widths=[3.2, 8.5, 3.5], center_body=False)

# ---------------- 附录 ----------------
doc.add_heading("附录  操作—公式—数字 对照表", level=1)
table(doc, ["步骤", "操作", "产出", "C2 数值"],
      [["0", "点 0", "看清 7 段", "—"],
       ["1", "点 1", "确定只有两段会变", "c = 61.26"],
       ["2", "点 2，拖 θ", "u, v", "(−32.5, −12, 18)"],
       ["3", "点 3", "a, b", "27.459 / 37.152"],
       ["4", "点 4", "h", "4.000"],
       ["5", "点 5", "Δ", "18.49°"],
       ["6", "点 6", "s", "28.249"],
       ["7", "—", "r", "−27.04"],
       ["8", "切 pitch 段", "R 的 6 格", "见 4.2 表"]],
      widths=[1.4, 3.4, 5.6, 4.8], center_body=False)

doc.save(OUT)
print("saved", OUT, os.path.getsize(OUT))
