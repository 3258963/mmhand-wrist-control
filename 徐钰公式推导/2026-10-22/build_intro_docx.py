# -*- coding: utf-8 -*-
"""Build a plain-text-formula DOCX for the focused dynamic-R note."""
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "飞书_动态R矩阵_原理与实现_纯文本.md"
OUT = ROOT / "飞书_动态R矩阵_原理与实现.docx"

MD = SRC.read_text(encoding="utf-8-sig")
LINES = MD.splitlines()

INK = "1F2328"
BLUE = "1D4ED8"
DARK = "12355B"
MUTED = "57606A"
CODE_BG = "F5F7FA"
QUOTE_BG = "F1F6FF"
HDR_BG = "E8EEF9"

doc = Document()
sec = doc.sections[0]
sec.top_margin = Cm(2.0)
sec.bottom_margin = Cm(2.0)
sec.left_margin = Cm(2.2)
sec.right_margin = Cm(2.2)

# Normal / headings
normal = doc.styles["Normal"]
normal.font.name = "Microsoft YaHei"
normal.font.size = Pt(10.5)
normal.font.color.rgb = RGBColor.from_string(INK)
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

for name, size, color in (("Title", 20, DARK), ("Heading 1", 18, DARK),
                          ("Heading 2", 13.5, BLUE), ("Heading 3", 11.5, "1F3F66")):
    st = doc.styles[name]
    st.font.name = "Microsoft YaHei"
    st.font.size = Pt(size)
    st.font.bold = True
    st.font.color.rgb = RGBColor.from_string(color)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

# Page number
footer_p = sec.footer.paragraphs[0]
footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = footer_p.add_run()
fld = OxmlElement("w:fldSimple")
fld.set(qn("w:instr"), "PAGE")
run._r.addnext(fld)


def set_run_font(run, name="Microsoft YaHei", size=None, color=None, bold=None, italic=None):
    run.font.name = name
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


TOKEN = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*]+\*)")


def add_inline(p, text, size=10.5, color=INK):
    for tok in TOKEN.split(text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
            r = p.add_run(tok[2:-2])
            set_run_font(r, size=size, color=color, bold=True)
        elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
            r = p.add_run(tok[1:-1])
            set_run_font(r, name="Consolas", size=size - 0.7, color="1F4E79")
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            r = p.add_run(tok[1:-1])
            set_run_font(r, size=size, color=color, italic=True)
        else:
            r = p.add_run(tok)
            set_run_font(r, size=size, color=color)


def add_para(text, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.45
    add_inline(p, text, size=size)
    return p


def add_bullet(text, numbered=False):
    p = doc.add_paragraph(style="List Number" if numbered else "List Bullet")
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    add_inline(p, text, size=10.5)
    return p


def shade_paragraph(p, fill):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)


def left_border(p, color="2F5597", sz="18"):
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), sz)
    left.set(qn("w:space"), "6")
    left.set(qn("w:color"), color)
    pBdr.append(left)
    pPr.append(pBdr)


def add_quote(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.right_indent = Cm(0.2)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.4
    shade_paragraph(p, QUOTE_BG)
    left_border(p)
    add_inline(p, text, size=10.0, color="243B53")


def add_code(lines):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.1)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.keep_together = True
    shade_paragraph(p, CODE_BG)
    left_border(p)
    for k, line in enumerate(lines):
        r = p.add_run(line)
        set_run_font(r, name="Consolas", size=8.8, color="16202E")
        if k < len(lines) - 1:
            r.add_break()


def shade_cell(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def set_col_width(cell, cm):
    cell.width = Cm(cm)


def add_table(rows, aligns):
    ncol = len(rows[0])
    t = doc.add_table(rows=1, cols=ncol)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = True
    hdr = t.rows[0].cells
    for i, cell in enumerate(hdr):
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_inline(p, rows[0][i] if rows[0][i] else " ", size=9.0)
        for r in p.runs:
            r.bold = True
        shade_cell(cell, HDR_BG)
    for row in rows[1:]:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            al = WD_ALIGN_PARAGRAPH.LEFT
            if aligns[i] == "right":
                al = WD_ALIGN_PARAGRAPH.RIGHT
            elif aligns[i] == "center":
                al = WD_ALIGN_PARAGRAPH.CENTER
            p.alignment = al
            add_inline(p, val if val else " ", size=8.8)

    # repeat header across pages
    trPr = t.rows[0]._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:tblHeader"))
    # rows should not split internally
    for row in t.rows:
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))

    # keep small tables on one page
    if len(t.rows) <= 5:
        for row in t.rows[:-1]:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True

    # explicit widths for the 4-column impact table
    if ncol == 4 and "行程内实际" in rows[0]:
        widths = [2.6, 2.4, 5.6, 5.6]
        t.autofit = False
        for i, w in enumerate(widths):
            t.columns[i].width = Cm(w)
            for row in t.rows:
                row.cells[i].width = Cm(w)
    return t


def parse_table(lines):
    raw = []
    for line in lines:
        s = line.strip().lstrip("\ufeff")
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        raw.append(cells)
    if not raw:
        return [], []
    header = raw[0]
    aligns = []
    for c in raw[1]:
        c = c.replace(" ", "")
        if c.startswith(":") and c.endswith(":"):
            aligns.append("center")
        elif c.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    rows = [header] + [r for r in raw[2:] if not all(set(c) <= set("-: ") for c in r)]
    return rows, aligns


def add_image(path, width_cm=16.0):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(ROOT / path), width=Cm(width_cm))


def add_caption(text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    add_inline(p, text.strip("*"), size=9.0, color=MUTED)


# ---------------- block parser ----------------
i = 0
while i < len(LINES):
    line = LINES[i]
    s = line.strip().lstrip("\ufeff")
    if not s:
        i += 1
        continue
    if s == "---":
        i += 1
        continue

    if s.startswith("```"):
        i += 1
        buf = []
        while i < len(LINES) and not LINES[i].strip().startswith("```"):
            buf.append(LINES[i])
            i += 1
        i += 1
        add_code(buf)
        continue

    if s.startswith("!["):
        m = re.match(r"!\[.*?\]\((.*?)\)", s)
        if m:
            add_image(m.group(1))
        i += 1
        continue

    if s.startswith("# "):
        p = doc.add_paragraph(style="Title")
        p.paragraph_format.space_after = Pt(10)
        add_inline(p, s[2:], size=20, color=DARK)
        for r in p.runs:
            r.bold = True
        i += 1
        continue

    if s.startswith("## "):
        p = doc.add_paragraph(style="Heading 2")
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(6)
        add_inline(p, s[3:], size=13.5, color=BLUE)
        for r in p.runs:
            r.bold = True
        i += 1
        continue

    if s.startswith("### "):
        p = doc.add_paragraph(style="Heading 3")
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        add_inline(p, s[4:], size=11.5, color="1F3F66")
        for r in p.runs:
            r.bold = True
        i += 1
        continue

    if s.startswith(">"):
        buf = []
        while i < len(LINES):
            t = LINES[i].strip()
            if t == ">":
                buf.append(None)
                i += 1
            elif t.startswith("> "):
                buf.append(t[2:].strip())
                i += 1
            else:
                break
        groups, cur = [], []
        for t in buf:
            if t is None:
                if cur:
                    groups.append(" ".join(cur))
                    cur = []
            else:
                cur.append(t)
        if cur:
            groups.append(" ".join(cur))
        for g in groups:
            add_quote(g)
        continue

    if s.startswith("|"):
        buf = []
        while i < len(LINES) and LINES[i].strip().startswith("|"):
            buf.append(LINES[i])
            i += 1
        rows, aligns = parse_table(buf)
        if rows:
            add_table(rows, aligns)
        continue

    if s.startswith("- "):
        add_bullet(s[2:])
        i += 1
        continue

    if re.match(r"^\d+\.\s+", s):
        add_bullet(re.sub(r"^\d+\.\s+", "", s), numbered=True)
        i += 1
        continue

    # caption
    if s.startswith("*") and s.endswith("*") and not s.startswith("**"):
        add_caption(s)
        i += 1
        continue

    # paragraph: join until blank / block start
    buf = [s]
    i += 1
    while i < len(LINES):
        nxt = LINES[i].strip()
        if not nxt or nxt.startswith(("#", "```", "> ", "|", "- ", "![")):
            break
        if re.match(r"^\d+\.\s+", nxt) or nxt == "---":
            break
        buf.append(nxt)
        i += 1
    add_para(" ".join(buf))

doc.save(OUT)
print("wrote", OUT, OUT.stat().st_size)




