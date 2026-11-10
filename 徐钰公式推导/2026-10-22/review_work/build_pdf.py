"""Build the complete PDF report: text (PyMuPDF china-s CJK) + PIL figures.
Output: 05_独立核对报告_完整版_2026-10-22.pdf"""
import pymupdf
from PIL import Image

FIGS = "review_work/figs"
OUT = "05_独立核对报告_完整版_2026-10-22.pdf"

PAGE_W, PAGE_H = 595, 842  # A4 portrait
ML, MR, MT, MB = 58, 58, 64, 56
TW = PAGE_W - ML - MR

doc = pymupdf.Document()
page = [doc.new_page()]
y = [MT]

INK = (0.10, 0.11, 0.13)
BLUE = (0.13, 0.25, 0.47)
GRAY = (0.45, 0.47, 0.50)
LIGHT = (0.93, 0.94, 0.96)
RED = (0.72, 0.22, 0.18)

def newpage():
    page[0] = doc.new_page()
    y[0] = MT

def footer_title(p):
    p.insert_text((ML, PAGE_H - 30), "绳驱二轴腕部解析模型 · 独立核对报告（图解完整版）",
                  fontname="china-s", fontsize=7.5, color=GRAY)

def need(h):
    if y[0] + h > PAGE_H - MB:
        newpage()

def para(text, size=10, color=INK, indent=0, leading=1.35, gap=5, first_gap=None):
    rect = pymupdf.Rect(ML + indent, y[0], PAGE_W - MR, PAGE_H - MB)
    leftover = page[0].insert_textbox(rect, text, fontname="china-s",
                                      fontsize=size, color=color, lineheight=leading,
                                      align=pymupdf.TEXT_ALIGN_LEFT)
    used = rect.height - max(0, leftover)
    y[0] += used + gap
    return leftover

def heading(text, level=1):
    sizes = {0: 17, 1: 13, 2: 11.5}
    gaps = {0: (10, 8), 1: (12, 6), 2: (8, 4)}
    before, after = gaps[level]
    h = sizes[level] * 1.8
    need(h + 30)
    y[0] += before
    page[0].insert_text((ML, y[0] + sizes[level]), text, fontname="china-s",
                        fontsize=sizes[level], color=BLUE if level <= 1 else INK)
    y[0] += sizes[level] + 4
    if level <= 1:
        page[0].draw_line(pymupdf.Point(ML, y[0]), pymupdf.Point(PAGE_W - MR, y[0]),
                          color=(0.75, 0.78, 0.82), width=0.8)
        y[0] += after
    else:
        y[0] += after

def formula(text):
    need(20)
    rect = pymupdf.Rect(ML, y[0], PAGE_W - MR, y[0] + 24)
    page[0].insert_textbox(rect, text, fontname="china-s", fontsize=10.5,
                           color=BLUE, align=pymupdf.TEXT_ALIGN_CENTER)
    y[0] += 22

def figure(name, caption, width=None):
    path = "%s/%s.png" % (FIGS, name)
    im = Image.open(path)
    w, h = im.size
    tw = width or TW
    th = tw * h / w
    if th > PAGE_H - MT - MB - 20:
        th = PAGE_H - MT - MB - 20
        tw = th * w / h
    need(th + 30)
    x0 = ML + (TW - tw) / 2
    page[0].insert_image(pymupdf.Rect(x0, y[0], x0 + tw, y[0] + th), filename=path)
    y[0] += th + 4
    rect = pymupdf.Rect(ML, y[0], PAGE_W - MR, y[0] + 14)
    page[0].insert_textbox(rect, caption, fontname="china-s", fontsize=8.5,
                           color=GRAY, align=pymupdf.TEXT_ALIGN_CENTER)
    y[0] += 20

def bullet(text, size=10):
    need(16)
    rect = pymupdf.Rect(ML + 12, y[0], PAGE_W - MR, PAGE_H - MB)
    leftover = page[0].insert_textbox(rect, "• " + text, fontname="china-s",
                                      fontsize=size, color=INK, lineheight=1.35)
    used = rect.height - max(0, leftover)
    y[0] += used + 3

PNO = [1]

# ============ Page 1: cover ============
page[0].draw_rect(pymupdf.Rect(0, 0, PAGE_W, 150), color=None, fill=(0.13, 0.25, 0.47))
page[0].insert_textbox(pymupdf.Rect(ML, 52, PAGE_W - MR, 100),
                       "绳驱二轴腕部解析模型", fontname="china-s", fontsize=22,
                       color=(1, 1, 1), align=pymupdf.TEXT_ALIGN_CENTER)
page[0].insert_textbox(pymupdf.Rect(ML, 92, PAGE_W - MR, 130),
                       "独立核对报告 · 图解完整版", fontname="china-s", fontsize=14,
                       color=(0.85, 0.88, 0.93), align=pymupdf.TEXT_ALIGN_CENTER)
page[0].insert_textbox(pymupdf.Rect(ML, 205, PAGE_W - MR, 300),
    "审稿对象：《绳驱二轴腕部解析模型·最终版》2026-10-22 / v2.0（C2/C3 P03、P04 修正点位）\n"
    "审稿方法：独立向量几何实现（不复用作者代码）＋四条交叉验证路线\n"
    "报告日期：2026-10-22    复现脚本：review_work/ 目录 7 个脚本",
    fontname="china-s", fontsize=10, color=GRAY, align=pymupdf.TEXT_ALIGN_CENTER, lineheight=1.6)
y[0] = 330
# verdict box
box = pymupdf.Rect(ML, y[0], PAGE_W - MR, y[0] + 92)
page[0].draw_rect(box, fill=LIGHT, color=(0.13, 0.25, 0.47), width=1.2)
page[0].insert_textbox(pymupdf.Rect(ML + 16, y[0] + 10, PAGE_W - MR - 16, y[0] + 40),
                       "总体结论：有条件通过", fontname="china-s", fontsize=15, color=BLUE)
page[0].insert_textbox(pymupdf.Rect(ML + 16, y[0] + 40, PAGE_W - MR - 16, y[0] + 88),
    "理想模型（固定中心折线）假设下，推导与数值全部独立复现成立；"
    "需修正公式 (27) 与 (S4) 两处印刷符号错误；实机精度尚未标定，不作任何承诺。",
    fontname="china-s", fontsize=10, color=INK, lineheight=1.4)
y[0] += 110
para("审稿结论速览：① 主数学链（虚功符号、24 mm 偏置运动学、解耦定理、α/β/γ 展开、力臂闭式解、"
     "灵敏度与协方差）经四条互相独立的路线核验：闭式解、嵌套中心差分、0.2° 模板重放、静力学取矩。"
     "② 六组系数、C2 实例、零位矩阵、3,621 网格姿态、25 条边界原始记录、连续最小值表、全部灵敏度表，"
     "逐项与文档一致。③ 唯一实质发现是两处印刷层符号错误；文档数值表与代码均正确。"
     "④ 0.032668 mm 已被证明为差分模板截断误差，不是模型误差，更不是实机误差。", size=10)
para("本 PDF 整合了完整文字报告与 10 幅图、3 张表；正文结构为 ① 总体结论 → ② 问题表 → "
     "③ 关键公式独立推导 → ④ 数值核对 → ⑤ 实机标定方案 → ⑥ 误差承诺边界 → ⑦ 待补测量数据，"
     "并附方法与运行环境声明。", size=10)

# ============ Section 0: mechanism ============
newpage(); heading("0 · 机构与绳路：理解全文的钥匙", 1)
para("三条绳各按 P1→P8 八个标点走中心折线：P1–P4 在基座（静止），P5–P6 在 roll 件上，P7–P8 在手掌上。"
     "两条关节轴互相垂直但不相交——公垂线长 24 mm，即两轴偏置，推导中不可省略。"
     "整根绳只有两段跨关节：P4–P5 跨 roll 轴，P6–P7 跨 pitch 轴；其余五段两端同刚体、长度恒定（其和记为 cᵢ）。"
     "全部解析模型就是围绕这两个跨关节段建立的。")
figure("schema", "图 1 · 零位 F0 系机构示意：三绳八点折线路径、两轴及 24 mm 偏置（红色虚线）")

# ============ ① ============
heading("① 总体结论：有条件通过", 1)
para("在文档声明假设下（刚体、固定导向点中心折线、无摩擦、同绳各段张力相等），主推导链数学成立且全部独立复现。"
     "条件是必须修正两处公式印刷符号错误：公式 (27) 的 sin 项符号、概览式 (S4) 的分数符号（见第 ② 节）。"
     "两处均属\u201c打印了错误代数式\u201d——正文通式 (22)(23)、全部数值表和作者代码是对的，"
     "但读者直接引用这两条印刷式在非零角度会得到错误力臂。"
     "文档对\u201cCAD 内部一致性 ≠ 实机精度\u201d的区分表述诚实且正确，本审稿在数值上证实了这一区分。")

# ============ ② ============
heading("② 问题表（按严重程度）", 1)
figure("tab_problems", "表 1 · 全部遗留问题清单：2 处必改印刷错误、1 处包完整性、2 处实现/表述层面")
heading("印刷错误 (27) 的数值裁定", 2)
para("文档公式 (27) 将 C2 roll 段力臂印刷为 (−647cosθ + 1935sinθ)/(2√D)，而通式 (23) r=(βsinθ−γcosθ)/(2√D) "
     "代入 β=−1935、γ=647 的正确结果应为 −1935sinθ − 647cosθ。θ=0 时两式同为 −22.05 mm，"
     "这个巧合掩盖了错误；但 CAD 网格数据在 roll=+17° 处给出 −26.78 mm，与正确式一致，印刷式在该处给出 ≈−1.2 mm。"
     "经 4 次独立图像判读（含原生位图逐字形）确认印刷内容。概览式 (S4) 为同样的镜像错误：分数印成了 +ds/dθ。")
figure("sign", "图 2 · 符号错误裁定：CAD 数据点全部落在正确曲线（橙）上；红色虚线（印刷式）只在 θ=0 与正确线相切")

# ============ ③ ============
heading("③ 关键公式独立推导", 1)
heading("3.1 虚功与 R 的符号、维度（对文档公式(1)–(4)）", 2)
para("绳张力倾向缩短绳路，第 i 根绳对机构做功 −fᵢdlᵢ。令关节虚功相等：τᵀdq = −fᵀdl = −fᵀJ_l dq 对任意 dq 成立，")
formula("τ = −J_lᵀ f，  即  R = −(∂l/∂q)ᵀ   （2×3：行 = roll/pitch，列 = C1/C2/C3，τ = R f）")
para("单位：长度对 rad 求导为 m/rad，SI 中弧度无量纲，数值上等同等效力臂 m；张力 N × 力臂 m = N·m。"
     "独立验证：用静力学取矩路线 τ = a·[(P动−o)×(−f·u)]（仅跨关节段有贡献，其余段内力相消）"
     "与闭式解最大差 1.4e−12 mm，零位矩阵逐位一致。")
heading("3.2 两轴运动学与 24 mm 偏置（对(10)–(11)）", 2)
formula("P_roll_link = Q_r p₀ ；  P_palm = Q_r[ Q_p p₀ + (I−Q_p) o_p0 ]，  o_p0 = (0,0,24 mm)")
para("palm 点先随 roll、再绕 roll 携带后的 pitch 轴（方向 Q_r a_p0，过点 Q_r o_p0）转动；"
     "24 mm 平移项显式保留。全网格数值一致证明该顺序正确，偏置不可省略。")
heading("3.3 解耦定理与反例（对(12)–(14)）", 2)
formula("P6−P7 = Q_r·[P06 − o_p0 − Q_p(P07−o_p0)] ⇒ ‖P6−P7‖ 只依赖 θ_p；P4P5 只依赖 θ_r")
formula("因此  lᵢ = cᵢ + s_rᵢ(θ_r) + s_pᵢ(θ_p)")
para("这是当前绳路归属（P1–P4 在 base、P5–P6 在 roll_link、P7–P8 在 palm、无 base 直连 palm 段）的结构性质。"
     "反例（已数值实现）：增加一段 base P03→palm P08 直连后，混合偏导从 0 变为 C2=+1.37、C3=−1.24 mm/rad²，"
     "两角耦合出现，单变量分解失效。")
figure("decouple", "图 3 · 解耦与反例（对数轴）：当前绳路混合偏导解析恒为 0；加直连段后耦合立即出现")
heading("3.4 α/β/γ 几何展开（对(15)–(21)）", 2)
formula("s² = ‖u−Qv‖² = α + β cosθ + γ sinθ，  u=A−o，v=B₀−o")
formula("α = ‖u‖²+‖v‖²−2(u·a)(v·a)；  β = −2[u·v−(u·a)(v·a)]；  γ = −2 u·(a×v)   （单位：长度²）")
para("轴上原点沿 a 平移时 u⊥、v⊥、u∥−v∥ 与 u·(a×v) 均不变，故三系数不变（规范自由度）。"
     "α ≥ ρ=√(β²+γ²)=2‖u⊥‖‖v⊥‖ 由 AM-GM 保证；六段实际裕量 14.8～215.9 mm²，无零长奇异。"
     "六组系数从 24 点坐标独立重算与参数 JSON 全等。")
heading("3.5 力臂导数（对(22)–(25)）", 2)
formula("ds/dθ = (−βsinθ + γcosθ)/(2√D)；  r = −ds/dθ = (βsinθ − γcosθ)/(2√D)")
para("C2 roll 段 θ=0：r = −647/(2√215.25) = −22.04970101 mm，与文档一致。"
     "注意：文档第一部分概览式 (S4) 与代入示例 (27) 的印刷符号与此处正确式相反，见第 ② 节。")
heading("3.6 灵敏度、协方差与相位耦合（对(31)–(38)、C4）", 2)
formula("N = βsinθ − γcosθ：  ∂r/∂α = −N/(4D^1.5)")
formula("∂r/∂β = sinθ/(2√D) − Ncosθ/(4D^1.5)；  ∂r/∂γ = −cosθ/(2√D) − Nsinθ/(4D^1.5)")
formula("Cov(vec R) ≈ J_z Σ_z J_zᵀ；  |Δτ_j| ≤ Σᵢ |ΔR_ji||fᵢ|")
para("三式与有限差分吻合到 8~9 位有效数字。相位耦合：D(q+δ;β,γ) = D(q;β′,γ′)，"
     "β′=βcosδ+γsinδ、γ′=γcosδ−βsinδ（数值残差 5.4e−19 m²）。"
     "⇒ 无外部基准时零偏 δ 与 β/γ 不可分离；每关节 10 个名义参数 −1 相位规范 = 9 个有效参数；仅测 Δl 时 cᵢ 不可辨识。")
figure("phase", "图 4 · 相位耦合：真实参数（实线）与吸收 δ 后的等效参数（虚线）给出完全相同的观测量")

# ============ ④ ============
heading("④ 数值核对结果", 1)
para("环境：Windows 10 (22621) x64，Python 3.12.10，数值计算仅标准库；PDF 解包用 PyMuPDF（不参与数值）。"
     "独立实现：Rodrigues 主动旋转 + 父子刚体链 + 24 mm 偏置；嵌套中心差分 h=1e−6 rad；"
     "三点 Lagrange 模板重放；静力学取矩；空间梯度中心差分 h=1e−4 m + Richardson。"
     "verify_formulas.py 与 复核结果.json 未随包（已搜索工作区、zip、PDF 附件），故未运行原作者脚本，"
     "全部结论出自独立实现。")
figure("tab_num1", "表 2 · 数值核对（一）：系数、实例、全网格残差")
figure("tab_num2", "表 3 · 数值核对（二）：模板重放、灵敏度表、预紧计数、框架变换")
figure("grid", "图 5 · 3,621 姿态全网格残差（对数轴）：条柱＝独立复现最大差，横线＝文档声称值，二者重合")
heading("0.0327 mm 之谜：三种误差的区分", 2)
para("解析导数与 CAD 0.2° 差分表的最大差为 0.032668 mm（pitch/C1 分量，位于 (4°,−25°)）。"
     "将同一三点模板直接作用于 CAD 原始长度再与原表比较，最大差仅 7.1e−12 mm——"
     "证明 CAD 的 R 表本身就是该模板差分出来的，0.0327 mm 全部来自模板对真导数的截断"
     "（内部中心模板 h²/6、边界单侧模板 h²/3），不是模型失配，更不是实机误差。")
figure("stencil_top", "图 6 · 解析导数（蓝实线）与 0.2° 差分（绿虚线）几乎重合")
figure("stencil_dif", "图 7 · 两曲线之差随 pitch 角变化：峰值 0.032668 mm 恰在 −25° 边界（单侧模板）")

# ============ short-segment risk ============
heading("短段风险与误差预算（文档 C1/C3 节复核）", 1)
para("六段绳长在连续角范围内的最小值全部复现（含最小值所在角度）。C1/pitch 段在 −25° 仅 3.90 mm，"
     "是全机构最短的段；其余五段均 >10.4 mm。零位单点灵敏度表 12 项逐项复现："
     "P04 最敏感（C3 达 2.20 mm/mm），P07 最迟钝（0.18 mm/mm）。"
     "在 −25° 处 C1/pitch 对 P06 的位置梯度范数达 15.7 mm/mm：0.05 mm 点位误差的一阶预算约 1.52 mm 力臂误差"
     "（文档示例 1.5246 mm 精确复现）。结论：pitch ≤ −24° 为低置信区，须单独标定验收，不能被全局平均掩盖。")
figure("smin_roll", "图 8 · roll 段长度曲线与最小值（roll ∈ [−25°, 25°]）")
figure("smin_pitch", "图 9 · pitch 段长度曲线与最小值：C1/pitch 在 −25° 仅 3.90 mm（红点，高危区）")
figure("grad", "图 10 · 零位单点灵敏度（‖∇P R‖，mm/mm）：P04–P07 × C1–C3")

# ============ ⑤ ============
heading("⑤ 实机标定方案与可辨识性风险", 1)
bullet("先定规范：机械检具确定两关节机械零位与正方向（外部固定 δ），绝不与几何系数同时自由拟合；固定全局坐标系。")
bullet("独立标定收放测量链：编码器→收放长度换算（卷绕半径、绕层）、空载往返回差，先于几何标定。")
bullet("单轴扫掠（利用解耦结构）：固定 roll 扫 pitch、固定 pitch 扫 roll；静置采样；低/中/高三种预紧各一次往返。")
bullet("组合姿态验证实机解耦（R_r 不随 θ_p 漂移等）；数据分标定集 / 独立验证集。")
bullet("识别顺序：先六组 α/β/γ（+c 若测绝对长度），约束 D>0 与 α≥ρ；报告验证集 Δl 的 RMSE / 95% 分位数 / 最大差。")
bullet("摩擦/弹性分离：不同预紧下 Δl(q) 曲线族分离度→弹性；往返迟滞环宽→摩擦回差；不得混入几何长度。")
bullet("风险：δ 与 β/γ 相位耦合（无外部基准每关节必损失 1 维）；仅 Δl 时 cᵢ 不可辨识；"
       "参数雅可比须查秩 / 条件数；C1 pitch≤−24° 短段区单独标定；1,664/3,621 姿态无全正预紧方向"
       "（满秩 ≠ 可实现任意力矩）；轴线现仅由三 CAD 姿态恢复，需实测确认。")
figure("preload", "图 11 · 预紧可行性地图：红色区域（1,664/3,621 姿态）不存在全正内部预紧方向")

# ============ ⑥ ============
heading("⑥ 能承诺与不能承诺的误差", 1)
heading("能承诺（理想模型内）", 2)
para("固定中心折线假设下推导与实现的数学正确性（多路线独立验证）；单位与符号约定自洽；"
     "CAD 体系内部一致性（长度残差机器级 2.7e−11 mm；R 差上限 0.032668 mm 已证明为差分截断）。")
heading("不能承诺", 2)
para("真机力臂误差的任何数值（\u201c≤0.0327 mm\u201d\u201c≤0.1 mm\u201d均不成立）；中心折线与真实瓷环滑动接触的偏差；"
     "摩擦 / 弹性 / 回差的影响量；轴线与 24 mm 偏距的实物准确性（尚无实测）；加工装配偏差下的力矩精度；"
     "张力可行域内的承载能力。", color=RED)

# ============ ⑦ ============
heading("⑦ 需要补充的测量数据", 1)
bullet("两轴方向、位置与 24 mm 最短偏距的实测（三坐标 / 激光跟踪 / 检具），注明装配基准。")
bullet("跨刚体段端点关键尺寸：至少 C1 的 P06、P07 及各 P04、P05 位置（零位最敏感点 P04：1.35~2.20 mm/mm）。")
bullet("机械零位基准的实物定义与 δ 标定记录。")
bullet("电机收放链标定数据：卷绕半径 / 层数换算、空载回差、重复性。")
bullet("单轴扫掠 Δl(q) 数据集：角度、预紧水平、运动方向、重复次数、张力（若有）。")
bullet("C1 pitch 负角区（≤−24°）专门数据。")
bullet("（建议）关节力矩与绳张力同步测量，用于最终验证 τ = R f。")

# ============ appendix ============
heading("附录 · 方法与运行记录", 1)
para("复现脚本（review_work/ 目录）：independent_check.py（系数重算/实例/零位/符号判别）、"
     "grid_check.py（3,621 网格 + 200 非网格）、stencil_ident.py（模板重放/解耦反例/相位）、"
     "phase_mins.py（恒等式/连续最小值）、grad_zero.py（Richardson 梯度/预紧计数）、"
     "mech_route.py（静力学取矩路线）、sensitivity_tables.py（灵敏度表全量复核）。"
     "本 PDF 的图表由 pdf_figs.py（PIL 渲染）与 build_pdf.py（PyMuPDF 排版）生成。")
para("PDF 中公式为内嵌位图，审稿时以高分辨率裁剪 + 原生位图放大后的逐字形视觉转录获得印刷内容，"
     "并用数值真值反向裁定转录正确性（该流程曾在公式 (34)(35) 上自动纠正过一次误读）。"
     "两处印刷错误的判定经 3~4 次独立读取一致，置信度高；如需 100% 确证可核对作者源文档。"
     "不可核验项：原始 18,105 姿态日志（未随包，文档已声明；随包的 3,621 网格 + 25 条原始邻域记录已足以支撑结论）。")
para("文字版全文见 04_独立核对报告_2026-10-22.md；交互式图解版另存于会话可视化目录。")

total = len(doc)
for i in range(1, total):
    footer_title(doc[i])
    doc[i].insert_text((PAGE_W - MR - 18, PAGE_H - 30), "%d / %d" % (i + 1, total),
                       fontname="china-s", fontsize=8, color=GRAY)

doc.save(OUT, deflate=True)
print("PDF saved:", OUT, "pages:", len(doc))
