"""Render all figures and tables for the PDF report as PNGs (PIL + SimHei).
Outputs to review_work/figs/*.png at ~210dpi effective."""
import json, math, os
from PIL import Image, ImageDraw, ImageFont

DATA = json.load(open("review_work/viz_data.json", encoding="utf-8"))
OUT = "review_work/figs"
os.makedirs(OUT, exist_ok=True)
FONT = "C:/Windows/Fonts/simhei.ttf"

INK = (35, 38, 45)
MUT = (120, 124, 132)
AXC = (150, 154, 162)
GRID = (222, 224, 228)
C1C = (56, 108, 176)
C2C = (233, 144, 53)
C3C = (95, 160, 78)
RED = (198, 60, 52)
BLU = (36, 70, 130)
BG = (255, 255, 255)
CC = [C1C, C2C, C3C]

def F(sz):
    return ImageFont.truetype(FONT, int(sz))

class Chart:
    def __init__(self, w, h, xdom, ydom, xlabel, ylabel, logx=False, logy=False,
                 ml=110, mr=40, mt=70, mb=90):
        self.w, self.h = w, h
        self.logx, self.logy = logx, logy
        self.ml, self.mr, self.mt, self.mb = ml, mr, mt, mb
        self.pw, self.ph = w - ml - mr, h - mt - mb
        self.img = Image.new("RGB", (w, h), BG)
        self.d = ImageDraw.Draw(self.img)
        self.xdom, self.ydom = xdom, ydom
        self.xlabel, self.ylabel = xlabel, ylabel
        self.fx = F(26); self.fy = F(26); self.fann = F(26); self.ftt = F(28)
        self._frame()

    def _tx(self, v):
        a, b = self.xdom
        if self.logx:
            return self.ml + (math.log10(v) - math.log10(a)) / (math.log10(b) - math.log10(a)) * self.pw
        return self.ml + (v - a) / (b - a) * self.pw

    def _ty(self, v):
        a, b = self.ydom
        if self.logy:
            return self.mt + self.ph - (math.log10(v) - math.log10(a)) / (math.log10(b) - math.log10(a)) * self.ph
        return self.mt + self.ph - (v - a) / (b - a) * self.ph

    def _frame(self):
        d = self.d
        d.rectangle([self.ml, self.mt, self.ml + self.pw, self.mt + self.ph], outline=AXC, width=2)
        xt = self._ticks(self.xdom, self.logx)
        for v, lab in xt:
            x = self._tx(v)
            d.line([x, self.mt + self.ph, x, self.mt + self.ph + 10], fill=AXC, width=2)
            d.text((x, self.mt + self.ph + 16), lab, font=self.fx, fill=MUT, anchor="ma")
        yt = self._ticks(self.ydom, self.logy)
        for v, lab in yt:
            y = self._ty(v)
            d.line([self.ml - 10, y, self.ml, y], fill=AXC, width=2)
            tw = d.textlength(lab, font=self.fy)
            d.text((self.ml - 16 - tw, y - 14), lab, font=self.fy, fill=MUT)
        xl = self.xlabel
        d.text((self.ml + self.pw / 2, self.h - 26), xl, font=self.ftt, fill=INK, anchor="ma")
        yl = self.ylabel
        timg = Image.new("RGB", (600, 44), BG)
            # no-op
        td = ImageDraw.Draw(timg)
        td.text((0, 0), yl, font=self.ftt, fill=INK)
        bb = timg.getbbox()
        timg = timg.crop(bb).rotate(90, expand=True)
        self.img.paste(timg, (max(8, self.ml - 110 - timg.width // 2) - 14, int(self.mt + self.ph / 2 - timg.height / 2)))

    def _ticks(self, dom, log):
        out = []
        if log:
            lo, hi = int(math.floor(math.log10(dom[0]))), int(math.ceil(math.log10(dom[1])))
            for e in range(lo, hi + 1):
                v = 10 ** e
                if dom[0] * 0.999 <= v <= dom[1] * 1.001:
                    out.append((v, ("1e%d" % e).replace("e0", "e").replace("e-", "e−")))
        else:
            a, b = dom
            span = b - a
            step = 10 ** math.floor(math.log10(span / 5))
            for m in (1, 2, 5, 10):
                if span / (step * m) <= 7:
                    step *= m
                    break
            v = math.ceil(a / step) * step
            while v <= b + step * 0.01:
                lab = ("%g" % round(v, 6))
                out.append((v, lab))
                v += step
        return out

    def line(self, pts, color, width=4, dash=None):
        px = [(self._tx(x), self._ty(y)) for x, y in pts]
        if dash is None:
            self.d.line(px, fill=color, width=width, joint="curve")
        else:
            on, off = dash
            for i in range(len(px) - 1):
                x0, y0 = px[i]
                x1, y1 = px[i + 1]
                L = math.hypot(x1 - x0, y1 - y0)
                if L < 1:
                    continue
                t = 0.0
                while t < L:
                    t2 = min(t + on, L)
                    self.d.line([x0 + (x1 - x0) * t / L, y0 + (y1 - y0) * t / L,
                                 x0 + (x1 - x0) * t2 / L, y0 + (y1 - y0) * t2 / L],
                                fill=color, width=width)
                    t = t2 + off

    def dot(self, x, y, color, r=6, outline=None):
        self.d.ellipse([self._tx(x) - r, self._ty(y) - r, self._tx(x) + r, self._ty(y) + r],
                       fill=color, outline=outline, width=3 if outline else 0)

    def bar(self, x, y0, y1, color, wpx=26, alpha=255):
        c = color + (alpha,) if len(color) == 3 else color
        xm = self._tx(x)
        ya, yb = self._ty(y0), self._ty(y1)
        self.d.rectangle([xm - wpx / 2, min(ya, yb), xm + wpx / 2, max(ya, yb)], fill=color)

    def note(self, x, y, s, color=None, anchor="la", size=26):
        self.d.text((x, y), s, font=F(size), fill=color or INK, anchor=anchor)

    def pixel_note(self, px, py, s, color=None, anchor="la", size=26):
        self.d.text((px, py), s, font=F(size), fill=color or INK, anchor=anchor)

    def legend(self, items, y=None):
        x = self.ml + 4
        y = y or (self.mt - 44)
        for color, label, dash in items:
            if color is None:
                self.d.rectangle([x, y + 2, x + 34, y + 18], outline=INK, width=3)
            else:
                if dash:
                    self.d.line([x, y + 10, x + 15, y + 10], fill=color, width=6)
                    self.d.line([x + 22, y + 10, x + 34, y + 10], fill=color, width=6)
                else:
                    self.d.line([x, y + 10, x + 34, y + 10], fill=color, width=6)
            self.d.text((x + 42, y), label, font=F(26), fill=INK)
            x += 46 + self.d.textlength(label, font=F(26)) + 30

    def save(self, name):
        self.img.save("%s/%s.png" % (OUT, name))
        print("saved", name, self.img.size)

def r_of(abc, deg):
    t = math.radians(deg)
    s = math.sqrt(abc["A"] + abc["B"] * math.cos(t) + abc["C"] * math.sin(t))
    return (abc["B"] * math.sin(t) - abc["C"] * math.cos(t)) / (2 * s)

def s_of(abc, deg):
    t = math.radians(deg)
    return math.sqrt(abc["A"] + abc["B"] * math.cos(t) + abc["C"] * math.sin(t))

def abc_of(cable, seg):
    return next(a for a in DATA["abc"] if a["cable"] == cable and a["seg"] == seg)

# ---------- fig 1: schema ----------
def fig_schema():
    W, H = 1500, 820
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    proj = lambda p: (p["x"] - 0.55 * p["z"], -0.82 * p["y"] + 0.30 * p["x"] + 0.45 * p["z"])
    extra = [{"x": 0, "y": -45, "z": 0}, {"x": 0, "y": 115, "z": 0},
             {"x": -65, "y": 0, "z": 24}, {"x": 75, "y": 0, "z": 24}]
    pts = DATA["pts24"] + extra
    P = [proj(p) for p in pts]
    xs = [q[0] for q in P]; ys = [q[1] for q in P]
    sx = lambda v: 90 + (v - min(xs)) / (max(xs) - min(xs)) * (W - 220)
    sy = lambda v: H - 90 - (v - min(ys)) / (max(ys) - min(ys)) * (H - 200)
    def Q(p):
        q = proj(p)
        return (sx(q[0]), sy(q[1]))
    def axline(a, b, color, dash=None, w=4):
        pa, pb = Q(a), Q(b)
        if dash:
            L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            t = 0
            while t < L:
                t2 = min(t + dash, L)
                d.line([pa[0] + (pb[0] - pa[0]) * t / L, pa[1] + (pb[1] - pa[1]) * t / L,
                        pa[0] + (pb[0] - pa[0]) * t2 / L, pa[1] + (pb[1] - pa[1]) * t2 / L],
                       fill=color, width=w)
                t = t2 + dash * 0.8
        else:
            d.line([pa, pb], fill=color, width=w)
    axline({"x": 0, "y": -45, "z": 0}, {"x": 0, "y": 115, "z": 0}, INK)
    axline({"x": -65, "y": 0, "z": 24}, {"x": 75, "y": 0, "z": 24}, INK)
    axline({"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 24}, RED, dash=14, w=4)
    q = Q({"x": 0, "y": 118, "z": 0}); d.text((q[0] + 8, q[1] - 10), "roll 轴 a=(0,1,0)", font=F(28), fill=INK)
    q = Q({"x": 75, "y": 0, "z": 24}); d.text((q[0] - 8, q[1] - 44), "pitch 轴 a=(1,0,0) 过 (0,0,24)", font=F(28), fill=INK, anchor="ra")
    q = Q({"x": 0, "y": 0, "z": 24}); d.text((q[0] + 10, q[1] + 16), "24 mm 偏置（公垂线）", font=F(28), fill=RED)
    for ci in (1, 2, 3):
        chain = [p for p in DATA["pts24"] if p["cable"] == ci]
        chain.sort(key=lambda p: int(p["id"].split("P")[1]))
        poly = [Q(p) for p in chain]
        d.line(poly, fill=CC[ci - 1], width=7 if ci == 2 else 4, joint="curve")
        for p in poly:
            r = 9 if ci == 2 else 6
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=CC[ci - 1])
    for idx in (4, 5, 6, 7):
        p = [q for q in DATA["pts24"] if q["id"] == "C2-P0%d" % idx][0]
        q = Q(p)
        d.text((q[0], q[1] - 16), "P%d" % idx, font=F(26), fill=INK, anchor="ma")
    q = Q([p for p in DATA["pts24"] if p["id"] == "C2-P05"][0])
    d.text((q[0] + 12, q[1] + 8), "P4–P5 跨 roll", font=F(28), fill=C2C)
    q = Q([p for p in DATA["pts24"] if p["id"] == "C2-P07"][0])
    d.text((q[0] + 12, q[1] + 8), "P6–P7 跨 pitch", font=F(28), fill=C2C)
    x = 100
    for color, label in [(CC[0], "绳 C1"), (CC[1], "绳 C2"), (CC[2], "绳 C3"), (INK, "关节轴"), (RED, "两轴公垂线 24mm")]:
        d.line([x, 44, x + 36, 44], fill=color, width=7)
        d.text((x + 44, 30), label, font=F(28), fill=INK)
        x += 50 + d.textlength(label, font=F(28)) + 34
    img.save("%s/schema.png" % OUT); print("saved schema")

# ---------- fig 2: grid residual ----------
def fig_grid():
    cats = ["roll/C1", "roll/C2", "roll/C3", "pitch/C1", "pitch/C2", "pitch/C3"]
    c = Chart(1500, 620, (1e-6, 0.1), (1e-6, 0.1), "最大差 |ΔR|（mm，对数轴）", "最大差（mm）",
              logx=True, logy=True, ml=120)
    for i, cat in enumerate(cats):
        v = DATA["myMax"][i]
        vd = DATA["docMax"][i]
        col = RED if cat == "pitch/C1" else C1C
        c.bar(v, v, 1e-6 if False else c.ydom[0], col, wpx=34)
        x = c._tx(v); y = c._ty(v)
        c.d.line([x - 46, y, x + 46, y], fill=INK, width=5)
        c.d.text((x, y - 40), "%.3g" % v, font=F(26), fill=INK, anchor="ma")
        c.d.text((x, c.mt + c.ph + 52), cat, font=F(26), fill=INK, anchor="ma")
    c.d.text((c.ml + c.pw - 6, c.mt + 12), "横线＝文档声称值（与独立复现重合）", font=F(26), fill=INK, anchor="rs")
    c.save("grid")

# ---------- fig 3: stencil ----------
def fig_stencil():
    st = DATA["stencil"]
    c = Chart(1500, 560, (-25, 45), (-60, -8), "pitch 角（°）", "C1 pitch 段力臂（mm）", ml=120)
    c.line(list(zip(st["ang"], st["rana"])), C1C, 5)
    c.line(list(zip(st["ang"], st["rst"])), C3C, 5, dash=(16, 12))
    c.d.text((c._tx(38), c._ty(-20)), "两条曲线几乎重合", font=F(28), fill=INK, anchor="rs")
    c.legend([(C1C, "解析导数 r(θ)", None), (C3C, "0.2° 三点差分（同一解析长度）", 14)])
    c.save("stencil_top")
    c2 = Chart(1500, 500, (-25, 45), (0, 0.037), "pitch 角（°）", "两者之差（mm）", ml=120)
    c2.line(list(zip(st["ang"], st["dif"])), C3C, 5)
    c2.dot(-25, 0.032668, RED, 9)
    c2.d.text((c2._tx(-23.6), c2._ty(0.0330)), "边界单侧模板：0.032668 mm @ −25°", font=F(28), fill=INK)
    c2.d.text((c2.ml + c2.pw - 6, c2.mt + 12), "同一模板作用于 CAD 原始长度 → 与原表仅差 7.1e−12 mm",
              font=F(26), fill=INK, anchor="rs")
    c2.save("stencil_dif")

# ---------- fig 4: sign ----------
def fig_sign():
    abc = abc_of("C2", "roll")
    xs = [x * 0.5 for x in range(-50, 51)]
    right = [(x, r_of(abc, x)) for x in xs]
    wrong = []
    for x in xs:
        t = math.radians(x)
        s = s_of(abc, x)
        wrong.append((x, (-647 * math.cos(t) + 1935 * math.sin(t)) / (2 * s)))
    c = Chart(1500, 760, (-25, 25), (-66, 14), "roll 角（°）", "C2 roll 力臂（mm）", ml=110)
    c.line(wrong, RED, 5, dash=(18, 12))
    c.line(right, C2C, 6)
    for a, v in DATA["cadC2roll"]:
        c.dot(a, v, INK, 5)
    c.dot(0, -22.05, BG, 10, outline=INK)
    c.d.text((c._tx(0), c._ty(-22.05) + 34), "θ=0：两式同为 −22.05（错误被掩盖）", font=F(27), fill=INK, anchor="ma")
    xv = c._tx(17)
    c.d.line([xv, c._ty(-62), xv, c._ty(12)], fill=GRID, width=3)
    c.d.text((c._tx(17), c._ty(12) - 40), "θ=17°：CAD −26.78 ✓正确式；印刷式 ≈ −1.2 ✗", font=F(27), fill=INK, anchor="ma")
    c.legend([(C2C, "正确式 (23) 代入：r=(βsinθ−γcosθ)/(2√D)", None),
              (RED, "文档 (27) 印刷式（sin 项符号错）", 18),
              (None, "CAD 网格点（pitch=0，51 点）", None)])
    c.save("sign")

# ---------- fig 5: decouple ----------
def fig_decouple():
    c = Chart(1500, 620, (1e-9, 10), (1e-9, 10), "混合偏导 |∂²l/∂θr∂θp|（mm/rad²，对数轴）", "（mm/rad²）",
              logx=True, logy=True, ml=130)
    for i, k in enumerate(["C1", "C2", "C3"]):
        cur = 1e-8
        cnt = DATA["decoupleCounter"][i]
        c.bar(cur, cur, c.ydom[0], C1C, wpx=30)
        c.bar(cnt, cnt, c.ydom[0], C2C, wpx=30)
        xm = (c._tx(cur) + c._tx(cnt)) / 2
        c.d.text((xm, c.mt + c.ph + 52), k, font=F(27), fill=INK, anchor="ma")
        c.d.text((c._tx(cnt) + 6, c._ty(cnt) - 40), "%.3g" % cnt, font=F(26), fill=INK, anchor="ma")
    c.d.text((c._tx(1e-8) - 20, c._ty(1e-8) - 44), "≈0（解析恒为 0）", font=F(26), fill=INK, anchor="ra")
    c.d.text((c.ml + c.pw - 6, c.mt + 12), "左柱＝当前绳路；右柱＝加 base→palm 直连段后耦合出现",
             font=F(26), fill=INK, anchor="rs")
    c.legend([(C1C, "当前绳路（数值 ≤1e−8）", None), (C2C, "反例：base→palm 直连段", None)])
    c.save("decouple")

# ---------- fig 6: smin ----------
def fig_smin(seg):
    lo, hi = (-25, 25) if seg == "roll" else (-25, 45)
    xs = [x * 0.25 for x in range(int(lo * 4), int(hi * 4) + 1)]
    curves = []
    for i, k in enumerate(["C1", "C2", "C3"]):
        abc = abc_of(k, seg)
        curves.append((k, abc, [(x, s_of(abc, x)) for x in xs]))
    ymax = max(max(p[1] for p in cv[2]) for cv in curves) * 1.1
    c = Chart(1500, 560, (lo, hi), (0, ymax), seg + " 角（°）", "段长 s（mm）", ml=100)
    for i, (k, abc, pts) in enumerate(curves):
        c.line(pts, CC[i], 5)
        m = abc["minAng"]
        if lo <= m <= hi:
            col = RED if (k == "C1" and seg == "pitch") else CC[i]
            c.dot(m, abc["minS"], col, 9)
            c.d.text((c._tx(m), c._ty(abc["minS"]) - 42), "%.2f" % abc["minS"], font=F(26), fill=INK, anchor="ma")
    if seg == "pitch":
        c.d.text((c._tx(-24), c.mt + 14), "C1/pitch 仅 3.90 mm @ −25°：短段高危区", font=F(27), fill=RED)
    c.legend([(CC[i], "%s/%s" % (["C1", "C2", "C3"][i], seg), None) for i in range(3)])
    c.save("smin_" + seg)

# ---------- fig 7: grad ----------
def fig_grad():
    pts = ["P04", "P05", "P06", "P07"]
    c = Chart(1500, 620, (0, 4), (0, 2.5), "跨关节段端点", "‖∇P R‖（mm/mm）", ml=110)
    bw = 0.13
    for i, p in enumerate(pts):
        for j in range(3):
            v = DATA["grad"][p][j]
            x = i + 0.22 + j * 0.2
            c.bar(x, v, 0, CC[j], wpx=40)
            if v > 0.6:
                c.d.text((c._tx(x), c._ty(v) - 40), "%.2f" % v, font=F(26), fill=INK, anchor="ma")
        c.d.text((c._tx(i + 0.5), c.mt + c.ph + 52), p, font=F(27), fill=INK, anchor="ma")
    c.d.text((c.ml + c.pw - 6, c.mt + 12), "−25° 时 C1/pitch 对 P06 梯度达 15.7 mm/mm",
             font=F(26), fill=INK, anchor="rs")
    c.legend([(CC[j], ["C1", "C2", "C3"][j], None) for j in range(3)])
    c.save("grad")

# ---------- fig 8: phase ----------
def fig_phase():
    abc = abc_of("C2", "roll")
    delta = math.radians(3.7)
    Bp = abc["B"] * math.cos(delta) + abc["C"] * math.sin(delta)
    Cp = abc["C"] * math.cos(delta) - abc["B"] * math.sin(delta)
    xs = [x * 0.5 for x in range(-50, 51)]
    d1 = [(q, abc["A"] + abc["B"] * math.cos(math.radians(q) + delta) + abc["C"] * math.sin(math.radians(q) + delta)) for q in xs]
    d2 = [(q, abc["A"] + Bp * math.cos(math.radians(q)) + Cp * math.sin(math.radians(q))) for q in xs]
    d0 = [(q, abc["A"] + abc["B"] * math.cos(math.radians(q)) + abc["C"] * math.sin(math.radians(q))) for q in xs]
    ymin = min(min(p[1] for p in d1), min(p[1] for p in d0)) * 0.92
    ymax = max(max(p[1] for p in d1), max(p[1] for p in d0)) * 1.05
    c = Chart(1500, 560, (-25, 25), (ymin, ymax), "编码器读数 q（°）", "D = s²（mm²）", ml=130)
    c.line(d0, MUT, 4)
    c.line(d1, C1C, 7)
    c.line(d2, C3C, 5, dash=(16, 12))
    c.d.text((c._tx(-24), c.mt + 14), "实线与虚线完全重合 ⇒ 长度数据无法区分 (β,γ,δ) 与 (β′,γ′,0)",
             font=F(27), fill=INK)
    c.legend([(C1C, "真实参数 D(q+δ; β,γ)", None), (C3C, "等效参数 D(q; β′,γ′)，δ=0", 16), (MUT, "参考：未移相 D(q; β,γ)", None)])
    c.save("phase")

# ---------- fig 9: preload ----------
def fig_preload():
    rolls, pitches = DATA["rolls"], DATA["pitches"]
    ml, mt, mr, mb = 110, 40, 40, 90
    W = 1500
    cw = min((W - ml - mr) / len(rolls), 14)
    H = int(mt + mb + len(pitches) * cw)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    okc = (208, 212, 220); badc = (216, 88, 78)
    for i, p in enumerate(pitches):
        row = DATA["pmap"][i]
        for j, r in enumerate(rolls):
            d.rectangle([ml + j * cw, mt + i * cw, ml + (j + 1) * cw - 1, mt + (i + 1) * cw - 1],
                        fill=okc if row[j] == "1" else badc)
    ph = len(pitches) * cw
    f = F(26)
    for v in range(-20, 26, 10):
        x = ml + (v - rolls[0]) * cw
        d.line([x, mt + ph, x, mt + ph + 10], fill=AXC, width=2)
        d.text((x, mt + ph + 14), "%d°" % v, font=f, fill=MUT, anchor="ma")
    for v in range(-20, 50, 10):
        y = mt + (v - pitches[0]) * cw
        d.line([ml - 10, y, ml, y], fill=AXC, width=2)
        d.text((ml - 16, y - 14), "%d°" % v, font=f, fill=MUT, anchor="ra")
    d.text((ml + len(rolls) * cw / 2, H - 30), "roll（°）", font=F(28), fill=INK, anchor="ma")
    tmp = Image.new("RGB", (700, 44), BG)
    ImageDraw.Draw(tmp).text((0, 0), "pitch（°）", font=F(28), fill=INK)
    bb = tmp.getbbox(); tmp = tmp.crop(bb).rotate(90, expand=True)
    img.paste(tmp, (ml - 96 - tmp.width, int(mt + ph / 2 - tmp.height / 2)))
    d.rectangle([ml, mt, ml + 20, mt + 20], fill=okc)
    d.text((ml + 28, mt - 2), "存在全正预紧方向", font=f, fill=INK)
    d.rectangle([ml + 260, mt, ml + 280, mt + 20], fill=badc)
    d.text((ml + 288, mt - 2), "不存在（共 1,664 / 3,621 姿态）", font=f, fill=INK)
    d.text((ml + len(rolls) * cw - 4, mt - 40), "满秩 ≠ 可实现任意力矩：张力分配需单独校验",
           font=F(26), fill=INK, anchor="ra")
    img.save("%s/preload.png" % OUT); print("saved preload", img.size)

# ---------- tables ----------
def wrap_text(d, s, font, width):
    lines, cur = [], ""
    for ch in s:
        if ch == "\n":
            lines.append(cur); cur = ""
            continue
        if d.textlength(cur + ch, font=font) > width:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines

def make_table(name, headers, rows, widths, W=1500, fs=25, hfs=25):
    HROW = 52
    img_h_margin = 24
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f, hf = F(fs), F(hfs)
    all_rows = []
    for r in rows:
        cells = []
        for i, cell in enumerate(r):
            lines = wrap_text(d0, str(cell), f, widths[i] - 18)
            cells.append(lines)
        all_rows.append(cells)
    total_h = img_h_margin + HROW + sum(max(len(c) for c in cells) * (fs + 8) + 16 for cells in all_rows) + img_h_margin
    img = Image.new("RGB", (W, total_h), BG)
    d = ImageDraw.Draw(img)
    x = img_h_margin
    d.rectangle([x, img_h_margin, x + sum(widths), img_h_margin + HROW], fill=(232, 236, 242))
    for i, htxt in enumerate(headers):
        d.text((x + 10, img_h_margin + 12), htxt, font=hf, fill=INK)
        d.line([x, img_h_margin, x, img_h_margin + HROW], fill=AXC, width=2)
        x += widths[i]
    d.line([x, img_h_margin, x, img_h_margin + HROW], fill=AXC, width=2)
    y = img_h_margin + HROW
    for cells in all_rows:
        rh = max(len(c) for c in cells) * (fs + 8) + 16
        x = img_h_margin
        for i, lines in enumerate(cells):
            yy = y + 8
            for ln in lines:
                d.text((x + 10, yy), ln, font=f, fill=INK)
                yy += fs + 8
            d.line([x, y, x, y + rh], fill=(200, 204, 210), width=2)
            x += widths[i]
        d.line([x, y, x, y + rh], fill=(200, 204, 210), width=2)
        d.line([img_h_margin, y + rh, img_h_margin + sum(widths), y + rh], fill=(200, 204, 210), width=2)
        y += rh
    img.save("%s/%s.png" % (OUT, name)); print("saved", name, img.size)

def fig_tables():
    make_table("tab_problems",
               ["#", "位置", "类别", "问题", "改正建议"],
               [["1", "公式(27)", "数学必错(印刷)",
                 "sin 项符号印错：印刷为 −647cosθ+1935sinθ，应为 −1935sinθ−647cosθ；θ=0 时两式巧合同值，掩盖错误",
                 "分子改为 −(1935sinθ+647cosθ)"],
                ["2", "公式(S4)", "数学必错(印刷)",
                 "分数印成 +ds/dθ，与自身 r=−ds/dθ 及正文 (22)(23) 矛盾", "分子改为 βsinθ−γcosθ"],
                ["3", "复核包", "仅实现问题",
                 "verify_formulas.py 与 复核结果.json 未随包，无法运行原脚本核对", "随包补上或注明获取方式"],
                ["4", "geometry_model.py", "仅实现可读性",
                 "length_arm() 第二返回值是力臂 r 而非长度导数，命名易误读", "改名或加注释"],
                ["5", "第8节", "表述差异",
                 "模板重放差文档记 1.53e−9 mm，本审稿用等价方法得 7.1e−12 mm，结论一致", "注明重放路径"]],
               [60, 190, 210, 720, 260])

    fm = lambda v: ("%.3g" % v)
    rows1 = [["六组 α/β/γ 从 24 点重算 vs JSON", "—", "6 组全等（至 1e−6 mm²）", "通过"],
             ["C2 roll 实例 R_r2(0)", "−22.04970101 mm", "完全相同", "通过"],
             ["解析零位矩阵（6 元素）", "见文档表", "逐位相同（另两条路线亦同）", "通过"],
             ["3,621 姿态长度 L1–L3", "—", "最大差 2.7e−11 mm（机器级）", "通过"],
             ["R 最大差 roll/C1", "2.47e−5 mm", "2.471e−5 mm", "通过"],
             ["R 最大差 roll/C2", "9.65e−4 mm", "9.653e−4 mm", "通过"],
             ["R 最大差 roll/C3", "6.34e−4 mm", "6.342e−4 mm", "通过"],
             ["R 最大差 pitch/C1", "3.267e−2 mm", "3.2668e−2 mm（最差分量）", "通过"],
             ["R 最大差 pitch/C2", "1.48e−4 mm", "1.479e−4 mm", "通过"],
             ["R 最大差 pitch/C3", "1.11e−4 mm", "1.106e−4 mm", "通过"],
             ["RMSE 六分量", "见文档", "逐项相同", "通过"],
             ["200 非网格姿态（闭式 vs 差分）", "6.63e−8 mm", "2.5e−8 mm（同级别）", "通过"]]
    make_table("tab_num1", ["核对项目", "文档值", "独立复现", "判定"], rows1,
               [560, 260, 440, 120])

    rows2 = [["25 条边界原始记录 CAD 长度 vs 模型", "~0", "2.65e−11 mm", "通过"],
             ["0.2° 模板重放（作用于 CAD 长度 vs 原表）", "0 / 1.53e−9 mm", "7.1e−12 mm（结论一致更紧）", "通过"],
             ["解析导数 vs CAD 差分 0.032668 mm", "有限步长截断", "已证实为截断，非模型误差", "通过"],
             ["差分模板截断系数", "中心 h²/6、单侧 h²/3", "代数推导一致", "通过"],
             ["连续最小 s 表（6 段）", "见文档", "6 行全同（含角度）", "通过"],
             ["+1mm 单点扰动表（12 项）", "见文档", "逐项相同", "通过"],
             ["零位梯度范数表（12 项）", "见文档", "逐项相同", "通过"],
             ["轴原点 ∂R/∂o_Y（pitch 行；roll 行=0）", "0.982605/0.999355/0.930400", "完全相同；0.000000", "通过"],
             ["24 mm 偏置两约定", "见文档", "conv1 全同；conv2 至 3e−6 相对差", "通过"],
             ["P06 三口径灵敏度", "16.064268 / 15.185639 / 15.745867", "精确同 / 15.185638 / 15.7431", "通过"],
             ["−25° 预算示例", "1.5246 mm", "1.5246 mm", "通过"],
             ["全正预紧方向不满足数", "1664 / 3621", "3621−1957=1664", "通过"],
             ["框架变换（E.T 正确 / 误转置误差）", "残差 0；≈183.85 mm", "6.9e−18 m；183.8478 mm", "通过"],
             ["PDF 附件 JSON 与 zip JSON", "一致", "points/cables 全同", "通过"]]
    make_table("tab_num2", ["核对项目", "文档值", "独立复现", "判定"], rows2,
               [560, 300, 400, 120])

if __name__ == "__main__":
    fig_schema(); fig_grid(); fig_stencil(); fig_sign(); fig_decouple()
    fig_smin("roll"); fig_smin("pitch"); fig_grad(); fig_phase(); fig_preload()
    fig_tables()
    print("all figures done")
