// ===== 绳驱二轴腕部解析模型 · 独立核对报告（图解完整版）=====
#let accent = rgb("#1F3A5F")
#let softline = rgb("#C9D2DD")
#let capgray = rgb("#5A6472")
#let footgray = rgb("#8A919C")
#let warn = rgb("#B23A2E")

#set page(paper: "a4", margin: (top: 2.3cm, x: 2.25cm, bottom: 2.2cm),
  footer: context {
    grid(columns: (1fr, auto), align: (left, right),
      text(size: 7.5pt, fill: footgray)[绳驱二轴腕部解析模型 · 独立核对报告],
      text(size: 7.5pt, fill: footgray)[#counter(page).display()\ /#counter(page).final().first()])
  })

#set text(font: ("DengXian", "Microsoft YaHei"), size: 10pt, lang: "zh", region: "cn")
#set par(justify: true, leading: 0.72em, spacing: 1.05em)
#set heading(numbering: "1.1")
#show heading: set block(above: 1.6em, below: 0.9em)
#show heading: set text(font: "Microsoft YaHei")
#show heading.where(level: 1): set text(size: 14pt, fill: accent)
#show heading.where(level: 2): set text(size: 11.5pt, fill: rgb("#24303F"))
#show heading.where(level: 3): set text(size: 10.5pt, fill: rgb("#24303F"))

#set math.equation(numbering: "(1)")
#show math.equation.where(block: true): set block(above: 1.1em, below: 1.1em)

#set figure(supplement: [图])
#set figure.caption(separator: [ · ])
#show figure.caption: set text(size: 8.2pt, fill: capgray)

#show raw: set text(font: "Consolas", size: 8.6pt)

#let callout(body, col: accent, bg: rgb("#EEF2F7")) = block(
  fill: bg, stroke: (left: 3pt + col), inset: (x: 12pt, y: 10pt),
  radius: 1.5pt, width: 100%, body)

#let btbl(..args, caption: none) = figure(
  supplement: [表],
  table(
    inset: (y: 5.5pt, x: 6pt), stroke: none,
    fill: (c, r) => if r > 0 and calc.even(r) { luma(247) },
    ..args),
  caption: caption)

// ================= 封面 =================
#v(3.2cm)
#align(center)[
  #text(size: 9.5pt, fill: capgray, tracking: 0.28em)[独 立 核 对 报 告]
  #v(0.5em)
  #text(size: 25pt, weight: "bold", fill: accent, font: "Microsoft YaHei")[绳驱二轴腕部解析模型]
  #v(0.35em)
  #text(size: 12.5pt, fill: rgb("#3E4A59"))[公式推导 · 数值核对 · 标定方案 · 误差边界 —— 图解完整版]
  #v(1.1em)
  #line(length: 42%, stroke: 1.2pt + accent)
]
#v(1.6em)
#align(center)[
  #text(size: 9pt, fill: capgray)[#set par(leading: 0.95em); 
    审稿对象：《绳驱二轴腕部解析模型 · 最终版》2026-10-22 / v2.0（C2/C3 P03、P04 修正点位）\
    审稿方法：独立向量几何实现（不复用作者代码）＋四条交叉验证路线\
    报告日期：2026-10-22　·　复现脚本：`review_work/` 目录 7 个脚本
  ]
]
#v(1.5em)
#callout()[
  #text(size: 12pt, weight: "bold", fill: accent, font: "Microsoft YaHei")[总体结论：有条件通过]
  #v(0.35em)
  理想模型（固定导向点中心折线）假设下，推导与数值*全部独立复现成立*；需修正公式 (27) 与 (S4) 两处印刷符号错误；实机精度尚未标定，不作任何数值承诺。
]
#v(1.2em)
*摘要*　主数学链（虚功符号、24 mm 偏置运动学、解耦定理、α/β/γ 展开、力臂闭式解、灵敏度与协方差传播）经闭式解、嵌套中心差分、0.2° 模板重放、静力学取矩四条互相独立的路线核验。六组系数、C2 实例、零位矩阵、3,621 网格姿态、25 条边界原始记录、连续最小值表与全部灵敏度表逐项与文档一致；唯一实质发现是两处印刷层符号错误；0.032668 mm 已被证明为差分模板截断误差，既非模型误差，亦非实机误差。

#pagebreak()

// ================= 1 机构 =================
= 机构与绳路：理解全文的钥匙

三条绳各按 P1→P8 八个标点走中心折线：P1–P4 在基座（静止），P5–P6 在 roll 件上，P7–P8 在手掌上。两条关节轴互相垂直但*不相交*——公垂线长 24 mm，即两轴偏置，推导中不可省略。整根绳只有两段跨关节：P4–P5 跨 roll 轴、P6–P7 跨 pitch 轴；其余五段两端同刚体、长度恒定（其和记为 $c_i$）。全部解析模型围绕这两个跨关节段建立。

#figure(image("figs2/schema.svg", width: 100%),
  caption: [零位 F0 系机构示意：三绳八点折线路径、两关节轴与 24 mm 偏置（红色虚线为公垂线）])

= 总体结论：有条件通过

在文档声明假设下（刚体、固定中心折线、无摩擦、同绳各段张力相等），主推导链数学成立且全部独立复现。条件是必须修正两处公式印刷符号错误：公式 (27) 的 sin 项符号、概览式 (S4) 的分数符号（见第 3 节）。两处均属“打印了错误代数式”——正文通式 (22)(23)、全部数值表与作者代码是对的，但读者直接引用这两条印刷式，在非零角度会得到错误力臂。文档对“CAD 内部一致性 ≠ 实机精度”的区分表述诚实且正确，本审稿在数值上证实了这一区分。

// ================= 3 问题表 =================
= 问题清单（按严重程度）

#btbl(
  table.hline(stroke: 1.1pt),
  table.header([*编号*], [*位置*], [*类别*], [*问题*], [*改正建议*]),
  table.hline(stroke: 0.5pt),
  [1], [公式 (27)], [数学必错（印刷）], [sin 项符号印错：印刷为 −647cosθ+1935sinθ，应为 −1935sinθ−647cosθ；θ=0 时两式巧合同值，掩盖错误], [分子改为 −(1935sinθ+647cosθ)],
  [2], [公式 (S4)], [数学必错（印刷）], [分数印成 +ds/dθ，与自身 r=−ds/dθ 及正文 (22)(23) 矛盾], [分子改为 βsinθ−γcosθ],
  [3], [复核包], [仅实现问题], [verify_formulas.py 与 复核结果.json 未随包，无法运行原脚本核对], [随包补上或注明获取方式],
  [4], [`geometry_model.py`], [仅实现可读性], [`length_arm()` 第二返回值是力臂 r 而非长度导数，命名易误读], [改名或加注释],
  [5], [第 8 节], [表述差异], [模板重放差文档记 1.53e−9 mm，本审稿用等价方法得 7.1e−12 mm，结论一致], [注明重放路径],
  table.hline(stroke: 1.1pt),
  caption: [全部遗留问题：2 处必改印刷错误、1 处包完整性、2 处实现/表述层面])

== 印刷错误 (27) 的数值裁定

文档将 C2 roll 段力臂印刷为 (−647cosθ+1935sinθ)/(2√D)，而通式 (23) 代入 β=−1935、γ=647 的正确结果应为 −1935sinθ−647cosθ。θ=0 时两式同为 −22.05 mm，该巧合同值掩盖了错误；但 CAD 网格在 roll=+17° 处给出 −26.78 mm，与正确式一致，印刷式在该处给出 ≈−1.2 mm。经 4 次独立图像判读（含原生位图逐字形）确认印刷内容。概览式 (S4) 为同样的镜像错误。

#figure(image("figs2/sign.svg", width: 100%),
  caption: [符号错误裁定：CAD 数据点全部落在正确曲线（橙实线）上；红色虚线（印刷式）只在 θ=0 与正确线相切])

// ================= 4 推导 =================
= 关键公式独立推导

== 虚功与 R 的符号、维度（对文档公式 (1)–(4)）

绳张力倾向缩短绳路，第 $i$ 根绳对机构做功 $-f_i "d" l_i$。令关节虚功相等，对任意虚位移成立：

$ tau^T "d" q = -f^T "d" l = -f^T J_l "d" q
  quad ==> quad tau = -J_l^T f, quad bold(R) = -((partial l)/(partial q))^T $

其中 $bold(R)$ 为 2×3 矩阵：行为 roll/pitch，列为 C1/C2/C3，$bold(tau) = bold(R) bold(f)$。长度对 rad 求导为 m/rad，SI 中弧度无量纲，数值上等同等效力臂 m。*独立验证*：用静力学取矩路线 $tau = a dot [(P_"动" - o) times (-f u)]$（仅跨关节段有贡献，其余段内力相消）与闭式解最大差 $1.4 times 10^(2)$² mm，零位矩阵逐位一致。

== 两轴运动学与 24 mm 偏置（对 (10)–(11)）

$ P_"roll" = Q_r p_0, quad P_"palm" = Q_r [Q_p p_0 + (I - Q_p) o_("p0")], quad o_("p0") = (0, 0, 24 "mm") $

palm 点先随 roll、再绕 roll 携带后的 pitch 轴（方向 $Q_r a_("p0")$，过点 $Q_r o_("p0")$）转动；24 mm 平移项显式保留。全网格数值一致证明该顺序正确。

== 解耦定理与反例（对 (12)–(14)）

$ P_6 - P_7 = Q_r [P_(06) - o_("p0") - Q_p (P_(07) - o_("p0"))] quad ==> quad norm(P_6 - P_7) "只依赖" theta_p $

$ l_i = c_i + s_("r i")(theta_r) + s_("p i")(theta_p) $

这是当前绳路归属（P1–P4 在 base、P5–P6 在 roll_link、P7–P8 在 palm、无 base 直连 palm 段）的结构性质。*反例（已数值实现）*：增加一段 base P03→palm P08 直连后，混合偏导从 0 变为 C2=+1.37、C3=−1.24 mm/rad²，两角耦合出现，单变量分解失效。

#figure(image("figs2/decouple.svg", width: 100%),
  caption: [解耦与反例（对数轴）：当前绳路混合偏导解析恒为 0；加 base→palm 直连段后耦合立即出现])

== α/β/γ 几何展开（对 (15)–(21)）

$ s^2 = norm(u - Q v)^2 = alpha + beta cos theta + gamma sin theta, quad u = A - o, v = B_0 - o $

$ alpha = norm(u)^2 + norm(v)^2 - 2 (u dot a)(v dot a), quad beta = -2[u dot v - (u dot a)(v dot a)], quad gamma = -2 u dot (a times v) $

三系数单位均为长度²。轴上原点沿 $a$ 平移时 $u_⊥, v_⊥, u_∥ - v_∥$ 与 $u dot (a times v)$ 均不变，故三系数不变（规范自由度）。$alpha >= rho = sqrt(beta^2 + gamma^2) = 2 norm(u_⊥) norm(v_⊥)$ 由 AM–GM 保证；六段实际裕量 14.8～215.9 mm²，无零长奇异。六组系数从 24 点坐标独立重算与参数 JSON 全等。

== 力臂导数（对 (22)–(25)）

$ (d s)/(d theta) = (-beta sin theta + gamma cos theta)/(2 sqrt D), quad r = -(d s)/(d theta) = (beta sin theta - gamma cos theta)/(2 sqrt D) $

C2 roll 段 θ=0：$r = -647/(2 sqrt(215.25)) = -22.04970101 "mm"$，与文档一致。注意文档概览式 (S4) 与代入示例 (27) 的印刷符号与此处正确式相反。

== 灵敏度、协方差与相位耦合（对 (31)–(38)、C4）

令 $N = beta sin theta - gamma cos theta$：

$ (partial r)/(partial alpha) = -N/(4 D^(3\/2)), quad (partial r)/(partial beta) = (sin theta)/(2 sqrt D) - (N cos theta)/(4 D^(3\/2)), quad (partial r)/(partial gamma) = -(cos theta)/(2 sqrt D) - (N sin theta)/(4 D^(3\/2)) $

$ "Cov"(vec bold(R)) approx J_z Sigma_z J_z^T, quad abs(Delta tau_j) <= sum_i abs(Delta R_("j i")) abs(f_i) $

三式与有限差分吻合到 8~9 位有效数字。相位耦合：

$ D(q + delta; beta, gamma) = D(q; beta', gamma'), quad beta' = beta cos delta + gamma sin delta, quad gamma' = gamma cos delta - beta sin delta $

（数值残差 $5.4 times 10^(3)$ m²，机器零）。⇒ 无外部基准时零偏 δ 与 β/γ 不可分离；每关节 10 个名义参数 −1 相位规范 = 9 个有效参数；仅测 Δl 时 $c_i$ 不可辨识。

#figure(image("figs2/phase.svg", width: 100%),
  caption: [相位耦合：真实参数（蓝实线）与吸收 δ 后的等效参数（绿虚线）给出完全相同的观测量])

// ================= 5 数值核对 =================
= 数值核对结果

*环境*：Windows 10 (22621) x64，Python 3.12.10，数值计算仅标准库；PDF 解包用 PyMuPDF（不参与数值）。*独立实现*：Rodrigues 主动旋转＋父子刚体链＋24 mm 偏置；嵌套中心差分 h=$10^(-1)$ rad；三点 Lagrange 模板重放；静力学取矩；空间梯度中心差分 h=$10^(-1)$ m＋Richardson。*verify_formulas.py 与 复核结果.json 未随包*（已搜索工作区、zip、PDF 附件），故未运行原作者脚本，全部结论出自独立实现。

#btbl(
  table.hline(stroke: 1.1pt),
  table.header([*核对项目*], [*文档值*], [*独立复现*], [*判定*]),
  table.hline(stroke: 0.5pt),
  [六组 α/β/γ 从 24 点重算], [—], [6 组全等（至 $10^(-1)$ mm²）], [通过],
  [C2 roll 实例 $R_("r2")(0)$], [−22.04970101 mm], [完全相同], [通过],
  [解析零位矩阵（6 元素）], [见文档表], [逐位相同（三条路线一致）], [通过],
  [3,621 姿态长度 L1–L3], [—], [最大差 $2.7 times 10^(3)$ mm], [通过],
  [R 最大差 roll/C1·C2·C3], [2.47e−5 / 9.65e−4 / 6.34e−4 mm], [逐项相同], [通过],
  [R 最大差 pitch/C1·C2·C3], [3.267e−2 / 1.48e−4 / 1.11e−4 mm], [逐项相同（最差分量 pitch/C1）], [通过],
  [RMSE 六分量], [见文档], [逐项相同], [通过],
  [200 非网格姿态（闭式对差分）], [6.63e−8 mm], [2.5e−8 mm（同级别）], [通过],
  [25 条边界原始记录 CAD 长度], [≈0], [2.65e−11 mm], [通过],
  [0.2° 模板重放（CAD 长度对原表）], [0 / 1.53e−9 mm], [7.1e−12 mm（结论一致更紧）], [通过],
  [连续最小 s 表（6 段）], [见文档], [全同（含最小值角度）], [通过],
  [+1 mm 单点扰动表（12 项）], [见文档], [逐项相同], [通过],
  [零位梯度范数表（12 项）], [见文档], [逐项相同], [通过],
  table.hline(stroke: 1.1pt),
  caption: [数值核对（一）：系数、实例与全网格残差])

#btbl(
  table.hline(stroke: 1.1pt),
  table.header([*核对项目*], [*文档值*], [*独立复现*], [*判定*]),
  table.hline(stroke: 0.5pt),
  [轴原点 $(partial R)/(partial o_Y)$（pitch 行）], [0.982605 / 0.999355 / 0.930400], [完全相同；roll 行 = 0], [通过],
  [24 mm 偏置两种约定], [见文档], [约定一全同；约定二至 $3 times 10^(2)$ 相对差], [通过],
  [P06 三口径灵敏度], [16.064268 / 15.185639 / 15.745867], [精确同 / 15.185638 / 15.7431], [通过],
  [−25° 一阶预算示例], [1.5246 mm], [1.5246 mm], [通过],
  [全正预紧方向不满足数], [1664 / 3621], [3621 − 1957 = 1664], [通过],
  [rank2 全正预紧外统计], [全 True], [3621 / 3621], [通过],
  [框架变换（$E^T$ 正确 / 误转置）], [残差 0；≈183.85 mm], [$6.9 times 10^(3)$ m；183.8478 mm], [通过],
  [PDF 附件 JSON 与 zip JSON], [一致], [points / cables 全同], [通过],
  [差分模板截断系数], [中心 h²/6、单侧 h²/3], [代数推导一致], [通过],
  table.hline(stroke: 1.1pt),
  caption: [数值核对（二）：灵敏度表、预紧计数与框架变换])

#figure(image("figs2/grid.svg", width: 100%),
  caption: [3,621 姿态全网格残差（对数轴）：条柱为独立复现最大差，横线为文档声称值，二者重合])

== 0.0327 mm 之谜：三种误差的区分

解析导数与 CAD 0.2° 差分表的最大差为 0.032668 mm（pitch/C1 分量，位于 (4°, −25°)）。将同一三点模板*直接作用于 CAD 原始长度*再与原表比较，最大差仅 $7.1 times 10^(2)$² mm——证明 CAD 的 R 表本身就是该模板差分所得，0.0327 mm 全部来自模板对真导数的截断（内部中心模板 h²/6、边界单侧模板 h²/3），不是模型失配，更不是实机误差。

#figure(image("figs2/stencil.svg", width: 100%),
  caption: [上：解析导数与 0.2° 差分几乎重合；下：两者之差随 pitch 角变化，峰值 0.032668 mm 恰在 −25° 边界（单侧模板）])

== 短段风险与误差预算（对文档 C1/C3 节）

六段绳长在连续角范围内的最小值全部复现（含最小值所在角度）。C1/pitch 段在 −25° 仅 *3.90 mm*，是全机构最短的段；其余五段均大于 10.4 mm。零位单点灵敏度表 12 项逐项复现：P04 最敏感（C3 达 2.20 mm/mm），P07 最迟钝（0.18 mm/mm）。在 −25° 处 C1/pitch 对 P06 的位置梯度范数达 15.7 mm/mm：0.05 mm 点位误差的一阶预算约 1.52 mm 力臂误差（文档示例 1.5246 mm 精确复现）。结论：pitch ≤ −24° 为低置信区，须单独标定验收，不能被全局平均掩盖。

#figure(image("figs2/smin.svg", width: 100%),
  caption: [六段绳长曲线与连续最小值：C1/pitch 在 −25° 仅 3.90 mm（红点，高危区）])

#figure(image("figs2/grad.svg", width: 100%),
  caption: [零位单点灵敏度（位置梯度范数，mm/mm）：P04–P07 × C1–C3])

// ================= 6 标定 =================
= 实机标定方案与可辨识性风险

+ *先定规范*：机械检具确定两关节机械零位与正方向（外部固定 δ），绝不与几何系数同时自由拟合；固定全局坐标系。
+ *独立标定收放测量链*：编码器→收放长度换算（卷绕半径、绕层）、空载往返回差，先于几何标定。
+ *单轴扫掠*（利用解耦结构）：固定 roll 扫 pitch、固定 pitch 扫 roll；静置采样；低/中/高三种预紧各一次往返。
+ *组合姿态*验证实机解耦（$R_r$ 不随 $theta_p$ 漂移等）；数据分标定集与独立验证集。
+ *识别顺序*：先六组 α/β/γ（＋c 若测绝对长度），约束 D>0 与 α≥ρ；报告验证集 Δl 的 RMSE、95% 分位数与最大差。
+ *摩擦/弹性分离*：不同预紧下 Δl(q) 曲线族分离度对应弹性；往返迟滞环宽对应摩擦回差；不得混入几何长度。
+ *风险*：δ 与 β/γ 相位耦合（无外部基准每关节必损失 1 维）；仅 Δl 时 $c_i$ 不可辨识；参数雅可比须查秩与条件数；C1 pitch ≤ −24° 短段区单独标定；1,664/3,621 姿态无全正预紧方向（满秩 ≠ 可实现任意力矩）；轴线现仅由三 CAD 姿态恢复，需实测确认。

#figure(image("figs2/preload.svg", width: 78%),
  caption: [预紧可行性地图：红色区域（1,664/3,621 姿态）不存在全正内部预紧方向，集中于大 pitch 角区与两侧大 roll 角区])

= 误差承诺边界

#callout(col: rgb("#2E7D4F"), bg: rgb("#EDF5F0"))[
  *能承诺（理想模型内）*　固定中心折线假设下推导与实现的数学正确性（多路线独立验证）；单位与符号约定自洽；CAD 体系内部一致性（长度残差机器级 $2.7 times 10^(3)$ mm；R 差上限 0.032668 mm 已证明为差分截断）。
]
#v(0.5em)
#callout(col: warn, bg: rgb("#FBF0EE"))[
  *不能承诺*　真机力臂误差的任何数值（“≤0.0327 mm”“≤0.1 mm”均不成立）；中心折线与真实瓷环滑动接触的偏差；摩擦、弹性、回差的影响量；轴线与 24 mm 偏距的实物准确性（尚无实测）；加工装配偏差下的力矩精度；张力可行域内的承载能力。
]

= 需要补充的测量数据

+ 两轴方向、位置与 24 mm 最短偏距的实测（三坐标 / 激光跟踪 / 检具），注明装配基准。
+ 跨刚体段端点关键尺寸：至少 C1 的 P06、P07 及各 P04、P05 位置（零位最敏感点 P04：1.35～2.20 mm/mm）。
+ 机械零位基准的实物定义与 δ 标定记录。
+ 电机收放链标定数据：卷绕半径 / 层数换算、空载回差、重复性。
+ 单轴扫掠 Δl(q) 数据集：角度、预紧水平、运动方向、重复次数、张力（若有）。
+ C1 pitch 负角区（≤ −24°）专门数据。
+ （建议）关节力矩与绳张力同步测量，用于最终验证 $tau = bold(R) bold(f)$。

= 附录：方法与运行记录

*复现脚本*（`review_work/` 目录）：`independent_check.py`（系数重算 / 实例 / 零位 / 符号判别）、`grid_check.py`（3,621 网格＋200 非网格）、`stencil_ident.py`（模板重放 / 解耦反例 / 相位）、`phase_mins.py`（恒等式 / 连续最小值）、`grad_zero.py`（Richardson 梯度 / 预紧计数）、`mech_route.py`（静力学取矩路线）、`sensitivity_tables.py`（灵敏度表全量复核）。本 PDF 的图表由 `figs2.py`（matplotlib 矢量渲染）与 `report.typ`（Typst 排版）生成。

原 PDF 中公式为内嵌位图，审稿时以高分辨率裁剪＋原生位图放大后的逐字形视觉转录获得印刷内容，并用数值真值反向裁定转录正确性（该流程曾在公式 (34)(35) 上自动纠正过一次误读）。两处印刷错误的判定经 3～4 次独立读取一致，置信度高；如需百分之百确证可核对作者源文档。*不可核验项*：原始 18,105 姿态日志（未随包，文档已声明；随包的 3,621 网格＋25 条原始邻域记录已足以支撑结论）。文字版全文见 `04_独立核对报告_2026-10-22.md`。
