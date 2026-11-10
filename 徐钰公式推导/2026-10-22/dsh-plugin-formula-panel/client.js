window.__ModuleLoader__.load({
  id: '@local/formula-panel',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const PANEL_KEY = 'formula-panel';
    const PANEL_3D = 'formula-3d';

    const TEXT = {
      en: {
        nav: 'Formula Reference',
        eyebrow: 'Rope-driven two-axis wrist',
        title: 'Formula Reference',
        subtitle: 'Two joint angles in, six signed lever arms out. Click a card to copy it.',
        search: 'Search symbol, meaning, or formula number…',
        groupsLabel: 'Groups',
        all: 'All',
        empty: 'Nothing matches this filter.',
        emptyHint: 'Try a symbol, a meaning, or a number such as 23.',
        reset: 'Clear filter',
        copied: 'Copied',
        copyFailed: 'Copy failed — select the text manually',
        count: (n) => String(n),
        countSuffix: 'entries',
        entries: 'entries',
        shortcut: 'to search',
        tabReference: 'Reference',
        tabScene: '3D model',
        tabGuide: 'Walkthrough',
      },
      zh: {
        nav: '公式速查',
        eyebrow: '绳驱二轴腕部 · 解析式 v2.0',
        title: '公式速查',
        subtitle: '输入两个关节角，得到六个带符号力臂；点卡片即复制。',
        search: '搜索符号、含义或式号（如 23、E1）…',
        groupsLabel: '分组',
        all: '全部',
        empty: '没有匹配的条目。',
        emptyHint: '试试符号、含义，或者式号 23。',
        reset: '清除筛选',
        copied: '已复制',
        copyFailed: '复制失败，请手动选中文本',
        count: (n) => String(n),
        countSuffix: '条',
        entries: '条',
        shortcut: '聚焦搜索',
        tabReference: '速查',
        tabScene: '3D 模型',
        tabGuide: '完整图解',
      },
    };

    const GROUPS = [
      {
        id: 'core',
        title: { en: 'Core relations', zh: '核心关系' },
        entries: [
          {
            no: '(3)',
            sym: 'τ = R f',
            name: '总纲：关节力矩 = 力臂矩阵 × 张力',
            f: 'τ_{j} = Σ_{i} R_{ji} f_{i}；R 为 2×3：行 = roll / pitch，列 = C1–C3',
            copy: '(3) τ = R·f，即 τ_j = Σ_i R_ji·f_i（R 为 2×3：行 roll/pitch，列 C1–C3）',
          },
          {
            no: '(4)',
            sym: 'R = -(∂l/∂q)^{T}',
            name: '力臂矩阵 = 绳长雅可比的负转置',
            f: 'J_{l} = ∂l/∂q（3×2）；R_{ji} = -∂l_{i}/∂θ_{j}',
            copy: '(4) R = -(∂l/∂q)^T，R_ji = -∂l_i/∂θ_j',
          },
          {
            no: '(2)',
            sym: 'δW = -Σ_{i} f_{i} dl_{i} = τ^{T} dq',
            name: '虚功平衡：张力做功 = 关节力矩做功',
            f: '对任意微小虚位移 dq 都成立，因此才有 (3)(4)',
            copy: '(2) 虚功平衡：-Σ_i f_i·dl_i = τ^T·dq（对任意 dq 成立）',
          },
          {
            sym: 'R_{ji} 是带符号的',
            name: '正转使绳变长 ⇒ R 为负 ⇒ 张力阻碍正转',
            f: 'R 是轴向力矩系数，不是“绳到轴的距离”那种正数',
            copy: '符号约定：关节正转使绳变长 ⇒ ∂l/∂θ > 0 ⇒ R < 0 ⇒ 张力阻碍正转',
          },
          {
            no: '(14)',
            sym: 'l_{i} = c_{i} + s_{ri}(θ_{r}) + s_{pi}(θ_{p})',
            name: '一根绳的总长 = 常数段 + roll 段 + pitch 段',
            f: '五段同刚体 ⇒ 长度恒定，合并为 c_{i}；只有 P4–P5、P6–P7 会变',
            copy: '(14) l_i(θ_r,θ_p) = c_i + s_ri(θ_r) + s_pi(θ_p)',
          },
          {
            sym: 'dc_{i}/dθ = 0',
            name: '算力臂不需要 c_{i}',
            f: '只有要输出 P1–P8 绝对绳长时才需要常数段 c_{i}',
            copy: 'c_i 的导数为 0：算几何力臂不需要 c_i，只有算绝对绳长才要',
          },
          {
            no: '(25)',
            sym: '∂R_{ri}/∂θ_{p} = ∂R_{pi}/∂θ_{r} = 0',
            name: '交叉偏导为零：两个关节解耦',
            f: '解耦是当前绳路拓扑的推论，不是拟合；拓扑变了要退回第 3 节通用式',
            copy: '(25) ∂R_ri/∂θ_p = ∂R_pi/∂θ_r = 0（两轴解耦）',
          },
          {
            sym: 'f = R^{+}τ + t w',
            name: '张力分配：最小范数解 + 零空间内张力',
            f: 'R^{+} 为伪逆；t 为内张力标量，w 为零空间基；满秩不等于存在全正张力解',
            copy: 'f = R^+·τ + t·w（R^+ 为伪逆，t 为内张力标量，w 为零空间基）',
          },
          {
            no: '(38)',
            sym: '|Δτ_{j}| ≤ Σ_{i} |ΔR_{ji}|·|f_{i}|',
            name: '力矩误差界（几何误差已知、张力已知时）',
            f: '量纲示例：某元素误差 0.1 mm、张力 10 N ⇒ 0.001 N·m；这不是实测精度承诺',
            copy: '(38) |Δτ_j| ≤ Σ_i |ΔR_ji|·|f_i|（0.1 mm × 10 N ⇒ 0.001 N·m）',
          },
        ],
      },
      {
        id: 'segment',
        title: { en: 'Segment closed form', zh: '单段闭式' },
        entries: [
          {
            no: '(15)',
            sym: 'u = A - o,  v = B_{0} - o',
            name: '两个位矢（本节的 u 不是单位向量）',
            f: 'A = 跨关节段固定端；B_{0} = 运动端零位；o = 轴上任一点',
            copy: '(15) u = A - o，v = B_0 - o（位矢，长度单位）',
          },
          {
            no: '(16)',
            sym: 'h_{1} = u·a,  u_{⊥} = u - h_{1}a',
            name: '拆沿轴 / 垂直分量（v 同理）',
            f: 'a = 轴方向单位向量；只有垂直分量决定绳长怎么变',
            copy: '(16) h_1 = u·a，u⊥ = u - h_1·a；h_2 = v·a，v⊥ = v - h_2·a',
          },
          {
            sym: 'a, b, h',
            name: '三个不变量',
            f: 'a = ‖u_{⊥}‖，b = ‖v_{⊥}‖，h = h_{2} - h_{1}（带符号）',
            copy: 'a = ‖u⊥‖，b = ‖v⊥‖，h = h_2 - h_1',
          },
          {
            no: '(17)',
            sym: 'Rot(θ)v_{⊥} = v_{⊥}cosθ + (a×v_{⊥})sinθ',
            name: 'Rodrigues 展开（垂直平面内）',
            f: 'B(θ) = o + h_{2}a + Rot(θ)v_{⊥}',
            copy: '(17) Rot(θ)v⊥ = v⊥·cosθ + (a×v⊥)·sinθ；B(θ) = o + h_2·a + Rot(θ)v⊥',
          },
          {
            no: '(18)',
            sym: 's = √D,  D = α + βcosθ + γsinθ',
            name: '单段绳长闭式（整篇的发动机）',
            f: 'D 与 α/β/γ 的单位都是长度²（文档 mm²，源码 m²）',
            copy: '(18) s = √D = √(α + β·cosθ + γ·sinθ)',
          },
          {
            no: '(19)',
            sym: 'α = ‖u‖^{2} + ‖v‖^{2} - 2(a·u)(a·v)',
            name: '常数项（与 θ 无关）',
            f: '等价于 ‖u_{⊥}‖² + ‖v_{⊥}‖² + (h_{1}-h_{2})²，一定 ≥ 0',
            copy: '(19) α = ‖u‖² + ‖v‖² - 2(a·u)(a·v)（mm²）',
          },
          {
            no: '(20)',
            sym: 'β = -2[u·v - (a·u)(a·v)]',
            name: 'cos 项系数',
            f: '也写成 β = -2(v_{⊥}·u_{⊥})',
            copy: '(20) β = -2[u·v - (a·u)(a·v)] = -2(v⊥·u⊥)（mm²）',
          },
          {
            no: '(21)',
            sym: 'γ = -2 u·(a×v)',
            name: 'sin 项系数（不是角度！）',
            f: '叉乘是垂直平面内的有向面积，它决定相位',
            copy: '(21) γ = -2·u·(a×v)（mm²，不是角）',
          },
          {
            no: '(22)',
            sym: 'ds/dθ = (-βsinθ + γcosθ)/(2√D)',
            name: '段长对关节角的导数',
            f: '与 (23) 只差一个负号，别背反',
            copy: '(22) ds/dθ = (-β·sinθ + γ·cosθ)/(2√D)',
          },
          {
            no: '(23)',
            sym: 'r(θ) = (βsinθ - γcosθ)/(2√D)',
            name: '带符号力臂（通式，引用以它为准）',
            f: 'r = -ds/dθ；单位 mm/rad，数值按 mm 当等效力臂用',
            copy: '(23) r(θ) = (β·sinθ - γ·cosθ)/(2√(α + β·cosθ + γ·sinθ))',
          },
          {
            sym: 'r(θ) = ρ sin(θ-φ_{0})/(2s)',
            name: '力臂的余弦波写法（更好懂）',
            f: 'θ = φ_{0}（绳最长处）时 r = 0；分母有 2s，绳越长力臂越小',
            copy: 'r(θ) = ρ·sin(θ - φ_0)/(2s)',
          },
          {
            sym: 'r(0) = -γ/(2√(α+β))',
            name: '零位力臂，只依赖三个常数',
            f: 'C2 roll：-647/(2√215.25) = -22.0497 mm',
            copy: 'r(0) = -γ / (2√(α + β))',
          },
          {
            sym: 'ρ = √(β^{2}+γ^{2}) = 2‖u_{⊥}‖‖v_{⊥}‖',
            name: '摆幅参数：长度平方的摆动幅度',
            f: '因此物理几何保证 α ≥ ρ',
            copy: 'ρ = √(β² + γ²) = 2‖u⊥‖·‖v⊥‖',
          },
          {
            sym: 'D = α + ρcos(θ-φ_{0})',
            name: '相位角写法',
            f: 'φ_{0} = atan2(γ, β)，即零位时两个垂直分量的夹角',
            copy: 'D = α + ρ·cos(θ - φ_0)，φ_0 = atan2(γ, β)',
          },
          {
            sym: 'D_{min} = α - ρ',
            name: '闭式最小值（拿来自检）',
            f: '出现在 θ = φ_{0} ± 180°；C2 roll 为 109.95 mm²，在 -18.49°',
            copy: 'D_min = α - ρ，出现在 θ = φ_0 ± 180°',
          },
          {
            sym: 'N = βsinθ - γcosθ',
            name: '求导中间量（分子）',
            f: 'r = N/(2√D)；N 在公式里叫“分子”比“力臂”更准确',
            copy: 'N = β·sinθ - γ·cosθ，r = N/(2√D)',
          },
        ],
      },
      {
        id: 'geometry',
        title: { en: 'Geometry & invariants', zh: '几何与不变量' },
        entries: [
          {
            no: '(10)(11)',
            sym: 'o_{r}=(0,0,0),  a_{r}=(0,1,0)',
            name: '零位固定系 F0 与 roll 轴',
            f: '+X 沿零位 pitch 正轴、+Y 沿 roll 正轴、+Z = X×Y',
            copy: '(10)(11) F0：roll 轴 o_r=(0,0,0)、a_r=(0,1,0)；pitch 轴 o_p=(0,0,24 mm)、a_p=(1,0,0)',
          },
          {
            sym: '24 mm',
            name: '两轴正交但不相交',
            f: 'pitch 轴抬高 24 mm；把轴心当原点会让力臂差 24 mm 量级',
            copy: '两轴正交但不相交，最短间距 24 mm（pitch 轴过 (0,0,24)）',
          },
          {
            no: '(F1)',
            sym: 'p_{model} = B^{T}(p_{world} - o_{W})',
            name: 'CAD 世界系 → F0 的变换',
            f: 'B 的三列是 F0 的 X/Y/Z 轴在世界系中的基向量；o_{W} ≈ (0, 210, 32.452121734611) mm',
            copy: '(F1) p_model = B^T·(p_world - o_W)，o_W ≈ (0,210,32.452121734611) mm',
          },
          {
            sym: 'B^{T} 用错差 183.85 mm',
            name: '最容易踩的坐标坑',
            f: 'JSON 里 B 按行存数组，但代表按列放基向量；不转置最大欧式误差约 183.85 mm',
            copy: '坑：B 在 JSON 里按行存，但代表按列放基向量；用错（不转置）最大差 183.85 mm',
          },
          {
            no: '(12)(13)',
            sym: '7 段 = 5 段恒定 + 2 段跨刚体',
            name: '一根绳 8 个点、7 段，只有两段会变长',
            f: 'P1–P2、P2–P3、P3–P4、P5–P6、P7–P8 恒定（和 = c_{i}）；只有 P4–P5、P6–P7 跨刚体',
            copy: '(12)(13) 每根绳 7 段：5 段同刚体长度恒定（和 = c_i），只有 P4–P5、P6–P7 变化',
          },
          {
            sym: 'u_{⊥}, v_{⊥}',
            name: '只有垂直分量影响绳长',
            f: 'u_{⊥} = u - (u·a)a，v_{⊥} = v - (v·a)a；沿轴分量旋转时完全不变',
            copy: 'u⊥ = u - (u·a)·a，v⊥ = v - (v·a)·a（只有垂直分量影响绳长）',
          },
          {
            sym: 'α = ‖u_{⊥}‖^{2} + ‖v_{⊥}‖^{2} + (h_{1}-h_{2})^{2}',
            name: 'α 的恒等式（一定 ≥ 0）',
            f: '与 (19) 等价，适合心算检查，也解释了 α ≥ ρ 的来源',
            copy: 'α = ‖u⊥‖² + ‖v⊥‖² + (h_1 - h_2)² ≥ 0',
          },
          {
            sym: '解耦的来源',
            name: '为什么能拆成两个单变量函数',
            f: 'P4–P5 不受 pitch 驱动 ⇒ 只依赖 roll；P6–P7 的共同 roll 运动被范数消去 ⇒ 只依赖 pitch',
            copy: '解耦来源：P4–P5 只随 roll、P6–P7 只随 pitch；若新增 base→palm 直连段则失效',
          },
        ],
      },
      {
        id: 'params',
        title: { en: 'Six segment constants', zh: '六段参数' },
        entries: [
          {
            sym: 'C1 / roll',
            name: 'α / β / γ（mm²）',
            f: 'α = 364.5，β = -182.5，γ = 7.0',
            copy: 'C1/roll：α = 364.5，β = -182.5，γ = 7.0（mm²）',
          },
          {
            sym: 'C1 / pitch',
            name: 'α / β / γ（mm²）',
            f: 'α = 7263.47364742，β = -6537.66603142，γ = 3130.77161942',
            copy: 'C1/pitch：α = 7263.47364742，β = -6537.66603142，γ = 3130.77161942（mm²）',
          },
          {
            sym: 'C2 / roll',
            name: 'α / β / γ（mm²）· PDF 第 7 节官方算例',
            f: 'α = 2150.25，β = -1935.0，γ = 647.0',
            copy: 'C2/roll：α = 2150.25，β = -1935.0，γ = 647.0（mm²）',
          },
          {
            sym: 'C2 / pitch',
            name: 'α / β / γ（mm²）',
            f: 'α = 820.33042151，β = -563.99999989，γ = -378.00000006',
            copy: 'C2/pitch：α = 820.33042151，β = -563.99999989，γ = -378.00000006（mm²）',
          },
          {
            sym: 'C3 / roll',
            name: 'α / β / γ（mm²）',
            f: 'α = 2500.25，β = -2205.0，γ = -597.0',
            copy: 'C3/roll：α = 2500.25，β = -2205.0，γ = -597.0（mm²）',
          },
          {
            sym: 'C3 / pitch',
            name: 'α / β / γ（mm²）',
            f: 'α = 859.73346622，β = -563.99999980，γ = -378.00000010',
            copy: 'C3/pitch：α = 859.73346622，β = -563.99999980，γ = -378.00000010（mm²）',
          },
          {
            sym: 'c_{1}, c_{2}, c_{3}',
            name: '五段常数长度之和（mm）',
            f: 'c_{1} = 80.6754857664，c_{2} = 61.2596374567，c_{3} = 61.2596374615',
            copy: 'c1 = 80.6754857664 mm，c2 = 61.2596374567 mm，c3 = 61.2596374615 mm',
          },
          {
            sym: '单位',
            name: '文档 mm² / mm，源码 m² / m',
            f: '同一式子里不要混用；1 m = 1000 mm，系数差 10⁶',
            copy: '单位：文档表格用 mm²/mm，源码与 JSON 用 m²/m；1 m = 1000 mm，系数差 10^6',
          },
        ],
      },
      {
        id: 'calibration',
        title: { en: 'Zero position', zh: '零位标定' },
        entries: [
          {
            sym: 'R(0) roll 行',
            name: '零位力臂（mm/rad）',
            f: 'C1 -0.25943726，C2 -22.04970101，C3 17.37198247',
            copy: 'R(0) roll 行：[C1] -0.25943726，[C2] -22.04970101，[C3] 17.37198247 mm',
          },
          {
            sym: 'R(0) pitch 行',
            name: '零位力臂（mm/rad）',
            f: 'C1 -58.10461556，C2 11.80488412，C3 10.99035112',
            copy: 'R(0) pitch 行：[C1] -58.10461556，[C2] 11.80488412，[C3] 10.99035112 mm',
          },
          {
            sym: 'Δ',
            name: '三个半径的有向夹角',
            f: 'C1 +2.20°，C2 +18.49°，C3 -15.14°；正负由 sinΔ = γ/(2ab) 决定',
            copy: 'Δ：C1 +2.20°，C2 +18.49°，C3 -15.14°（sinΔ = γ/(2ab) 决定正负）',
          },
          {
            sym: 'C2 代入',
            name: 'PDF 第 7 节官方算例（roll 段）',
            f: 'A=P04≈(-27,-16,5)，B₀=P05≈(-32.5,-12,18)，o=(0,0,0)，a=(0,1,0) ⇒ α=2150.25，β=-1935，γ=647',
            copy: 'C2 roll 代入：A=P04≈(-27,-16,5)，B0=P05≈(-32.5,-12,18)，o=(0,0,0)，a=(0,1,0) ⇒ α=2150.25，β=-1935，γ=647',
          },
          {
            no: '(26)',
            sym: 's_{r2}(θ) = √(2150.25 - 1935cosθ + 647sinθ)',
            name: 'C2 roll 绳长的数值式',
            f: 'D(0) = 215.25 mm²，s(0) = 14.6714 mm',
            copy: '(26) C2 roll：s = √(2150.25 - 1935·cosθ + 647·sinθ) mm；D(0)=215.25，s(0)=14.6714',
          },
          {
            no: '(27)',
            sym: 'R_{r2}(0) = -647/(2×14.671)',
            name: 'C2 roll 零位力臂',
            f: '= -22.0497 mm；负号表示拉紧 C2 给 roll 负向力矩（每 1 N ≈ 22 mN·m）',
            copy: '(27) C2 roll：R_r2(0) = -647/(2×14.671) = -22.0497 mm',
          },
          {
            sym: '30° 验证点',
            name: 'C2 roll 的独立数值校验',
            f: 'θ=30° ⇒ s = 28.249 mm，r = -27.04 mm（与 0.2° 差分一致到 0.2%）',
            copy: 'C2 roll θ=30°：s = 28.249 mm，r = -27.04 mm',
          },
          {
            sym: 'C2 最短段',
            name: 'D 的最小值就在零位附近',
            f: 'D_{min}=109.95 mm² 在 θ = -18.49°，对应 s = 10.486 mm；零位只比最短长约 4.2 mm',
            copy: 'C2 roll：D_min = 109.95 mm² 在 θ = -18.49°，对应 s_min = 10.486 mm（零位只长 4.2 mm）',
          },
        ],
      },
      {
        id: 'algorithm',
        title: { en: 'Per-segment algorithm', zh: '每段算法' },
        entries: [
          {
            sym: 'd_{1}, d_{2}',
            name: '单段实时计算的核心两行',
            f: 'd_{1} = v_{1}cosθ - v_{2}sinθ - u_{1}；d_{2} = v_{1}sinθ + v_{2}cosθ - u_{2}',
            copy: 'd1 = v1·cosθ - v2·sinθ - u1；d2 = v1·sinθ + v2·cosθ - u2',
          },
          {
            sym: 's, r',
            name: '由 d1、d2、h 直接得到段长与力臂',
            f: 's = √(d_{1}² + d_{2}² + h²)；r = (u_{2}d_{1} - u_{1}d_{2})/s',
            copy: 's = √(d1² + d2² + h²)；r = (u2·d1 - u1·d2)/s',
          },
          {
            sym: '5 个常数',
            name: '每段只需预存 5 个数',
            f: 'u_{1}, u_{2}, v_{1}, v_{2}, h（等价于 a, b, h, α, β, γ 的一套）',
            copy: '每段预计算常数：u1, u2, v1, v2, h',
          },
          {
            sym: '6 次调用',
            name: '3 根绳 × 2 段 → R 的 6 个元素',
            f: '每根绳 roll 段用 roll 角、pitch 段用 pitch 角，互不耦合',
            copy: '3 根绳 × 2 段 = 6 次单段调用，得到 R 的 6 个元素',
          },
          {
            sym: '单段代价',
            name: '实时计算量',
            f: '2 次 sin/cos + 4 次乘 + 1 次开方；9,249 个姿态里 float32 与 double 最大差 4.67×10⁻⁵ mm',
            copy: '单段：2 次 sin/cos + 4 次乘 + 1 次开方；float32 与 double 最大差 4.67e-5 mm',
          },
          {
            sym: '在线流程',
            name: '从编码器读数到 R 的六步',
            f: '度数→rad、统一正方向与零偏 δ、算六次显式函数、组装 2×3、按需换算 m、越界/退化时报无效状态',
            copy: '在线：deg→rad → 统一正方向与零偏 → 六次显式函数 → 组装 2×3 → 换算 SI → 越界/退化报无效',
          },
        ],
      },
      {
        id: 'limits',
        title: { en: 'Gates & error budget', zh: '门限与误差' },
        entries: [
          {
            no: '(E1)',
            sym: 's_{guard} ≥ max(s_{num}, 2ε_{d}/η_{max})',
            name: '工程段长门限（设计起点，不是安全认证）',
            f: 'ε_{d} 是段差向量不确定度界，η_{max} 是允许的相对方向误差；每段可单独配置',
            copy: '(E1) s_guard ≥ max(s_num, 2·ε_d/η_max)',
          },
          {
            sym: '三级判定',
            name: '数学可算 / 控制可用 / 实际可承载 要分开',
            f: '① D>0 且 s>s_{num}　② s≥s_{guard} 与力臂误差预算　③ 张力上下限与负载；通过前一级不代表后一级',
            copy: '三级判定：① D>0 且 s>s_num；② s≥s_guard 与力臂误差预算；③ 张力上下限与负载',
          },
          {
            sym: '六段最小长度',
            name: '连续角范围内的最小值（不是 1° 网格抽样）',
            f: 'C1 roll 13.4858 @-2.20°；C1 pitch 3.9006 @-25°；C2 roll 10.4856 @-18.49°；C2 pitch 11.8901 @33.83°；C3 roll 14.6922 @15.15°；C3 pitch 13.4454 @33.83°',
            copy: '六段最小 s/mm：C1roll 13.4858，C1pitch 3.9006，C2roll 10.4856，C2pitch 11.8901，C3roll 14.6922，C3pitch 13.4454',
          },
          {
            sym: 'C1 pitch ≤ -24°',
            name: '重点标定 / 低置信区',
            f: '-25° 时 s 只有 3.9006 mm，几何误差被放大明显；这是工程审查分区，不是已确定的物理失效阈值',
            copy: '低置信区：C1 pitch ≤ -24°（-25° 处 s = 3.9006 mm），需单独标定，不可直接外推',
          },
          {
            no: '(E2)',
            sym: 'ΔR ≈ Σ |∂R/∂P|·ε_{P} + |∂R/∂φ|·φ',
            name: '几何误差到力臂误差的一阶预算',
            f: 'φ 是轴方向微小倾转（rad）；轴上原点沿自身轴平移属规范自由度，不计位置误差',
            copy: '(E2) 一阶预算：ΔR ≈ Σ|∂R/∂P|·ε_P + |∂R/∂φ|·φ（半径 ε_P 乘位置梯度范数）',
          },
          {
            sym: '24 mm 偏置灵敏度',
            name: '两种扰动约定，数值不同',
            f: '只沿 F0 Z 移动 pitch 轴、端点固定：C1 0.185592；轴与手掌同移、局部几何不变：C1 0.151958',
            copy: '24 mm 偏置：只移轴 0.185592 mm/mm；轴与手掌同移 0.151958 mm/mm（C1，两种约定）',
          },
          {
            sym: '16.06 / 0.1856 / 15.746',
            name: '三种灵敏度口径不能混用',
            f: 'ΔR_{p1}=+16.064268（P06 沿 +Z 移 1 mm 的有限变化）；局部偏导 ≈ 15.185639；三维梯度范数 ≈ 15.745867',
            copy: '灵敏度口径：ΔR_p1=+16.064268（1 mm 有限变化）；局部偏导 15.185639；梯度范数 15.745867',
          },
          {
            no: '(28)(29)',
            sym: 'θ = q_{enc} + δ',
            name: '角度零偏与 β、γ 存在精确相位耦合',
            f: '(β, γ, δ) 只有两个独立组合 ⇒ 仅凭绳长数据无法单独识别 δ；要先用机械基准固定 δ',
            copy: '(28)(29) θ = q_enc + δ：(β,γ,δ) 只有两个独立组合，δ 不可单独识别',
          },
          {
            no: '(30)',
            sym: '可辨识自由度',
            name: '每个关节 10 个名义参数，通常 9 个有效',
            f: '三根绳的 α_i、β_i、γ_i 共享一个零偏 δ；只测 Δl 时 c_i 不可辨识',
            copy: '(30) 可辨识性：每关节 10 个名义参数，共享一个相位规范自由度，通常 9 个有效；只测 Δl 时 c_i 不可辨识',
          },
          {
            sym: '满秩 ≠ 可承载',
            name: '3,621 个姿态里 1,664 个没有全正张力解',
            f: 'R 满秩只说明能算力矩，不保证存在全正预紧解，也不保证满足张力上下限',
            copy: '满秩≠预紧：3621 个姿态中 1664 个不存在全正张力解，满秩不保证可承载',
          },
          {
            sym: '0.032668 mm',
            name: '这是差分截断误差，不是模型误差',
            f: '同一 0.2° 模板作用在解析长度上，与原表只差 1.5×10⁻⁹ mm',
            copy: '0.032668 mm 是 0.2° 差分截断误差，不是模型精度：同模板作用于解析长度只差 1.5e-9 mm',
          },
        ],
      },
      {
        id: 'ambiguity',
        title: { en: 'Ambiguous names', zh: '易混同名' },
        entries: [
          {
            sym: 'u',
            name: '同一字母两种身份（最容易错）',
            f: '第 4 节 = 单位方向向量（‖u‖ = 1）；第 5 节 = 位矢 u = A - o（mm）',
            copy: 'u：第 4 节为单位方向向量（‖u‖=1），第 5 节为位矢 u = A - o（mm）',
          },
          {
            sym: 'B',
            name: '三种身份',
            f: '3×3 基矩阵（F1）；B₀ = 运动端零位点（第 5 节）；B1–B5 = 五个边界中心姿态（附录 D1）',
            copy: 'B：3×3 基矩阵 / B0 运动端零位点 / B1–B5 五个边界中心姿态',
          },
          {
            sym: 'D',
            name: '两种身份',
            f: 'D(θ) = s²（第 5 节）；D1–D4 = 附录小节',
            copy: 'D：D(θ)=s² / D1–D4 附录小节',
          },
          {
            sym: 's',
            name: '三种身份',
            f: '一段绳长；S1–S5 = 第一部分公式编号；s_{num} / s_{guard} = 门限量',
            copy: 's：一段绳长 / S1–S5 公式编号 / s_num、s_guard 门限',
          },
          {
            sym: 'φ',
            name: '相位角 vs 倾转参数',
            f: 'φ₀ = 第 5 节相位角（rad）；φ = E2 里轴方向的微小倾转参数（rad）',
            copy: 'φ：φ0 为相位角（第 5 节）；φ 为 E2 轴倾转参数（rad）',
          },
          {
            sym: 'R / r',
            name: '矩阵 vs 标量',
            f: 'R = 2×3 力臂矩阵；r(θ) = 单段标量力臂；RMSE 里的 R 又是另一回事',
            copy: 'R / r：R 为 2×3 力臂矩阵；r(θ) 为单段标量力臂',
          },
          {
            sym: 'P / p',
            name: '点名 vs 位置向量',
            f: 'P01–P08 = 点名（大写 + 两位数字）；p₀、p(i,k) = 位置向量（小写斜体）',
            copy: 'P / p：P01–P08 为点名；p0、p(i,k) 为位置向量',
          },
          {
            sym: 'A / a',
            name: '两个身份',
            f: 'A = 跨关节段固定端；a = 轴方向单位向量；A1–A3 = 第一部分小节',
            copy: 'A / a：A 为跨关节段固定端；a 为轴方向单位向量；A1–A3 为小节编号',
          },
          {
            sym: 'C1',
            name: '绳号 vs 小节号',
            f: 'C1 = Cable 1；C1 也指第三部分第 1 小节（六段最小长度）',
            copy: 'C1：第 1 根绳（Cable 1）/ 第三部分 C1 小节',
          },
          {
            sym: 'β, γ, β 角',
            name: '系数不是角度',
            f: 'β、γ 是长度² 系数；示意图里标记的 β 角与公式里的 β 无关',
            copy: 'β、γ 是长度² 系数（mm²），不是角；示意图里的 β 角与公式 β 无关',
          },
          {
            sym: 'c_{i} vs C1',
            name: '大小写要分清',
            f: '小写 c_{i} = 常数长度之和；大写 C1 = 绳号',
            copy: 'c_i（小写）= 常数长度之和；C1（大写）= 绳号',
          },
        ],
      },
      {
        id: 'checks',
        title: { en: 'Pitfalls & self-checks', zh: '坑与自检' },
        entries: [
          {
            sym: 'rad',
            name: '公式内部一律用弧度',
            f: '长度对角度求导按“度”算会小 57.2958 倍；把度直接送进 sin/cos 是另一种错误，不是乘 57.3 能修的',
            copy: '注意：公式内部用 rad；按度求导结果小 57.2958 倍；度直接送 sin/cos 是另一类错误',
          },
          {
            sym: 'α ≥ ρ',
            name: '自检 2',
            f: '否则存在“绳长 = 0”的奇异角；α = ρ 时要检查该角是否落在行程内',
            copy: '自检：α ≥ ρ（否则存在绳长为 0 的奇异角）',
          },
          {
            sym: '|r| ≤ 半径',
            name: '自检 3',
            f: '力臂不可能大于该运动点到轴的距离',
            copy: '自检：|r(θ)| ≤ 该运动点到轴的距离',
          },
          {
            sym: 'D > 0',
            name: '自检 1',
            f: '工作角内必须成立，否则根号无意义、绳方向无定义；但它只保证数学非零，不保证控制可信',
            copy: '自检：工作角内 D(θ) > 0（只保证数学非零，不保证控制可信）',
          },
          {
            sym: '解耦',
            name: '自检 4',
            f: '∂R_{ri}/∂θ_{p} = ∂R_{pi}/∂θ_{r} = 0；不为 0 说明绳路拓扑变了',
            copy: '自检：∂R_ri/∂θ_p = ∂R_pi/∂θ_r = 0（不为 0 说明绳路拓扑变了）',
          },
          {
            sym: '24 mm',
            name: 'pitch 轴心',
            f: 'pitch 轴过 (0,0,24 mm)；当成原点会让力臂差 24 mm 量级',
            copy: '注意：pitch 轴过 (0,0,24 mm)，当成原点会让力臂差 24 mm 量级',
          },
          {
            sym: 'B^{T} 转置',
            name: '基矩阵的存法',
            f: 'JSON 里 B 按行存数组，但代表按列放基向量；用错最大差 183.85 mm',
            copy: '注意：B 在 JSON 里按行存数组，但代表按列放基向量；不转置最大差 183.85 mm',
          },
          {
            sym: '(S4) / (27) 历史印反',
            name: 'sin 项符号的两个历史问题',
            f: '早期印本把 (S4)、(27) 的 sin 项印反；引用时以通式 (23) 自己代一遍最稳',
            copy: '注意：(S4)、(27) 早期印本 sin 项印反；引用以通式 (23) 为准，自己代一遍',
          },
          {
            sym: '力臂符号取反',
            name: '后果不是“差个负号”',
            f: '控制方向反，闭环会发散；先用零位值对一遍符号',
            copy: '注意：力臂符号取反会让控制方向反、闭环发散；先用零位值核对符号',
          },
          {
            sym: '‖v‖ 当半径 b',
            name: '少减了轴向分量',
            f: 'b = ‖v_{⊥}‖ 而不是 ‖v‖；用错会让 α/β/γ 全错',
            copy: '注意：b = ‖v⊥‖ 不是 ‖v‖；少减轴向分量会让 α/β/γ 全错',
          },
        ],
      },
    ];

    /* ==== WRIST3D:BEGIN — 3D 场景移植自 腕部公式_可视化沙盘.html（canvas 2D，零依赖） ==== */
    function createWristView(cv) {
      var g = cv.getContext('2d');
      var st = {
        w: 0, h: 0, dpr: 1,
        tr: 0, tp: 0,
        azBase: 0.62, elBase: 0.30,
        azUser: 0, elUser: 0,
        t: 0,
        scale: 1, center: [0, 0, 0], span: 1,
        min: [0, 0, 0], max: [0, 0, 0],
        offx: 0, offy: 0,
      };

        var DEG = Math.PI/180;
        var YR = [0,1,0], XP = [1,0,0], OP = [0,0,24];

        function sub(a,b){ return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
        function add(a,b){ return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]; }
        function dot(a,b){ return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
        function cross(a,b){ return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }
        function len(a){ return Math.sqrt(dot(a,a)); }

        /* 绕过原点的单位轴旋转（Rodrigues） */
        function rotAxis(p, k, th){
          var c = Math.cos(th), s = Math.sin(th), kv = cross(k,p), kd = dot(k,p);
          return [
            p[0]*c + kv[0]*s + k[0]*kd*(1-c),
            p[1]*c + kv[1]*s + k[1]*kd*(1-c),
            p[2]*c + kv[2]*s + k[2]*kd*(1-c)
          ];
        }
        function rotAbout(p, o, k, th){ return add(o, rotAxis(sub(p,o), k, th)); }

        /* ================= 真实几何数据（零位，mm） ================= */
        var CABLES = [
          { name:'C1', color:'#22d3ee', c:0,
            rl:{a:364.5, b:-182.5, g:7.0},
            pt:{a:7263.47364742, b:-6537.66603142, g:3130.77161942},
            pts:[[27,85,-35],[27,85,-27],[0.5,55,-5],[0.5,55,5],
                 [2.5,58,18],[2.5,58,30],[2.3215,53,56.4722],[2.3215,53,61.4722]] },
          { name:'C2', color:'#a78bfa', c:0,
            rl:{a:2150.25, b:-1935, g:647},
            pt:{a:820.33042151, b:-564.0, g:-378.0},
            pts:[[-23,-20,-35],[-23,-20,-27],[-27,-16,-5],[-27,-16,5],
                 [-32.5,-12,18],[-32.5,-12,30],[-32.2164,-12.5,46],[-32.2164,-15.5,54]] },
          { name:'C3', color:'#fbbf24', c:0,
            rl:{a:2500.25, b:-2205, g:-597},
            pt:{a:859.73346622, b:-564.0, g:-378.0},
            pts:[[23,-20,-35],[23,-20,-27],[27,-16,-5],[27,-16,5],
                 [37.5,-12,18],[37.5,-12,30],[43.7836,-12.5,46],[43.7836,-15.5,54]] }
        ];

        /* α/β/γ 直接由零位坐标反算（式 19–21）：页面上的数字不是抄来的 */
        function coeffs(u, v, a){
          var au = dot(a,u), av = dot(a,v);
          return {
            a: dot(u,u) + dot(v,v) - 2*au*av,
            b: -2*(dot(u,v) - au*av),
            g: -2*dot(u, cross(a,v))
          };
        }
        CABLES.forEach(function(cab){
          cab.rl = coeffs(cab.pts[3], cab.pts[4], YR);                   /* P04、P05 绕 roll 轴 */
          cab.pt = coeffs(sub(cab.pts[5], OP), sub(cab.pts[6], OP), XP); /* P06、P07 绕 pitch 轴 */
        });

        /* 各绳的世界坐标（base 不动；roll_link 随 θr；palm 先随 θp 再整体随 θr） */
        function worldPts(cab, tr, tp){
          var out = [], i, p;
          for(i = 0; i < 8; i++){
            p = cab.pts[i];
            if(i < 4){
              out.push([p[0], p[1], p[2]]);
            } else if(i < 6){
              out.push(rotAbout(p, [0,0,0], YR, tr));
            } else {
              var q = add(OP, rotAxis(sub(p, OP), XP, tp));
              out.push(rotAbout(q, [0,0,0], YR, tr));
            }
          }
          return out;
        }

        function geoLen(cab, tr, tp){
          var w = worldPts(cab, tr, tp), L = 0;
          for(var i = 1; i < 8; i++) L += len(sub(w[i], w[i-1]));
          return L;
        }
        function closedLen(cab, tr, tp){
          var D1 = cab.rl.a + cab.rl.b*Math.cos(tr) + cab.rl.g*Math.sin(tr);
          var D2 = cab.pt.a + cab.pt.b*Math.cos(tp) + cab.pt.g*Math.sin(tp);
          return cab.c + Math.sqrt(Math.max(D1,0)) + Math.sqrt(Math.max(D2,0));
        }
        function arm(th, k){
          var D = k.a + k.b*Math.cos(th) + k.g*Math.sin(th);
          return (k.b*Math.sin(th) - k.g*Math.cos(th)) / (2*Math.sqrt(Math.max(D,1e-9)));
        }
        /* 常数段长度：P1P2 + P2P3 + P3P4 + P5P6 + P7P8（零位） */
        CABLES.forEach(function(cab){
          var s = 0, i;
          for(i = 1; i < 8; i++){
            if(i === 4 || i === 6) continue;   /* 跳过跨关节段 P4-P5、P6-P7 */
            s += len(sub(cab.pts[i], cab.pts[i-1]));
          }
          cab.c = s;
        });


        function fitScene(){
          var trs = [-20,0,20], tps = [-18,0,20,40];
          var min = [1e9,1e9,1e9], max = [-1e9,-1e9,-1e9];
          function acc(p){
            for(var i=0;i<3;i++){ if(p[i]<min[i]) min[i]=p[i]; if(p[i]>max[i]) max[i]=p[i]; }
          }
          trs.forEach(function(a){
            tps.forEach(function(b){
              CABLES.forEach(function(cab){
                worldPts(cab, a*DEG, b*DEG).forEach(acc);
              });
            });
          });
          /* 只按机构本身取景，轴线允许出画 */
          st.center = [(min[0]+max[0])/2, (min[1]+max[1])/2, (min[2]+max[2])/2];
          var span = Math.max(max[0]-min[0], max[1]-min[1], max[2]-min[2]);
          st.span = span;
          st.min = min; st.max = max;
        }

        function basis(){
          var az = st.azBase + 0.18*Math.sin(st.t*0.22) + st.azUser;
          var el = Math.max(0.06, Math.min(1.15, st.elBase + st.elUser));
          var ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
          var dir = [ce*ca, ce*sa, se];
          var right = [-sa, ca, 0];
          var up = cross(dir, right);
          return { dir:dir, right:right, up:up };
        }

        function resizeScene(){
          var r = cv.getBoundingClientRect();
          st.dpr = Math.min(window.devicePixelRatio || 1, 2);
          st.w = r.width; st.h = r.height;
          cv.width = Math.round(r.width * st.dpr);
          cv.height = Math.round(r.height * st.dpr);
          g.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
          /* 用当前方位估计缩放：把包围盒 8 个角投影后塞进画布 */
          var b = basis();
          var minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;
          var mn = st.min, mx = st.max;
          for(var i = 0; i < 8; i++){
            var p = [i&1?mx[0]:mn[0], i&2?mx[1]:mn[1], i&4?mx[2]:mn[2]];
            var d = sub(p, st.center);
            var x = dot(d, b.right), y = dot(d, b.up);
            if(x<minx)minx=x; if(x>maxx)maxx=x; if(y<miny)miny=y; if(y>maxy)maxy=y;
          }
          var sx = (st.w*1.24) / Math.max(maxx-minx, 1e-6);
          var sy = (st.h*1.12) / Math.max(maxy-miny, 1e-6);
          st.scale = Math.min(sx, sy);
        }

        function project(p, b){
          var d = sub(p, st.center);
          return [ st.w/2 + st.offx + dot(d, b.right)*st.scale,
                   st.h/2 + st.offy - dot(d, b.up)*st.scale ];
        }

        function updateOffset(b){
          var mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9;
          CABLES.forEach(function(c){
            worldPts(c, 0, 0).forEach(function(p){
              var d = sub(p, st.center);
              var x = dot(d, b.right), y = dot(d, b.up);
              if(x < mnx) mnx = x; if(x > mxx) mxx = x;
              if(y < mny) mny = y; if(y > mxy) mxy = y;
            });
          });
          st.offx = -((mnx + mxx)/2)*st.scale;
          st.offy = ((mny + mxy)/2)*st.scale;
        }

        function hull2d(pts){
          if(pts.length < 3) return pts.slice();
          var s = pts.slice().sort(function(a,b){ return a[0]-b[0] || a[1]-b[1]; });
          var lower = [], upper = [], i;
          for(i = 0; i < s.length; i++){
            while(lower.length >= 2 && cross2(lower[lower.length-2], lower[lower.length-1], s[i]) <= 0) lower.pop();
            lower.push(s[i]);
          }
          for(i = s.length-1; i >= 0; i--){
            while(upper.length >= 2 && cross2(upper[upper.length-2], upper[upper.length-1], s[i]) <= 0) upper.pop();
            upper.push(s[i]);
          }
          lower.pop(); upper.pop();
          return lower.concat(upper);
        }

        function cross2(o,a,b){ return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0]); }

        function line(p1, p2, color, width, dash){
          g.save();
          g.strokeStyle = color;
          g.lineWidth = width || 1;
          if(dash) g.setLineDash(dash);
          g.beginPath();
          g.moveTo(p1[0], p1[1]);
          g.lineTo(p2[0], p2[1]);
          g.stroke();
          g.restore();
        }

        function line(p1, p2, color, width, dash){
          g.save();
          g.strokeStyle = color;
          g.lineWidth = width || 1;
          if(dash) g.setLineDash(dash);
          g.beginPath();
          g.moveTo(p1[0], p1[1]);
          g.lineTo(p2[0], p2[1]);
          g.stroke();
          g.restore();
        }

        function label(text, x, y, color, size){
          g.save();
          var fs = size || 11;
          g.font = fs + 'px "JetBrains Mono", Consolas, monospace';
          var tw = g.measureText(text).width;
          g.fillStyle = 'rgba(9,12,18,.62)';
          g.fillRect(x - 3, y - fs + 1, tw + 6, fs + 4);
          g.fillStyle = color || 'rgba(190,205,235,.8)';
          g.fillText(text, x, y);
          g.restore();
        }

        function arrowHead(from, to, color){
          var dx = to[0]-from[0], dy = to[1]-from[1];
          var a = Math.atan2(dy, dx), size = 7;
          g.save();
          g.fillStyle = color;
          g.beginPath();
          g.moveTo(to[0], to[1]);
          g.lineTo(to[0]-size*Math.cos(a-0.4), to[1]-size*Math.sin(a-0.4));
          g.lineTo(to[0]-size*Math.cos(a+0.4), to[1]-size*Math.sin(a+0.4));
          g.closePath();
          g.fill();
          g.restore();
        }

        function drawAxes(b){
          var o = project([0,0,0], b);
          var ry = project([0,96,0], b);
          var py = project([54,0,24], b);
          var px0 = project([-40,0,24], b);

          line(px0, py, 'rgba(120,150,210,.28)', 1, [4,6]);
          line(o, ry, 'rgba(120,150,210,.28)', 1, [4,6]);
          arrowHead(px0, py, 'rgba(160,185,235,.55)');
          arrowHead(o, ry, 'rgba(160,185,235,.55)');

          label('roll 轴 +Y', ry[0]+8, ry[1]+12, 'rgba(170,195,240,.75)');

          /* 24 mm 偏置 */
          var p0 = project([0,0,0], b);
          var p24 = project([0,0,24], b);
          line(p0, p24, 'rgba(251,191,36,.55)', 1.5, [3,4]);
          var mid = [(p0[0]+p24[0])/2, (p0[1]+p24[1])/2];
          g.save();
          g.fillStyle = 'rgba(251,191,36,.85)';
          g.font = '11px "JetBrains Mono", Consolas, monospace';
          g.restore();

          /* 原点 */
          g.save();
          g.fillStyle = 'rgba(255,255,255,.85)';
          g.beginPath(); g.arc(o[0], o[1], 2.6, 0, Math.PI*2); g.fill();
          g.restore();
        }

        function drawBodies(b){
          var worlds = CABLES.map(function(cab){ return worldPts(cab, st.tr, st.tp); });

          /* base：三块侧板的整体轮廓（12 个锚点）+ 各自的边 */
          var baseAll2 = [];
          worlds.forEach(function(w){
            for(var i = 0; i < 4; i++) baseAll2.push(project(w[i], b));
          });
          var bh = hull2d(baseAll2);
          g.save();
          g.fillStyle = 'rgba(120,160,240,.05)';
          g.strokeStyle = 'rgba(140,175,240,.20)';
          g.lineWidth = 1;
          g.beginPath();
          bh.forEach(function(p,i){ if(i) g.lineTo(p[0],p[1]); else g.moveTo(p[0],p[1]); });
          g.closePath(); g.fill(); g.stroke();
          g.restore();

          worlds.forEach(function(w){
            var h = hull2d(w.slice(0,4).map(function(p){ return project(p,b); }));
            g.save();
            g.fillStyle = 'rgba(140,175,255,.06)';
            g.strokeStyle = 'rgba(150,185,255,.26)';
            g.lineWidth = 1;
            g.beginPath();
            h.forEach(function(p,i){ if(i) g.lineTo(p[0],p[1]); else g.moveTo(p[0],p[1]); });
            g.closePath();
            g.fill(); g.stroke();
            g.restore();
          });

          /* palm：六个锚点合成一块掌板 */
          var palm2 = [];
          worlds.forEach(function(w){ palm2.push(project(w[6],b), project(w[7],b)); });
          var ph = hull2d(palm2);
          g.save();
          g.fillStyle = 'rgba(167,139,250,.075)';
          g.strokeStyle = 'rgba(190,170,255,.32)';
          g.lineWidth = 1;
          g.beginPath();
          ph.forEach(function(p,i){ if(i) g.lineTo(p[0],p[1]); else g.moveTo(p[0],p[1]); });
          g.closePath(); g.fill(); g.stroke();
          g.restore();

          /* roll_link：三根短杆 */
          worlds.forEach(function(w){
            var a = project(w[4],b), c = project(w[5],b);
            g.save();
            g.strokeStyle = 'rgba(170,200,255,.30)';
            g.lineWidth = 6; g.lineCap = 'round';
            g.beginPath(); g.moveTo(a[0],a[1]); g.lineTo(c[0],c[1]); g.stroke();
            g.strokeStyle = 'rgba(225,238,255,.55)'; g.lineWidth = 1;
            g.beginPath(); g.moveTo(a[0],a[1]); g.lineTo(c[0],c[1]); g.stroke();
            g.restore();
          });

          /* 刚体名字 */
          var baseAll = [], rollAll = [];
          worlds.forEach(function(w){
            for(var i=0;i<4;i++) baseAll.push(project(w[i],b));
            rollAll.push(project(w[4],b), project(w[5],b));
          });
          tagHull(baseAll, 'base', 18);
          tagHull(palm2, 'palm', -16);
        }

        function tagHull(pts, text, dy){
          if(!pts.length) return;
          var x = 0, y = 0;
          pts.forEach(function(p){ x += p[0]; y += p[1]; });
          x /= pts.length; y /= pts.length;
          g.save();
          g.font = '10px "JetBrains Mono", Consolas, monospace';
          g.textAlign = 'center';
          var tw = g.measureText(text).width;
          var ty = y + (dy || 0);
          g.fillStyle = 'rgba(9,12,18,.62)';
          g.fillRect(x - tw / 2 - 3, ty - 9, tw + 6, 13);
          g.fillStyle = 'rgba(175,200,240,.72)';
          g.fillText(text, x, ty);
          g.restore();
        }

        function drawRope(cab, b, t){
          var w = worldPts(cab, st.tr, st.tp);
          var p = w.map(function(q){ return project(q,b); });

          /* 外发光 */
          g.save();
          g.lineJoin = 'round'; g.lineCap = 'round';
          g.shadowColor = cab.color; g.shadowBlur = 16;
          g.strokeStyle = cab.color; g.globalAlpha = 0.30; g.lineWidth = 7;
          g.beginPath();
          p.forEach(function(q,i){ if(i) g.lineTo(q[0],q[1]); else g.moveTo(q[0],q[1]); });
          g.stroke();
          g.restore();

          /* 主体 */
          g.save();
          g.lineJoin = 'round'; g.lineCap = 'round';
          g.strokeStyle = cab.color; g.globalAlpha = 0.95; g.lineWidth = 2.2;
          g.beginPath();
          p.forEach(function(q,i){ if(i) g.lineTo(q[0],q[1]); else g.moveTo(q[0],q[1]); });
          g.stroke();
          g.restore();

          /* 流动虚线：表示"张力沿绳传播" */
          g.save();
          g.lineJoin = 'round'; g.lineCap = 'round';
          g.setLineDash([2,10]);
          g.lineDashOffset = -t*46;
          g.strokeStyle = 'rgba(255,255,255,.85)'; g.lineWidth = 1.6;
          g.beginPath();
          p.forEach(function(q,i){ if(i) g.lineTo(q[0],q[1]); else g.moveTo(q[0],q[1]); });
          g.stroke();
          g.restore();

          /* 跨关节两段高亮 */
          [[4,5],[6,7]].forEach(function(pair){
            var i = pair[0], j = pair[1];
            g.save();
            g.lineCap = 'round';
            g.strokeStyle = 'rgba(255,255,255,.9)';
            g.lineWidth = 4.2;
            g.globalAlpha = 0.5 + 0.5*Math.sin(t*3 + i);
            g.beginPath();
            g.moveTo(p[i][0], p[i][1]); g.lineTo(p[j][0], p[j][1]);
            g.stroke();
            g.restore();
          });

          /* 导向点 */
          p.forEach(function(q){
            g.save();
            g.fillStyle = '#fff';
            g.shadowColor = cab.color; g.shadowBlur = 10;
            g.beginPath(); g.arc(q[0], q[1], 2.4, 0, Math.PI*2); g.fill();
            g.restore();
          });
        }

        function drawArcs(b){
          var tr = st.tr, tp = st.tp;

          /* roll 角弧：在 y=58 平面上绕 Y 轴 */
          if(Math.abs(tr) > 0.02){
            g.save();
            g.strokeStyle = 'rgba(34,211,238,.55)'; g.lineWidth = 1.4;
            g.beginPath();
            for(var i = 0; i <= 40; i++){
              var a = tr * i/40;
              var q = project([22*Math.cos(a), 44, -22*Math.sin(a)], b);
              if(i) g.lineTo(q[0],q[1]); else g.moveTo(q[0],q[1]);
            }
            g.stroke();
            g.restore();
            var tip = project([22*Math.cos(tr), 44, -22*Math.sin(tr)], b);
            g.save();
            g.fillStyle = 'rgba(34,211,238,.9)';
            g.font = '600 12px "JetBrains Mono", Consolas, monospace';
            g.fillText('θr', tip[0]+6, tip[1]-4);
            g.restore();
          }

          /* pitch 角弧：在 x=0 平面上绕 X 轴 */
          if(Math.abs(tp) > 0.02){
            g.save();
            g.strokeStyle = 'rgba(167,139,250,.55)'; g.lineWidth = 1.4;
            g.beginPath();
            for(var j = 0; j <= 40; j++){
              var c = tp * j/40;
              var q2 = project([0, 16*Math.cos(c), 24 + 16*Math.sin(c)], b);
              if(j) g.lineTo(q2[0],q2[1]); else g.moveTo(q2[0],q2[1]);
            }
            g.stroke();
            g.restore();
            var tip2 = project([0, 16*Math.cos(tp), 24 + 16*Math.sin(tp)], b);
            g.save();
            g.fillStyle = 'rgba(167,139,250,.9)';
            g.font = '600 12px "JetBrains Mono", Consolas, monospace';
            g.fillText('θp', tip2[0]+6, tip2[1]-4);
            g.restore();
          }
        }

        function drawFloor(b){
          var z = -44, i;
          g.save();
          g.strokeStyle = 'rgba(120,160,230,.075)';
          g.lineWidth = 1;
          for(i = -45; i <= 45; i += 15){
            var a = project([i, -30, z], b), c = project([i, 90, z], b);
            g.beginPath(); g.moveTo(a[0],a[1]); g.lineTo(c[0],c[1]); g.stroke();
          }
          for(i = -30; i <= 90; i += 15){
            var d = project([-45, i, z], b), e = project([45, i, z], b);
            g.beginPath(); g.moveTo(d[0],d[1]); g.lineTo(e[0],e[1]); g.stroke();
          }
          g.restore();
        }

        function renderScene(){
          var b = basis();
          updateOffset(b);
          g.clearRect(0, 0, st.w, st.h);

          /* 背景光晕 */
          var glow = g.createRadialGradient(st.w*0.5, st.h*0.42, 10, st.w*0.5, st.h*0.42, Math.max(st.w,st.h)*0.7);
          glow.addColorStop(0, 'rgba(34,211,238,.07)');
          glow.addColorStop(1, 'rgba(0,0,0,0)');
          g.fillStyle = glow;
          g.fillRect(0, 0, st.w, st.h);

          drawFloor(b);
          drawAxes(b);
          drawBodies(b);
          CABLES.forEach(function(cab){ drawRope(cab, b, st.t); });
          drawArcs(b);
        }

      fitScene();

      /** R(2×3) 与 f = 10 N 下的关节力矩，单位 mm/rad、N·mm。 */
      function readout(tr, tp) {
        var R = [[], []];
        for (var i = 0; i < 3; i++) {
          R[0].push(arm(tr, CABLES[i].rl));
          R[1].push(arm(tp, CABLES[i].pt));
        }
        var f = 10;
        return {
          R: R,
          tau: [R[0][0] * f + R[0][1] * f + R[0][2] * f, R[1][0] * f + R[1][1] * f + R[1][2] * f],
          lengths: CABLES.map(function (cab) {
            var geo = geoLen(cab, tr, tp);
            var closed = closedLen(cab, tr, tp);
            return { name: cab.name, geo: geo, closed: closed, diff: geo - closed };
          }),
        };
      }

      return {
        state: st,
        resize: function () {
          resizeScene();
          renderScene();
        },
        render: renderScene,
        readout: readout,
      };
    }
    /* ==== WRIST3D:END ==== */

    /* ==== SANDBOX-PAGE:BEGIN — 整页内嵌，生成自 腕部公式_可视化沙盘.html，勿手改 ==== */
    const PAGE_HTML = "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>绳驱二轴腕部 · 公式可视化沙盘</title>\n<style>\n  :root{\n    --bg:#05070f;\n    --bg2:#0a1020;\n    --panel:rgba(16,23,42,.72);\n    --line:rgba(122,152,210,.18);\n    --ink:#e9eefb;\n    --muted:#95a4c4;\n    --cyan:#22d3ee;\n    --violet:#a78bfa;\n    --amber:#fbbf24;\n    --pink:#fb7185;\n    --grad:linear-gradient(115deg,#22d3ee,#a78bfa 48%,#fbbf24);\n    --mono:\"JetBrains Mono\",Consolas,\"Cascadia Mono\",monospace;\n  }\n  *{box-sizing:border-box}\n  html{scroll-behavior:smooth}\n  body{\n    margin:0;background:var(--bg);color:var(--ink);\n    font-family:\"Inter\",\"Segoe UI Variable\",\"Segoe UI\",\"PingFang SC\",\"Microsoft YaHei\",sans-serif;\n    -webkit-font-smoothing:antialiased;overflow-x:hidden;\n  }\n  body::before{\n    content:\"\";position:fixed;inset:0;z-index:-2;pointer-events:none;\n    background:\n      radial-gradient(900px 600px at 12% -8%,rgba(34,211,238,.16),transparent 60%),\n      radial-gradient(800px 700px at 88% 8%,rgba(167,139,250,.15),transparent 60%),\n      radial-gradient(900px 700px at 50% 105%,rgba(251,191,36,.09),transparent 60%),\n      linear-gradient(180deg,#05070f,#070b16 40%,#05070f);\n  }\n  body::after{\n    content:\"\";position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.35;\n    background-image:linear-gradient(rgba(120,150,210,.06) 1px,transparent 1px),\n                     linear-gradient(90deg,rgba(120,150,210,.06) 1px,transparent 1px);\n    background-size:64px 64px;\n    mask-image:radial-gradient(circle at 50% 20%,#000 10%,transparent 75%);\n  }\n  #progress{position:fixed;top:0;left:0;height:2px;width:0;z-index:100;background:var(--grad);box-shadow:0 0 12px rgba(34,211,238,.8)}\n  .wrap{width:100%;max-width:1180px;margin:0 auto;padding:0 24px}\n  .reveal{opacity:0;transform:translateY(26px);transition:opacity .9s cubic-bezier(.2,.7,.2,1),transform .9s cubic-bezier(.2,.7,.2,1)}\n  .reveal.in{opacity:1;transform:none}\n  .eyebrow{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}\n  h1,h2,h3{margin:0;font-weight:650;letter-spacing:-.01em}\n  p{line-height:1.85;color:#c2cde5}\n  .grad{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}\n  code,.mono{font-family:var(--mono)}\n\n  /* ---------- hero ---------- */\n  header{position:relative;min-height:100vh;display:flex;align-items:center;overflow:hidden}\n  .hero-orbs{position:absolute;inset:0;pointer-events:none}\n  .orb{position:absolute;border-radius:50%;filter:blur(60px);opacity:.5;animation:float 16s ease-in-out infinite}\n  .orb.a{width:420px;height:420px;left:-80px;top:12%;background:rgba(34,211,238,.35)}\n  .orb.b{width:520px;height:520px;right:-120px;top:0;background:rgba(167,139,250,.32);animation-delay:-6s}\n  .orb.c{width:360px;height:360px;left:40%;bottom:-160px;background:rgba(251,191,36,.18);animation-delay:-11s}\n  @keyframes float{0%,100%{transform:translate3d(0,0,0) scale(1)}50%{transform:translate3d(20px,-30px,0) scale(1.08)}}\n  .hero-inner{position:relative;z-index:2;padding:120px 0 90px}\n  .badges{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 0}\n  .chip{font-size:12px;padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:rgba(255,255,255,.03);color:#b9c6e2}\n  .chip b{color:var(--ink);font-weight:600}\n  h1{font-size:clamp(40px,7vw,86px);line-height:1.02;margin-top:18px}\n  .hero-sub{max-width:640px;font-size:clamp(15px,1.4vw,18px);margin-top:26px;color:#a9b7d4}\n  .hero-meta{display:flex;gap:34px;margin-top:44px;flex-wrap:wrap}\n  .stat b{display:block;font-family:var(--mono);font-size:26px;color:#fff;letter-spacing:-.02em}\n  .stat span{font-size:12px;color:var(--muted);letter-spacing:.08em}\n  .scroll-hint{position:absolute;left:50%;bottom:26px;transform:translateX(-50%);font-size:11px;letter-spacing:.28em;color:var(--muted);display:flex;flex-direction:column;align-items:center;gap:10px}\n  .scroll-hint i{display:block;width:1px;height:42px;background:linear-gradient(#22d3ee,transparent);animation:pulse 1.8s ease-in-out infinite}\n  @keyframes pulse{0%,100%{opacity:.2;transform:scaleY(.6)}50%{opacity:1;transform:scaleY(1)}}\n\n  /* ---------- sections ---------- */\n  section{position:relative;padding:96px 0}\n  .sec-head{display:flex;align-items:baseline;gap:18px;margin-bottom:10px}\n  .sec-num{font-family:var(--mono);font-size:13px;color:var(--cyan);letter-spacing:.1em}\n  h2{font-size:clamp(26px,3.4vw,40px);line-height:1.15}\n  .lead{max-width:760px;font-size:16px;margin-top:16px}\n  .divider{height:1px;background:linear-gradient(90deg,transparent,var(--line),transparent);margin:0 0 70px}\n\n  /* ---------- stage ---------- */\n  .stage{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(0,1fr);gap:18px;align-items:stretch}\n  .viewport{position:relative;border:1px solid var(--line);border-radius:22px;overflow:hidden;background:\n      radial-gradient(700px 420px at 50% 0%,rgba(34,211,238,.10),transparent 70%),\n      linear-gradient(180deg,rgba(12,19,36,.9),rgba(6,10,20,.95));min-height:620px}\n  #scene{position:absolute;inset:0;display:block;width:100%;height:100%;cursor:grab;touch-action:none}\n  #scene.drag{cursor:grabbing}\n  .vp-tag{position:absolute;top:14px;left:14px;font-size:11px;letter-spacing:.16em;color:#9fb0d0;background:rgba(6,10,20,.6);border:1px solid var(--line);padding:6px 10px;border-radius:999px}\n  .vp-hint{position:absolute;bottom:12px;left:14px;font-size:11px;color:#7d8cab}\n  .legend{position:absolute;top:14px;right:14px;display:flex;flex-direction:column;gap:7px;font-size:11px;color:#a9b7d4;background:rgba(6,10,20,.55);border:1px solid var(--line);padding:10px 12px;border-radius:12px}\n  .legend i{display:inline-block;width:18px;height:3px;border-radius:2px;margin-right:8px;vertical-align:middle}\n  .panel{border:1px solid var(--line);border-radius:22px;background:var(--panel);backdrop-filter:blur(12px);padding:20px}\n  .ctl-row{display:grid;grid-template-columns:64px 1fr 74px;align-items:center;gap:12px;margin-bottom:18px}\n  .ctl-row label{font-size:12px;color:var(--muted);letter-spacing:.04em}\n  .ctl-row output{font-family:var(--mono);font-size:13px;text-align:right;color:#eaf1ff}\n  input[type=range]{-webkit-appearance:none;appearance:none;height:2px;border-radius:2px;background:linear-gradient(90deg,rgba(34,211,238,.8),rgba(167,139,250,.8));outline:none}\n  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:#fff;box-shadow:0 0 0 4px rgba(34,211,238,.22),0 0 16px rgba(34,211,238,.7);cursor:pointer}\n  .btn{font:inherit;font-size:12px;color:#0a1020;background:linear-gradient(115deg,#8ee9f7,#cbb8ff);border:0;border-radius:10px;padding:9px 14px;cursor:pointer;font-weight:650;letter-spacing:.02em}\n  .btn.ghost{background:transparent;color:#bcc9e4;border:1px solid var(--line)}\n  .btn:active{transform:translateY(1px)}\n  .btn-row{display:flex;gap:8px;margin:4px 0 18px}\n  .readout{font-family:var(--mono);font-size:12.5px}\n  .ro-row{display:grid;grid-template-columns:38px 1fr 1fr 62px;gap:6px;padding:7px 0;border-top:1px dashed rgba(122,152,210,.14);align-items:baseline}\n  .ro-row.head{color:var(--muted);font-size:11px;border-top:0}\n  .ro-row .nm{font-weight:700}\n  .ro-row .d{color:#6f7f9e;font-size:11px}\n  .matrix{display:grid;grid-template-columns:44px repeat(3,1fr);gap:6px;margin-top:18px}\n  .matrix .h{font-size:10.5px;color:var(--muted);display:flex;align-items:center;justify-content:center;letter-spacing:.06em}\n  .cell{border-radius:10px;padding:10px 6px;text-align:center;font-family:var(--mono);font-size:13px;border:1px solid rgba(122,152,210,.16);background:rgba(255,255,255,.02)}\n  .cell.neg{color:#ffd7dd}\n  .cell.pos{color:#d6fff6}\n  .tau{display:flex;gap:10px;margin-top:14px;font-family:var(--mono);font-size:12.5px;color:#c9d6ef}\n  .tau div{flex:1;border:1px solid var(--line);border-radius:10px;padding:9px 10px;background:rgba(255,255,255,.02)}\n  .tau span{color:#7f8eae;font-size:11px;display:block;margin-bottom:3px}\n\n  /* ---------- generic cards ---------- */\n  .cols{display:grid;grid-template-columns:1fr 1fr;gap:36px;align-items:center}\n  .card{border:1px solid var(--line);border-radius:18px;padding:22px;background:rgba(14,21,38,.6)}\n  .card h3{font-size:15px;margin-bottom:10px;color:#eaf1ff}\n  .card p{font-size:14px;margin:0;color:#a9b7d4}\n  .eq{font-family:\"Cambria Math\",Cambria,\"Times New Roman\",serif;font-size:clamp(19px,2.2vw,27px);line-height:1.7;color:#f2f6ff;text-align:center}\n  .eq .small{font-size:.62em;color:#9fb0d0}\n  .frac{display:inline-flex;flex-direction:column;text-align:center;vertical-align:middle;margin:0 .18em}\n  .frac .num{border-bottom:1.5px solid rgba(233,238,251,.75);padding:0 .34em .1em}\n  .frac .den{padding:.12em .34em 0}\n  .eqbox{border:1px solid var(--line);border-radius:18px;padding:26px 20px;background:\n      radial-gradient(400px 160px at 50% 0%,rgba(34,211,238,.12),transparent 70%),rgba(10,16,30,.7);margin:22px 0}\n  ul.clean{margin:0;padding-left:0;list-style:none}\n  ul.clean li{position:relative;padding-left:22px;margin:14px 0;color:#b6c3dd;line-height:1.75;font-size:14.5px}\n  ul.clean li::before{content:\"\";position:absolute;left:2px;top:.62em;width:7px;height:7px;border-radius:2px;background:var(--grad)}\n  ul.clean b{color:#fff;font-weight:600}\n  canvas.chart{width:100%;height:240px;display:block}\n  .chart-pad{padding:8px 0 0}\n  .cap{font-size:12px;color:#7d8cab;margin-top:10px}\n  .kbd{font-family:var(--mono);font-size:12px;padding:2px 6px;border-radius:5px;border:1px solid var(--line);color:#cddaf3}\n\n  /* ---------- verification ---------- */\n  .counters{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0 34px}\n  .counter{border:1px solid var(--line);border-radius:16px;padding:18px;background:rgba(14,21,38,.6)}\n  .counter b{display:block;font-family:var(--mono);font-size:24px;color:#fff;letter-spacing:-.02em}\n  .counter span{font-size:11.5px;color:var(--muted);display:block;margin-top:6px;line-height:1.5}\n  .bars{display:grid;gap:14px}\n  .bar-row{display:grid;grid-template-columns:190px 1fr 110px;gap:14px;align-items:center;font-size:12.5px;color:#b6c3dd}\n  .track{height:8px;border-radius:999px;background:rgba(255,255,255,.05);overflow:hidden}\n  .fill{height:100%;width:0;border-radius:999px;background:var(--grad);transition:width 1.4s cubic-bezier(.2,.8,.2,1)}\n  .bar-row .v{font-family:var(--mono);color:#e7eefc;text-align:right;font-size:12px}\n\n  /* ---------- cheat sheet ---------- */\n  .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}\n  .formula{border:1px solid var(--line);border-radius:16px;padding:18px;background:rgba(14,21,38,.55);min-height:132px}\n  .formula .t{font-size:11px;letter-spacing:.14em;color:var(--cyan);margin-bottom:12px}\n  .formula .f{font-family:\"Cambria Math\",Cambria,\"Times New Roman\",serif;font-size:17px;color:#eef3ff;line-height:1.6}\n  .formula .n{font-size:11.5px;color:#8394b5;margin-top:10px;line-height:1.6}\n  footer{padding:70px 0 60px;border-top:1px solid var(--line);color:#7d8cab;font-size:12.5px}\n  footer a{color:#a9d8ff;text-decoration:none;border-bottom:1px dotted rgba(169,216,255,.4)}\n  .src{display:flex;flex-wrap:wrap;gap:18px;margin-top:14px}\n\n  @media (max-width:920px){\n    .stage,.cols{grid-template-columns:1fr}\n    .counters{grid-template-columns:repeat(2,1fr)}\n    .grid3{grid-template-columns:1fr}\n    .bar-row{grid-template-columns:130px 1fr 90px}\n    .viewport{min-height:480px}\n    section{padding:70px 0}\n  }\n</style>\n</head>\n<body>\n<div id=\"progress\"></div>\n\n<header>\n  <div class=\"hero-orbs\"><div class=\"orb a\"></div><div class=\"orb b\"></div><div class=\"orb c\"></div></div>\n  <div class=\"wrap hero-inner\">\n    <div class=\"eyebrow\">绳驱二轴腕部 · 解析模型 v2.0 · 交互图解</div>\n    <h1>一根绳的长度<br><span class=\"grad\">变成整只手腕的力矩</span></h1>\n    <p class=\"hero-sub\">把 PDF 里从虚功到力臂矩阵的推理链，做成可以拖动、可以看见的东西。三根绳、两个关节、六组系数，所有数字都来自真实 CAD 标点与复核数据。</p>\n    <div class=\"badges\">\n      <div class=\"chip\"><b>38</b> 条公式</div>\n      <div class=\"chip\"><b>7</b> 步推理</div>\n      <div class=\"chip\"><b>3,621</b> 个验证姿态</div>\n      <div class=\"chip\">单位 mm · rad</div>\n    </div>\n    <div class=\"hero-meta\">\n      <div class=\"stat\"><b>2 × 3</b><span>力臂矩阵 R</span></div>\n      <div class=\"stat\"><b>24 mm</b><span>两轴最短偏置</span></div>\n      <div class=\"stat\"><b>6</b><span>组 α / β / γ</span></div>\n      <div class=\"stat\"><b>−22.05</b><span>mm · C2 对 roll</span></div>\n    </div>\n  </div>\n  <div class=\"scroll-hint\"><span>向下滚动</span><i></i></div>\n</header>\n\n<main>\n<!-- 01 stage -->\n<section id=\"stage\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">01 / 沙盘</span><h2>先动手：这是一个活的二轴腕</h2></div>\n    <p class=\"lead reveal\">拖动滑块，三根绳会实时变形。右侧同时用两条完全独立的路线算绳长：<b>几何真值</b>（P1→P8 逐段量）和<b>闭式公式</b>（c + s<sub>r</sub> + s<sub>p</sub>）。它们必须相等——这就是整份推导的第一个证据。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"stage reveal\">\n      <div class=\"viewport\">\n        <canvas id=\"scene\"></canvas>\n        <div class=\"vp-tag\">REAL GEOMETRY · P1–P8</div>\n        <div class=\"legend\">\n          <div><i style=\"background:#22d3ee\"></i>绳 C1</div>\n          <div><i style=\"background:#a78bfa\"></i>绳 C2</div>\n          <div><i style=\"background:#fbbf24\"></i>绳 C3</div>\n          <div style=\"opacity:.6\"><i style=\"background:#fff\"></i>导向点 / 轴线</div>\n        </div>\n        <div class=\"vp-hint\">拖动旋转视角 · 白点 ＝ 导向点 P1–P8</div>\n      </div>\n\n      <div class=\"panel\">\n        <div class=\"ctl-row\">\n          <label>roll θ<sub>r</sub></label>\n          <input id=\"sl-r\" type=\"range\" min=\"-25\" max=\"25\" step=\"0.5\" value=\"0\">\n          <output id=\"out-r\">0.0°</output>\n        </div>\n        <div class=\"ctl-row\">\n          <label>pitch θ<sub>p</sub></label>\n          <input id=\"sl-p\" type=\"range\" min=\"-25\" max=\"45\" step=\"0.5\" value=\"0\">\n          <output id=\"out-p\">0.0°</output>\n        </div>\n        <div class=\"btn-row\">\n          <button class=\"btn\" id=\"btn-play\">暂停扫掠</button>\n          <button class=\"btn ghost\" id=\"btn-zero\">回零位</button>\n        </div>\n\n        <div class=\"readout\">\n          <div class=\"ro-row head\"><span></span><span>几何真值 l</span><span>闭式 c+s<sub>r</sub>+s<sub>p</sub></span><span>Δ</span></div>\n          <div class=\"ro-row\" id=\"ro-0\"><span class=\"nm\" style=\"color:#22d3ee\">C1</span><span class=\"g\">—</span><span class=\"c\">—</span><span class=\"d\">—</span></div>\n          <div class=\"ro-row\" id=\"ro-1\"><span class=\"nm\" style=\"color:#a78bfa\">C2</span><span class=\"g\">—</span><span class=\"c\">—</span><span class=\"d\">—</span></div>\n          <div class=\"ro-row\" id=\"ro-2\"><span class=\"nm\" style=\"color:#fbbf24\">C3</span><span class=\"g\">—</span><span class=\"c\">—</span><span class=\"d\">—</span></div>\n        </div>\n\n        <div class=\"matrix\" id=\"mat\">\n          <div class=\"h\"></div><div class=\"h\">绳 C1</div><div class=\"h\">绳 C2</div><div class=\"h\">绳 C3</div>\n        </div>\n        <div class=\"tau\">\n          <div><span>roll 力矩</span><b id=\"tau-r\">—</b></div>\n          <div><span>pitch 力矩</span><b id=\"tau-p\">—</b></div>\n        </div>\n        <p class=\"cap\" style=\"margin-top:12px\">力矩按 f = (10, 10, 10) N 计算；R 单位 mm/rad，即每 1 N 产生约 1 mN·m。</p>\n      </div>\n    </div>\n  </div>\n</section>\n\n<!-- 02 virtual work -->\n<section id=\"work\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">02 / 第①步</span><h2>为什么\"绳长变化率\"就是力臂</h2></div>\n    <p class=\"lead reveal\">不用去找\"力到轴的垂直距离\"——绳子是折线，那个距离处处在变。只做一件事：让关节转一个极小角度，看绳被拉长多少。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"cols\">\n      <div class=\"reveal\" style=\"border:1px solid var(--line);border-radius:20px;background:rgba(10,16,30,.6);padding:10px\">\n        <canvas id=\"spool\" class=\"chart\" style=\"height:300px\"></canvas>\n        <div class=\"cap\" style=\"text-align:center\">转 dθ → 收线 dl = r·dθ，力矩 = f·r</div>\n      </div>\n      <div class=\"reveal\">\n        <div class=\"eqbox\">\n          <div class=\"eq\">τᵀdq = −fᵀdl</div>\n          <div class=\"eq\" style=\"margin-top:18px\">R = −(∂l/∂q)ᵀ</div>\n        </div>\n        <ul class=\"clean\">\n          <li><b>能量守恒</b>：关节做的功，等于绳被拉长吸收的功。任意 dq 都成立，所以逐项相等。</li>\n          <li><b>半径即力臂</b>：绳绕在半径 r 的轴上，转 1 rad 收线 r——这正是\"每弧度能收多少绳\"。</li>\n          <li><b>符号是物理</b>：正转使绳变长 ⇒ 张力阻碍正转 ⇒ 元素为负。它是带符号的量，不是距离。</li>\n        </ul>\n      </div>\n    </div>\n  </div>\n</section>\n\n<!-- 03 decoupling -->\n<section id=\"decouple\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">03 / 第②③步</span><h2>三根绳，五段不变，两段在动</h2></div>\n    <p class=\"lead reveal\">P1–P4 在 base，P5–P6 在 roll_link，P7–P8 在 palm。同一刚体上的点距离恒定，所以只有 P4–P5（跨 roll）和 P6–P7（跨 pitch）会变长。再用一条性质：正交矩阵不改变长度。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"cols\">\n      <div class=\"reveal\">\n        <div class=\"eqbox\">\n          <div class=\"eq\">l<sub>i</sub> = c<sub>i</sub> + s<sub>ri</sub>(θ<sub>r</sub>) + s<sub>pi</sub>(θ<sub>p</sub>)</div>\n        </div>\n        <ul class=\"clean\">\n          <li><b>c<sub>i</sub> 是常数</b>：五段固定长度之和（C2 为 61.259637 mm），求导后为零，算力臂时根本用不上。</li>\n          <li><b>解耦的来历</b>：P6–P7 的差向量 = Q<sub>r</sub>·（只含 θ<sub>p</sub> 的向量），正交矩阵把模长保住，roll 被消掉。</li>\n          <li><b>但这不是通性</b>：加一根 base 直连 palm 的绳，交叉二阶导立刻从 ≈0 跳到 1.367 mm/rad²。</li>\n        </ul>\n      </div>\n      <div class=\"reveal\">\n        <div class=\"card\" style=\"padding:14px\">\n          <canvas id=\"chart-decouple\" class=\"chart\"></canvas>\n        </div>\n        <p class=\"cap\">同一段绳（C2 的 pitch 段）在 θ<sub>r</sub> = 0° / 10° / 20° 下逐点测量：三条曲线完全重合。这就是\"解耦\"的可视证据。</p>\n      </div>\n    </div>\n  </div>\n</section>\n\n<!-- 04 alpha beta gamma -->\n<section id=\"abc\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">04 / 第④步</span><h2>α、β、γ 不是拟合参数，是三个几何投影</h2></div>\n    <p class=\"lead reveal\">把固定端、动端相对轴原点记成 u、v，动端随角度转：s = ‖Qv − u‖。平方展开，再用 Rodrigues 把旋转写成 cos、sin 两项，就自然只剩三个系数。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"cols\">\n      <div class=\"reveal\">\n        <div class=\"eqbox\" style=\"margin-top:0\">\n          <div class=\"eq\">s(θ) = √<span style=\"border-top:1.5px solid rgba(233,238,251,.75);padding:0 .2em\">α + βcosθ + γsinθ</span></div>\n        </div>\n        <div class=\"card\" style=\"margin-top:16px\">\n          <div class=\"eq\" style=\"justify-content:flex-start;font-size:17px;gap:.6em\">\n            <span>α = ‖u‖²+‖v‖²−2(a·u)(a·v)</span>\n          </div>\n          <div class=\"eq\" style=\"justify-content:flex-start;font-size:17px;margin-top:8px\">β = −2[u·v − (a·u)(a·v)]</div>\n          <div class=\"eq\" style=\"justify-content:flex-start;font-size:17px;margin-top:8px\">γ = −2u·(a×v)</div>\n        </div>\n        <p style=\"font-size:14px\">把 u、v 拆成\"沿轴 / 垂直轴\"两部分：绕轴旋转只改变垂直分量的夹角，所以长度必然是一条余弦波。γ 里的叉乘，就是垂直平面内的<b>有向面积</b>。</p>\n      </div>\n      <div class=\"reveal\">\n        <div class=\"card\" style=\"padding:14px\">\n          <canvas id=\"chart-s\" class=\"chart\"></canvas>\n        </div>\n        <p class=\"cap\" id=\"cap-s\">曲线下方：α 决定平均长度，β、γ 决定这条波的相位与幅度。拖动上面的滑块，圆点会沿着曲线走。</p>\n        <div class=\"eqbox\" style=\"padding:16px;margin-top:14px\">\n          <div class=\"eq\" style=\"font-size:19px\">s² = α + ρ cos(θ − φ) ,&nbsp; ρ = √(β²+γ²)</div>\n        </div>\n      </div>\n    </div>\n  </div>\n</section>\n\n<!-- 05 arm -->\n<section id=\"arm\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">05 / 第⑤步</span><h2>求一次导，力臂就落在纸上</h2></div>\n    <p class=\"lead reveal\">因为 s = √D，求导只剩一步。力臂 r = −ds/dθ，负号来自物理约定：张力阻碍正转。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"cols\">\n      <div class=\"reveal\">\n        <div class=\"card\" style=\"padding:14px\">\n          <canvas id=\"chart-r\" class=\"chart\"></canvas>\n        </div>\n        <p class=\"cap\">r(θ) 在 θ = φ（绳最长处）穿过零：极值点处长度变化率为零，力臂自然为零。</p>\n      </div>\n      <div class=\"reveal\">\n        <div class=\"eqbox\">\n          <div class=\"eq\">\n            r(θ) =\n            <span class=\"frac\"><span class=\"num\">β sinθ − γ cosθ</span><span class=\"den\">2√D</span></span>\n            =\n            <span class=\"frac\"><span class=\"num\">ρ sin(θ − φ)</span><span class=\"den\">2s</span></span>\n          </div>\n        </div>\n        <ul class=\"clean\">\n          <li><b>分母 2s</b>：绳越长，转 1 rad 收线的比例越小，力臂越小。</li>\n          <li><b>零位读数</b>：r(0) = −γ / (2√(α+β))，三个系数直接给出答案。</li>\n          <li><b>组装</b>：每根绳对每个关节各用一组系数，拼起来就是 2×3 的 R。</li>\n        </ul>\n      </div>\n    </div>\n  </div>\n</section>\n\n<!-- 06 hand calc -->\n<section id=\"calc\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">06 / 手算</span><h2>拿计算器，把 C2 的 roll 段验一遍</h2></div>\n    <p class=\"lead reveal\">这一组数就是 PDF 第 7 节的实例：A = P04 ≈ (−27, −16, 5)，B<sub>0</sub> = P05 ≈ (−32.5, −12, 18)，轴 o = (0,0,0)，a = (0,1,0)。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"grid3 reveal\">\n      <div class=\"formula\">\n        <div class=\"t\">① 求 α</div>\n        <div class=\"f mono\" style=\"font-size:14px;line-height:1.9\">\n          ‖u‖² = 729+256+25 = 1010<br>\n          ‖v‖² = 1056.25+144+324 = 1524.25<br>\n          a·u = −16 ， a·v = −12<br>\n          α = 2534.25 − 2(192) = <b style=\"color:#8ef0ff\">2150.25</b>\n        </div>\n      </div>\n      <div class=\"formula\">\n        <div class=\"t\">② 求 β</div>\n        <div class=\"f mono\" style=\"font-size:14px;line-height:1.9\">\n          u·v = 877.5+192+90 = 1159.5<br>\n          β = −2[1159.5 − 192]<br>\n          &nbsp;&nbsp; = <b style=\"color:#8ef0ff\">−1935</b>\n        </div>\n      </div>\n      <div class=\"formula\">\n        <div class=\"t\">③ 求 γ</div>\n        <div class=\"f mono\" style=\"font-size:14px;line-height:1.9\">\n          a×v = (18, 0, 32.5)<br>\n          u·(a×v) = −486 + 162.5 = −323.5<br>\n          γ = −2(−323.5) = <b style=\"color:#8ef0ff\">647</b>\n        </div>\n      </div>\n    </div>\n\n    <div class=\"card reveal\" style=\"margin-top:14px\">\n      <div class=\"eq\" style=\"font-size:19px\">D(0) = 2150.25 − 1935 = 215.25 mm²&nbsp;&nbsp;→&nbsp;&nbsp;s(0) = √215.25 = 14.671 mm</div>\n      <div class=\"eq\" style=\"margin-top:16px\">r(0) = <span class=\"frac\"><span class=\"num\">−647</span><span class=\"den\">2 × 14.671</span></span> = <b style=\"color:#fbbf24\">−22.0497 mm</b></div>\n      <p style=\"font-size:13.5px;margin-top:14px\">负号的意思：零位拉紧 C2，给 roll 一个反向力矩。数值上就是\"每 1 N 张力约 22 mN·m\"。</p>\n    </div>\n  </div>\n</section>\n\n<!-- 07 verification -->\n<section id=\"verify\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">07 / 验证</span><h2>凭什么相信它没算错</h2></div>\n    <p class=\"lead reveal\">作者没有只说\"我觉得对\"，而是用几条互不依赖的路线对撞：CAD 有限差分、把同一差分模板作用在解析长度上、直接跨关节取矩、灵敏度差分。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"counters reveal\">\n      <div class=\"counter\"><b data-count=\"3621\">3,621</b><span>个 0.2° 姿态逐一比对</span></div>\n      <div class=\"counter\"><b data-count=\"0.032668\" data-dec=\"6\">0.032668</b><span>mm · 差分与解析最大差</span></div>\n      <div class=\"counter\"><b data-count=\"1.5e-9\" data-sci=\"1\">1.5e-9</b><span>mm · 同模板自洽残差</span></div>\n      <div class=\"counter\"><b data-count=\"1.4e-12\" data-sci=\"1\">1.4e-12</b><span>mm · 独立取矩路线差</span></div>\n    </div>\n\n    <div class=\"bars reveal\" id=\"bars\">\n      <div class=\"bar-row\"><span>解析 vs CAD 0.2° 差分</span><div class=\"track\"><div class=\"fill\" data-w=\"100\" style=\"width:100%\"></div></div><span class=\"v\">0.0327 mm</span></div>\n      <div class=\"bar-row\"><span>同差分模板作用于解析长度</span><div class=\"track\"><div class=\"fill\" data-w=\"57\" style=\"width:57%\"></div></div><span class=\"v\">1.5e-9 mm</span></div>\n      <div class=\"bar-row\"><span>25 条边界原始长度</span><div class=\"track\"><div class=\"fill\" data-w=\"47\" style=\"width:47%\"></div></div><span class=\"v\">2.7e-11 mm</span></div>\n      <div class=\"bar-row\"><span>解析 vs 独立静力学取矩</span><div class=\"track\"><div class=\"fill\" data-w=\"39\" style=\"width:39%\"></div></div><span class=\"v\">1.4e-12 mm</span></div>\n      <div class=\"bar-row\"><span>相位参数化互算残差</span><div class=\"track\"><div class=\"fill\" data-w=\"2\" style=\"width:2%\"></div></div><span class=\"v\">5e-19 m²</span></div>\n    </div>\n\n    <div class=\"card reveal\" style=\"margin-top:22px\">\n      <h3>最容易误读的一行</h3>\n      <p>0.032668 mm <b>不是模型误差</b>，而是\"用 0.2° 大步伐做差分\"的截断误差。证据是第二根条：同一套差分模板作用在解析长度上，差只剩 1.5e-9 mm。这也是为什么 PDF 专门辟谣\"真机精度 ≤ 0.0327 mm\"。</p>\n    </div>\n  </div>\n</section>\n\n<!-- 08 limits -->\n<section id=\"limits\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">08 / 边界</span><h2>它不能承诺什么</h2></div>\n    <p class=\"lead reveal\">整套公式建立在四个假设上。越出这些假设，公式依旧能算出数，但那些数不再代表真机。</p>\n    <div class=\"divider\"></div>\n\n    <div class=\"grid3 reveal\">\n      <div class=\"card\"><h3>刚体</h3><p>零件不变形，点相对零件固定。真实瓷环上的滑动接触不在此列。</p></div>\n      <div class=\"card\"><h3>无摩擦 · 同绳同张力</h3><p>导向点处摩擦为零，同一根绳各段张力相同；有摩擦时\"三根单一张力\"的物理解释要改。</p></div>\n      <div class=\"card\"><h3>固定中心折线</h3><p>绳按相邻点中心直线连接，接触拓扑不变。真实绕环、绳伸长、回差、卷绕半径都不在模型内。</p></div>\n    </div>\n\n    <div class=\"grid3 reveal\" style=\"margin-top:14px\">\n      <div class=\"card\"><h3 style=\"color:#fbbf24\">短段区</h3><p>C1 的 pitch 段在 −25° 只有 3.9 mm，梯度约 15.7 mm/mm。这里力臂误差被放大，必须单独标定。</p></div>\n      <div class=\"card\"><h3 style=\"color:#fbbf24\">满秩 ≠ 可实现</h3><p>3,621 个姿态里有 1,664 个不存在全正预紧解。矩阵满秩，不代表任意力矩都能靠正张力做出来。</p></div>\n      <div class=\"card\"><h3 style=\"color:#fbbf24\">零位不可辨识</h3><p>(β, γ, δ) 只含两个可观测量。没有外部机械基准，δ 无法单独定出；只测 Δl 时 c<sub>i</sub> 也不可辨识。</p></div>\n    </div>\n  </div>\n</section>\n\n<!-- 09 cheat sheet -->\n<section id=\"cheat\">\n  <div class=\"wrap\">\n    <div class=\"sec-head reveal\"><span class=\"sec-num\">09 / 公式卡</span><h2>一张纸带走</h2></div>\n    <div class=\"divider\"></div>\n    <div class=\"grid3 reveal\">\n      <div class=\"formula\"><div class=\"t\">总纲</div><div class=\"f\">R = −(∂l/∂q)ᵀ</div><div class=\"n\">τ = R·f；行 = roll / pitch，列 = C1 / C2 / C3。</div></div>\n      <div class=\"formula\"><div class=\"t\">解耦</div><div class=\"f\">l<sub>i</sub> = c<sub>i</sub> + s<sub>ri</sub> + s<sub>pi</sub></div><div class=\"n\">只对当前\"相邻刚体\"绳路成立，改绳路就失效。</div></div>\n      <div class=\"formula\"><div class=\"t\">单段</div><div class=\"f\">s = √(α+βcosθ+γsinθ)</div><div class=\"n\">α / β / γ 由零位坐标算出，单位长度²。</div></div>\n      <div class=\"formula\"><div class=\"t\">力臂</div><div class=\"f\">r = (βsinθ−γcosθ)/(2√D)</div><div class=\"n\">θ 用 rad；结果 m/rad，数值即等效力臂。</div></div>\n      <div class=\"formula\"><div class=\"t\">装配</div><div class=\"f\">R<sub>ri</sub> = r(θ<sub>r</sub>; α,β,γ)<sub>i</sub></div><div class=\"n\">六组系数各算一次，c<sub>i</sub> 不进入力臂。</div></div>\n      <div class=\"formula\"><div class=\"t\">门限</div><div class=\"f\">s<sub>guard</sub> ≥ max(s<sub>num</sub>, 2ε<sub>d</sub>/η<sub>max</sub>)</div><div class=\"n\">不满足 ⇒ INVALID_FOR_CONTROL，不能静默输出。</div></div>\n    </div>\n\n    <div class=\"card reveal\" style=\"margin-top:16px\">\n      <h3>小白最容易踩的五个坑</h3>\n      <p>① 角度混用度与弧度（差 57.3 倍）；② 把带符号力臂当成距离；③ m 与 mm 混用；④ 轴与点不在同一坐标系（转置用错差 183.85 mm）；⑤ 以为\"算得出来就能用\"——D&gt;0 只说明数学有效。</p>\n    </div>\n  </div>\n</section>\n</main>\n\n<footer>\n  <div class=\"wrap\">\n    <div>数据与结论来源：<span class=\"mono\">绳驱二轴腕部_解析公式.pdf</span>（2026-10-22 / v2.0）、复核数据 <span class=\"mono\">points_zero.csv</span>、<span class=\"mono\">segment_parameters.csv</span>、<span class=\"mono\">04_独立核对报告</span>。</div>\n    <div class=\"src\">\n      <span>几何：P1–P8 真实零位坐标（mm）</span>\n      <span>公式：与 PDF 编号 (1)–(27) 一致</span>\n      <span>页面：交互沙盘 / 6 张图 / 1 段扫掠动画</span>\n    </div>\n  </div>\n</footer>\n\n<script>\n(function(){\n  'use strict';\n\n  /* ================= 基础向量 ================= */\n  var DEG = Math.PI/180;\n  var YR = [0,1,0], XP = [1,0,0], OP = [0,0,24];\n\n  function sub(a,b){ return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }\n  function add(a,b){ return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]; }\n  function dot(a,b){ return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }\n  function cross(a,b){ return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }\n  function len(a){ return Math.sqrt(dot(a,a)); }\n\n  /* 绕过原点的单位轴旋转（Rodrigues） */\n  function rotAxis(p, k, th){\n    var c = Math.cos(th), s = Math.sin(th), kv = cross(k,p), kd = dot(k,p);\n    return [\n      p[0]*c + kv[0]*s + k[0]*kd*(1-c),\n      p[1]*c + kv[1]*s + k[1]*kd*(1-c),\n      p[2]*c + kv[2]*s + k[2]*kd*(1-c)\n    ];\n  }\n  function rotAbout(p, o, k, th){ return add(o, rotAxis(sub(p,o), k, th)); }\n\n  /* ================= 真实几何数据（零位，mm） ================= */\n  var CABLES = [\n    { name:'C1', color:'#22d3ee', c:0,\n      rl:{a:364.5, b:-182.5, g:7.0},\n      pt:{a:7263.47364742, b:-6537.66603142, g:3130.77161942},\n      pts:[[27,85,-35],[27,85,-27],[0.5,55,-5],[0.5,55,5],\n           [2.5,58,18],[2.5,58,30],[2.3215,53,56.4722],[2.3215,53,61.4722]] },\n    { name:'C2', color:'#a78bfa', c:0,\n      rl:{a:2150.25, b:-1935, g:647},\n      pt:{a:820.33042151, b:-564.0, g:-378.0},\n      pts:[[-23,-20,-35],[-23,-20,-27],[-27,-16,-5],[-27,-16,5],\n           [-32.5,-12,18],[-32.5,-12,30],[-32.2164,-12.5,46],[-32.2164,-15.5,54]] },\n    { name:'C3', color:'#fbbf24', c:0,\n      rl:{a:2500.25, b:-2205, g:-597},\n      pt:{a:859.73346622, b:-564.0, g:-378.0},\n      pts:[[23,-20,-35],[23,-20,-27],[27,-16,-5],[27,-16,5],\n           [37.5,-12,18],[37.5,-12,30],[43.7836,-12.5,46],[43.7836,-15.5,54]] }\n  ];\n\n  /* α/β/γ 直接由零位坐标反算（式 19–21）：页面上的数字不是抄来的 */\n  function coeffs(u, v, a){\n    var au = dot(a,u), av = dot(a,v);\n    return {\n      a: dot(u,u) + dot(v,v) - 2*au*av,\n      b: -2*(dot(u,v) - au*av),\n      g: -2*dot(u, cross(a,v))\n    };\n  }\n  CABLES.forEach(function(cab){\n    cab.rl = coeffs(cab.pts[3], cab.pts[4], YR);                   /* P04、P05 绕 roll 轴 */\n    cab.pt = coeffs(sub(cab.pts[5], OP), sub(cab.pts[6], OP), XP); /* P06、P07 绕 pitch 轴 */\n  });\n\n  /* 各绳的世界坐标（base 不动；roll_link 随 θr；palm 先随 θp 再整体随 θr） */\n  function worldPts(cab, tr, tp){\n    var out = [], i, p;\n    for(i = 0; i < 8; i++){\n      p = cab.pts[i];\n      if(i < 4){\n        out.push([p[0], p[1], p[2]]);\n      } else if(i < 6){\n        out.push(rotAbout(p, [0,0,0], YR, tr));\n      } else {\n        var q = add(OP, rotAxis(sub(p, OP), XP, tp));\n        out.push(rotAbout(q, [0,0,0], YR, tr));\n      }\n    }\n    return out;\n  }\n\n  function geoLen(cab, tr, tp){\n    var w = worldPts(cab, tr, tp), L = 0;\n    for(var i = 1; i < 8; i++) L += len(sub(w[i], w[i-1]));\n    return L;\n  }\n  function closedLen(cab, tr, tp){\n    var D1 = cab.rl.a + cab.rl.b*Math.cos(tr) + cab.rl.g*Math.sin(tr);\n    var D2 = cab.pt.a + cab.pt.b*Math.cos(tp) + cab.pt.g*Math.sin(tp);\n    return cab.c + Math.sqrt(Math.max(D1,0)) + Math.sqrt(Math.max(D2,0));\n  }\n  function arm(th, k){\n    var D = k.a + k.b*Math.cos(th) + k.g*Math.sin(th);\n    return (k.b*Math.sin(th) - k.g*Math.cos(th)) / (2*Math.sqrt(Math.max(D,1e-9)));\n  }\n  /* 常数段长度：P1P2 + P2P3 + P3P4 + P5P6 + P7P8（零位） */\n  CABLES.forEach(function(cab){\n    var s = 0, i;\n    for(i = 1; i < 8; i++){\n      if(i === 4 || i === 6) continue;   /* 跳过跨关节段 P4-P5、P6-P7 */\n      s += len(sub(cab.pts[i], cab.pts[i-1]));\n    }\n    cab.c = s;\n  });\n\n  /* ================= 场景渲染 ================= */\n  var canvas = document.getElementById('scene');\n  var ctx = canvas.getContext('2d');\n  var scene = {\n    w:0, h:0, dpr:1,\n    tr:0, tp:0,\n    azBase:0.62, elBase:0.30,\n    azUser:0, elUser:0,\n    t:0, sweep:true,\n    scale:1, center:[0,0,0], offx:0, offy:0,\n    dragging:false, lastX:0, lastY:0\n  };\n\n  function fitScene(){\n    var trs = [-20,0,20], tps = [-18,0,20,40];\n    var min = [1e9,1e9,1e9], max = [-1e9,-1e9,-1e9];\n    function acc(p){\n      for(var i=0;i<3;i++){ if(p[i]<min[i]) min[i]=p[i]; if(p[i]>max[i]) max[i]=p[i]; }\n    }\n    trs.forEach(function(a){\n      tps.forEach(function(b){\n        CABLES.forEach(function(cab){\n          worldPts(cab, a*DEG, b*DEG).forEach(acc);\n        });\n      });\n    });\n    /* 只按机构本身取景，轴线允许出画 */\n    scene.center = [(min[0]+max[0])/2, (min[1]+max[1])/2, (min[2]+max[2])/2];\n    var span = Math.max(max[0]-min[0], max[1]-min[1], max[2]-min[2]);\n    scene.span = span;\n    scene.min = min; scene.max = max;\n  }\n\n  function basis(){\n    var az = scene.azBase + 0.18*Math.sin(scene.t*0.22) + scene.azUser;\n    var el = Math.max(0.06, Math.min(1.15, scene.elBase + scene.elUser));\n    var ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);\n    var dir = [ce*ca, ce*sa, se];\n    var right = [-sa, ca, 0];\n    var up = cross(dir, right);\n    return { dir:dir, right:right, up:up };\n  }\n\n  function resizeScene(){\n    var r = canvas.getBoundingClientRect();\n    scene.dpr = Math.min(window.devicePixelRatio || 1, 2);\n    scene.w = r.width; scene.h = r.height;\n    canvas.width = Math.round(r.width * scene.dpr);\n    canvas.height = Math.round(r.height * scene.dpr);\n    ctx.setTransform(scene.dpr, 0, 0, scene.dpr, 0, 0);\n    /* 用当前方位估计缩放：把包围盒 8 个角投影后塞进画布 */\n    var b = basis();\n    var minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;\n    var mn = scene.min, mx = scene.max;\n    for(var i = 0; i < 8; i++){\n      var p = [i&1?mx[0]:mn[0], i&2?mx[1]:mn[1], i&4?mx[2]:mn[2]];\n      var d = sub(p, scene.center);\n      var x = dot(d, b.right), y = dot(d, b.up);\n      if(x<minx)minx=x; if(x>maxx)maxx=x; if(y<miny)miny=y; if(y>maxy)maxy=y;\n    }\n    var sx = (scene.w*0.90) / Math.max(maxx-minx, 1e-6);\n    var sy = (scene.h*0.88) / Math.max(maxy-miny, 1e-6);\n    scene.scale = Math.min(sx, sy);\n  }\n\n  function project(p, b){\n    var d = sub(p, scene.center);\n    return [ scene.w/2 + scene.offx + dot(d, b.right)*scene.scale,\n             scene.h/2 + scene.offy - dot(d, b.up)*scene.scale ];\n  }\n\n  /* 让零位机构落在画布中央：按当前视角重算屏幕偏移 */\n  function updateOffset(b){\n    var mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9;\n    CABLES.forEach(function(c){\n      worldPts(c, 0, 0).forEach(function(p){\n        var d = sub(p, scene.center);\n        var x = dot(d, b.right), y = dot(d, b.up);\n        if(x < mnx) mnx = x; if(x > mxx) mxx = x;\n        if(y < mny) mny = y; if(y > mxy) mxy = y;\n      });\n    });\n    scene.offx = -((mnx + mxx)/2)*scene.scale;\n    scene.offy = ((mny + mxy)/2)*scene.scale;\n  }\n\n  function hull2d(pts){\n    if(pts.length < 3) return pts.slice();\n    var s = pts.slice().sort(function(a,b){ return a[0]-b[0] || a[1]-b[1]; });\n    var lower = [], upper = [], i;\n    for(i = 0; i < s.length; i++){\n      while(lower.length >= 2 && cross2(lower[lower.length-2], lower[lower.length-1], s[i]) <= 0) lower.pop();\n      lower.push(s[i]);\n    }\n    for(i = s.length-1; i >= 0; i--){\n      while(upper.length >= 2 && cross2(upper[upper.length-2], upper[upper.length-1], s[i]) <= 0) upper.pop();\n      upper.push(s[i]);\n    }\n    lower.pop(); upper.pop();\n    return lower.concat(upper);\n  }\n  function cross2(o,a,b){ return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0]); }\n\n  function line(p1, p2, color, width, dash){\n    ctx.save();\n    ctx.strokeStyle = color;\n    ctx.lineWidth = width || 1;\n    if(dash) ctx.setLineDash(dash);\n    ctx.beginPath();\n    ctx.moveTo(p1[0], p1[1]);\n    ctx.lineTo(p2[0], p2[1]);\n    ctx.stroke();\n    ctx.restore();\n  }\n\n  function label(text, x, y, color, size){\n    ctx.save();\n    ctx.fillStyle = color || 'rgba(190,205,235,.8)';\n    ctx.font = (size || 11) + 'px \"JetBrains Mono\", Consolas, monospace';\n    ctx.fillText(text, x, y);\n    ctx.restore();\n  }\n\n  function arrowHead(from, to, color){\n    var dx = to[0]-from[0], dy = to[1]-from[1];\n    var a = Math.atan2(dy, dx), size = 7;\n    ctx.save();\n    ctx.fillStyle = color;\n    ctx.beginPath();\n    ctx.moveTo(to[0], to[1]);\n    ctx.lineTo(to[0]-size*Math.cos(a-0.4), to[1]-size*Math.sin(a-0.4));\n    ctx.lineTo(to[0]-size*Math.cos(a+0.4), to[1]-size*Math.sin(a+0.4));\n    ctx.closePath();\n    ctx.fill();\n    ctx.restore();\n  }\n\n  function drawAxes(b){\n    var o = project([0,0,0], b);\n    var ry = project([0,96,0], b);\n    var py = project([54,0,24], b);\n    var px0 = project([-40,0,24], b);\n\n    line(px0, py, 'rgba(120,150,210,.28)', 1, [4,6]);\n    line(o, ry, 'rgba(120,150,210,.28)', 1, [4,6]);\n    arrowHead(px0, py, 'rgba(160,185,235,.55)');\n    arrowHead(o, ry, 'rgba(160,185,235,.55)');\n\n    label('pitch 轴 +X', py[0]+8, py[1]+4, 'rgba(170,195,240,.75)');\n    label('roll 轴 +Y', ry[0]+8, ry[1]+12, 'rgba(170,195,240,.75)');\n\n    /* 24 mm 偏置 */\n    var p0 = project([0,0,0], b);\n    var p24 = project([0,0,24], b);\n    line(p0, p24, 'rgba(251,191,36,.55)', 1.5, [3,4]);\n    var mid = [(p0[0]+p24[0])/2, (p0[1]+p24[1])/2];\n    ctx.save();\n    ctx.fillStyle = 'rgba(251,191,36,.85)';\n    ctx.font = '11px \"JetBrains Mono\", Consolas, monospace';\n    ctx.fillText('24 mm', mid[0]+8, mid[1]+4);\n    ctx.restore();\n\n    /* 原点 */\n    ctx.save();\n    ctx.fillStyle = 'rgba(255,255,255,.85)';\n    ctx.beginPath(); ctx.arc(o[0], o[1], 2.6, 0, Math.PI*2); ctx.fill();\n    ctx.restore();\n  }\n\n  function drawBodies(b){\n    var worlds = CABLES.map(function(cab){ return worldPts(cab, scene.tr, scene.tp); });\n\n    /* base：三块侧板的整体轮廓（12 个锚点）+ 各自的边 */\n    var baseAll2 = [];\n    worlds.forEach(function(w){\n      for(var i = 0; i < 4; i++) baseAll2.push(project(w[i], b));\n    });\n    var bh = hull2d(baseAll2);\n    ctx.save();\n    ctx.fillStyle = 'rgba(120,160,240,.05)';\n    ctx.strokeStyle = 'rgba(140,175,240,.20)';\n    ctx.lineWidth = 1;\n    ctx.beginPath();\n    bh.forEach(function(p,i){ if(i) ctx.lineTo(p[0],p[1]); else ctx.moveTo(p[0],p[1]); });\n    ctx.closePath(); ctx.fill(); ctx.stroke();\n    ctx.restore();\n\n    worlds.forEach(function(w){\n      var h = hull2d(w.slice(0,4).map(function(p){ return project(p,b); }));\n      ctx.save();\n      ctx.fillStyle = 'rgba(140,175,255,.06)';\n      ctx.strokeStyle = 'rgba(150,185,255,.26)';\n      ctx.lineWidth = 1;\n      ctx.beginPath();\n      h.forEach(function(p,i){ if(i) ctx.lineTo(p[0],p[1]); else ctx.moveTo(p[0],p[1]); });\n      ctx.closePath();\n      ctx.fill(); ctx.stroke();\n      ctx.restore();\n    });\n\n    /* palm：六个锚点合成一块掌板 */\n    var palm2 = [];\n    worlds.forEach(function(w){ palm2.push(project(w[6],b), project(w[7],b)); });\n    var ph = hull2d(palm2);\n    ctx.save();\n    ctx.fillStyle = 'rgba(167,139,250,.075)';\n    ctx.strokeStyle = 'rgba(190,170,255,.32)';\n    ctx.lineWidth = 1;\n    ctx.beginPath();\n    ph.forEach(function(p,i){ if(i) ctx.lineTo(p[0],p[1]); else ctx.moveTo(p[0],p[1]); });\n    ctx.closePath(); ctx.fill(); ctx.stroke();\n    ctx.restore();\n\n    /* roll_link：三根短杆 */\n    worlds.forEach(function(w){\n      var a = project(w[4],b), c = project(w[5],b);\n      ctx.save();\n      ctx.strokeStyle = 'rgba(170,200,255,.30)';\n      ctx.lineWidth = 6; ctx.lineCap = 'round';\n      ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(c[0],c[1]); ctx.stroke();\n      ctx.strokeStyle = 'rgba(225,238,255,.55)'; ctx.lineWidth = 1;\n      ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(c[0],c[1]); ctx.stroke();\n      ctx.restore();\n    });\n\n    /* 刚体名字 */\n    var baseAll = [], rollAll = [];\n    worlds.forEach(function(w){\n      for(var i=0;i<4;i++) baseAll.push(project(w[i],b));\n      rollAll.push(project(w[4],b), project(w[5],b));\n    });\n    tagHull(baseAll, 'base', 18);\n    tagHull(palm2, 'palm', -16);\n    tagHull(rollAll, 'roll_link', -10);\n  }\n\n  function tagHull(pts, text, dy){\n    if(!pts.length) return;\n    var x = 0, y = 0;\n    pts.forEach(function(p){ x += p[0]; y += p[1]; });\n    x /= pts.length; y /= pts.length;\n    ctx.save();\n    ctx.fillStyle = 'rgba(175,200,240,.62)';\n    ctx.font = '10px \"JetBrains Mono\", Consolas, monospace';\n    ctx.textAlign = 'center';\n    ctx.fillText(text, x, y + (dy || 0));\n    ctx.restore();\n  }\n\n  function drawRope(cab, b, t){\n    var w = worldPts(cab, scene.tr, scene.tp);\n    var p = w.map(function(q){ return project(q,b); });\n\n    /* 外发光 */\n    ctx.save();\n    ctx.lineJoin = 'round'; ctx.lineCap = 'round';\n    ctx.shadowColor = cab.color; ctx.shadowBlur = 16;\n    ctx.strokeStyle = cab.color; ctx.globalAlpha = 0.30; ctx.lineWidth = 7;\n    ctx.beginPath();\n    p.forEach(function(q,i){ if(i) ctx.lineTo(q[0],q[1]); else ctx.moveTo(q[0],q[1]); });\n    ctx.stroke();\n    ctx.restore();\n\n    /* 主体 */\n    ctx.save();\n    ctx.lineJoin = 'round'; ctx.lineCap = 'round';\n    ctx.strokeStyle = cab.color; ctx.globalAlpha = 0.95; ctx.lineWidth = 2.2;\n    ctx.beginPath();\n    p.forEach(function(q,i){ if(i) ctx.lineTo(q[0],q[1]); else ctx.moveTo(q[0],q[1]); });\n    ctx.stroke();\n    ctx.restore();\n\n    /* 流动虚线：表示\"张力沿绳传播\" */\n    ctx.save();\n    ctx.lineJoin = 'round'; ctx.lineCap = 'round';\n    ctx.setLineDash([2,10]);\n    ctx.lineDashOffset = -t*46;\n    ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = 1.6;\n    ctx.beginPath();\n    p.forEach(function(q,i){ if(i) ctx.lineTo(q[0],q[1]); else ctx.moveTo(q[0],q[1]); });\n    ctx.stroke();\n    ctx.restore();\n\n    /* 跨关节两段高亮 */\n    [[4,5],[6,7]].forEach(function(pair){\n      var i = pair[0], j = pair[1];\n      ctx.save();\n      ctx.lineCap = 'round';\n      ctx.strokeStyle = 'rgba(255,255,255,.9)';\n      ctx.lineWidth = 4.2;\n      ctx.globalAlpha = 0.5 + 0.5*Math.sin(t*3 + i);\n      ctx.beginPath();\n      ctx.moveTo(p[i][0], p[i][1]); ctx.lineTo(p[j][0], p[j][1]);\n      ctx.stroke();\n      ctx.restore();\n    });\n\n    /* 导向点 */\n    p.forEach(function(q){\n      ctx.save();\n      ctx.fillStyle = '#fff';\n      ctx.shadowColor = cab.color; ctx.shadowBlur = 10;\n      ctx.beginPath(); ctx.arc(q[0], q[1], 2.4, 0, Math.PI*2); ctx.fill();\n      ctx.restore();\n    });\n  }\n\n  function drawArcs(b){\n    var tr = scene.tr, tp = scene.tp;\n\n    /* roll 角弧：在 y=58 平面上绕 Y 轴 */\n    if(Math.abs(tr) > 0.02){\n      ctx.save();\n      ctx.strokeStyle = 'rgba(34,211,238,.55)'; ctx.lineWidth = 1.4;\n      ctx.beginPath();\n      for(var i = 0; i <= 40; i++){\n        var a = tr * i/40;\n        var q = project([22*Math.cos(a), 44, -22*Math.sin(a)], b);\n        if(i) ctx.lineTo(q[0],q[1]); else ctx.moveTo(q[0],q[1]);\n      }\n      ctx.stroke();\n      ctx.restore();\n      var tip = project([22*Math.cos(tr), 44, -22*Math.sin(tr)], b);\n      ctx.save();\n      ctx.fillStyle = 'rgba(34,211,238,.9)';\n      ctx.font = '600 12px \"JetBrains Mono\", Consolas, monospace';\n      ctx.fillText('θr', tip[0]+6, tip[1]-4);\n      ctx.restore();\n    }\n\n    /* pitch 角弧：在 x=0 平面上绕 X 轴 */\n    if(Math.abs(tp) > 0.02){\n      ctx.save();\n      ctx.strokeStyle = 'rgba(167,139,250,.55)'; ctx.lineWidth = 1.4;\n      ctx.beginPath();\n      for(var j = 0; j <= 40; j++){\n        var c = tp * j/40;\n        var q2 = project([0, 16*Math.cos(c), 24 + 16*Math.sin(c)], b);\n        if(j) ctx.lineTo(q2[0],q2[1]); else ctx.moveTo(q2[0],q2[1]);\n      }\n      ctx.stroke();\n      ctx.restore();\n      var tip2 = project([0, 16*Math.cos(tp), 24 + 16*Math.sin(tp)], b);\n      ctx.save();\n      ctx.fillStyle = 'rgba(167,139,250,.9)';\n      ctx.font = '600 12px \"JetBrains Mono\", Consolas, monospace';\n      ctx.fillText('θp', tip2[0]+6, tip2[1]-4);\n      ctx.restore();\n    }\n  }\n\n  function renderScene(){\n    var b = basis();\n    updateOffset(b);\n    ctx.clearRect(0, 0, scene.w, scene.h);\n\n    /* 背景光晕 */\n    var g = ctx.createRadialGradient(scene.w*0.5, scene.h*0.42, 10, scene.w*0.5, scene.h*0.42, Math.max(scene.w,scene.h)*0.7);\n    g.addColorStop(0, 'rgba(34,211,238,.07)');\n    g.addColorStop(1, 'rgba(0,0,0,0)');\n    ctx.fillStyle = g;\n    ctx.fillRect(0, 0, scene.w, scene.h);\n\n    drawFloor(b);\n    drawAxes(b);\n    drawBodies(b);\n    CABLES.forEach(function(cab){ drawRope(cab, b, scene.t); });\n    drawArcs(b);\n  }\n\n  /* 底部网格：给悬浮的机构一点空间参照 */\n  function drawFloor(b){\n    var z = -44, i;\n    ctx.save();\n    ctx.strokeStyle = 'rgba(120,160,230,.075)';\n    ctx.lineWidth = 1;\n    for(i = -45; i <= 45; i += 15){\n      var a = project([i, -30, z], b), c = project([i, 90, z], b);\n      ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(c[0],c[1]); ctx.stroke();\n    }\n    for(i = -30; i <= 90; i += 15){\n      var d = project([-45, i, z], b), e = project([45, i, z], b);\n      ctx.beginPath(); ctx.moveTo(d[0],d[1]); ctx.lineTo(e[0],e[1]); ctx.stroke();\n    }\n    ctx.restore();\n  }\n\n  /* ================= 读数面板 ================= */\n  var ro = [0,1,2].map(function(i){ return document.getElementById('ro-'+i); });\n  var mat = document.getElementById('mat');\n  var cells = [];\n  for(var r = 0; r < 2; r++){\n    var row = [];\n    /* 行标签 */\n    var lab = document.createElement('div');\n    lab.className = 'h';\n    lab.textContent = r === 0 ? 'roll' : 'pitch';\n    mat.appendChild(lab);\n    for(var c = 0; c < 3; c++){\n      var d = document.createElement('div');\n      d.className = 'cell';\n      d.textContent = '—';\n      mat.appendChild(d);\n      row.push(d);\n    }\n    cells.push(row);\n  }\n  var tauR = document.getElementById('tau-r'), tauP = document.getElementById('tau-p');\n\n  function fmt(x, n){ return (Math.abs(x) < 5e-4 ? 0 : x).toFixed(n); }\n\n  function updateReadout(){\n    var tr = scene.tr, tp = scene.tp, R = [[],[]], i;\n    for(i = 0; i < 3; i++){\n      var cab = CABLES[i];\n      var gl = geoLen(cab, tr, tp);\n      var cl = closedLen(cab, tr, tp);\n      ro[i].querySelector('.g').textContent = gl.toFixed(6);\n      ro[i].querySelector('.c').textContent = cl.toFixed(6);\n      ro[i].querySelector('.d').textContent = Math.abs(gl-cl).toExponential(1);\n      R[0][i] = arm(tr, cab.rl);\n      R[1][i] = arm(tp, cab.pt);\n    }\n    var maxAbs = 1;\n    for(var rr = 0; rr < 2; rr++) for(var cc = 0; cc < 3; cc++) maxAbs = Math.max(maxAbs, Math.abs(R[rr][cc]));\n    for(var r2 = 0; r2 < 2; r2++){\n      for(var c2 = 0; c2 < 3; c2++){\n        var v = R[r2][c2], el = cells[r2][c2];\n        el.textContent = fmt(v, 2);\n        el.className = 'cell ' + (v < 0 ? 'neg' : 'pos');\n        var a = Math.min(0.55, Math.abs(v)/maxAbs*0.5);\n        el.style.background = 'rgba(' + (v<0 ? '251,113,133,' : '34,211,238,') + a.toFixed(3) + ')';\n      }\n    }\n    var f = 10;\n    var tR = R[0][0]*f + R[0][1]*f + R[0][2]*f;\n    var tP = R[1][0]*f + R[1][1]*f + R[1][2]*f;\n    tauR.textContent = fmt(tR, 1) + ' mN·m';\n    tauP.textContent = fmt(tP, 1) + ' mN·m';\n  }\n\n  /* ================= 通用曲线图 ================= */\n  function setupCanvas(cv){\n    var r = cv.getBoundingClientRect();\n    var dpr = Math.min(window.devicePixelRatio || 1, 2);\n    var w = Math.max(1, Math.round(r.width*dpr));\n    var h = Math.max(1, Math.round(r.height*dpr));\n    if(cv.width !== w || cv.height !== h){ cv.width = w; cv.height = h; }\n    var c = cv.getContext('2d');\n    c.setTransform(dpr, 0, 0, dpr, 0, 0);\n    return { ctx:c, w:r.width, h:r.height };\n  }\n\n  function niceTicks(min, max, n){\n    var span = max-min, step = Math.pow(10, Math.floor(Math.log(span/n)/Math.LN10));\n    var err = span/n/step;\n    if(err >= 7.5) step *= 10; else if(err >= 3.5) step *= 5; else if(err >= 1.5) step *= 2;\n    var out = [], v = Math.ceil(min/step)*step;\n    while(v <= max + 1e-9){ out.push(v); v += step; }\n    return out;\n  }\n\n  function drawChart(cv, opt){\n    var c = setupCanvas(cv), x = c.ctx, w = c.w, h = c.h;\n    var pad = {l:46, r:14, t:16, b:30};\n    var x0 = pad.l, x1 = w-pad.r, y0 = pad.t, y1 = h-pad.b;\n    x.clearRect(0,0,w,h);\n\n    var xs = [], i, N = 160;\n    for(i = 0; i <= N; i++) xs.push(opt.xmin + (opt.xmax-opt.xmin)*i/N);\n    var ymin = 1e9, ymax = -1e9;\n    opt.curves.forEach(function(cv2){\n      xs.forEach(function(t){\n        var v = cv2.f(t);\n        if(isFinite(v)){ if(v<ymin)ymin=v; if(v>ymax)ymax=v; }\n      });\n    });\n    if(ymin === 1e9){ ymin = -1; ymax = 1; }\n    if(ymax-ymin < 1e-6){ ymax = ymin + 1; }\n    var padv = (ymax-ymin)*0.12;\n    ymin -= padv; ymax += padv;\n\n    var X = function(t){ return x0 + (t-opt.xmin)/(opt.xmax-opt.xmin)*(x1-x0); };\n    var Y = function(v){ return y1 - (v-ymin)/(ymax-ymin)*(y1-y0); };\n\n    x.strokeStyle = 'rgba(122,152,210,.13)';\n    x.lineWidth = 1;\n    x.font = '10px \"JetBrains Mono\", Consolas, monospace';\n    x.fillStyle = 'rgba(150,170,210,.55)';\n    var yt = niceTicks(ymin, ymax, 4);\n    yt.forEach(function(v){\n      var yy = Y(v);\n      x.beginPath(); x.moveTo(x0, yy); x.lineTo(x1, yy); x.stroke();\n      x.fillText(String(Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)), 6, yy+3);\n    });\n    var xt = niceTicks(opt.xmin/DEG, opt.xmax/DEG, 6);\n    xt.forEach(function(vd){\n      var xx = X(vd*DEG);\n      x.strokeStyle = 'rgba(122,152,210,.08)';\n      x.beginPath(); x.moveTo(xx, y0); x.lineTo(xx, y1); x.stroke();\n      x.fillStyle = 'rgba(150,170,210,.55)';\n      x.fillText(vd.toFixed(0) + '°', xx-8, h-10);\n    });\n\n    opt.curves.forEach(function(cv2){\n      x.save();\n      x.strokeStyle = cv2.color;\n      x.lineWidth = cv2.width || 2;\n      if(cv2.dash) x.setLineDash(cv2.dash);\n      x.shadowColor = cv2.color; x.shadowBlur = 10;\n      x.beginPath();\n      var started = false;\n      xs.forEach(function(t){\n        var v = cv2.f(t);\n        if(!isFinite(v)) return;\n        var px = X(t), py = Y(v);\n        if(!started){ x.moveTo(px,py); started = true; } else x.lineTo(px,py);\n      });\n      x.stroke();\n      x.restore();\n    });\n\n    if(typeof opt.markerX === 'number'){\n      var mx = X(opt.markerX);\n      x.save();\n      x.strokeStyle = 'rgba(255,255,255,.28)';\n      x.setLineDash([3,4]);\n      x.beginPath(); x.moveTo(mx, y0); x.lineTo(mx, y1); x.stroke();\n      x.restore();\n      opt.curves.forEach(function(cv2){\n        var v = cv2.f(opt.markerX);\n        if(!isFinite(v)) return;\n        var py = Y(v);\n        x.save();\n        x.fillStyle = '#fff';\n        x.shadowColor = cv2.color; x.shadowBlur = 12;\n        x.beginPath(); x.arc(mx, py, 4, 0, Math.PI*2); x.fill();\n        x.restore();\n        if(cv2.label){\n          x.save();\n          x.fillStyle = cv2.color;\n          x.font = '600 11px \"JetBrains Mono\", Consolas, monospace';\n          x.fillText(cv2.label(v), mx+8, py-8);\n          x.restore();\n        }\n      });\n    }\n    if(opt.xlabel){\n      x.save();\n      x.fillStyle = 'rgba(150,170,210,.6)';\n      x.font = '10px \"JetBrains Mono\", Consolas, monospace';\n      x.textAlign = 'right';\n      x.fillText(opt.xlabel, x1-2, y1-7);\n      x.restore();\n    }\n  }\n\n  var chartS = document.getElementById('chart-s');\n  var chartR = document.getElementById('chart-r');\n  var chartD = document.getElementById('chart-decouple');\n\n  var selected = 1; /* 默认 C2 */\n  function drawCharts(){\n    var cab = CABLES[selected];\n    var xmin = -25*DEG, xmax = 45*DEG;\n\n    drawChart(chartS, {\n      xmin: xmin, xmax: xmax, xlabel: 'θ (deg)',\n      curves: [{ f:function(t){ return Math.sqrt(Math.max(cab.pt.a + cab.pt.b*Math.cos(t) + cab.pt.g*Math.sin(t), 0)); }, color:cab.color }],\n      markerX: scene.tp,\n      markers: true\n    });\n\n    drawChart(chartR, {\n      xmin: xmin, xmax: xmax, xlabel: 'θ (deg)',\n      curves: [{ f:function(t){ return arm(t, cab.pt); }, color:'#fbbf24', label:function(v){ return v.toFixed(2)+' mm'; } }],\n      markerX: scene.tp\n    });\n\n    var dec = [-25,-5,0,20,45].map(function(d){ return d*DEG; });\n    drawChart(chartD, {\n      xmin: xmin, xmax: xmax, xlabel: 'θp (deg)',\n      curves: [\n        { f:function(t){ return segLen(cab, 0, t); }, color:'rgba(34,211,238,.95)' },\n        { f:function(t){ return segLen(cab, 10*DEG, t); }, color:'rgba(167,139,250,.9)', dash:[6,5] },\n        { f:function(t){ return segLen(cab, 20*DEG, t); }, color:'rgba(251,191,36,.85)', dash:[2,4] }\n      ],\n      markerX: scene.tp\n    });\n  }\n\n  /* 指定 θr 下 P6-P7 的实际长度（几何法，用来证明与 θr 无关） */\n  function segLen(cab, tr, tp){\n    var w = worldPts(cab, tr, tp);\n    return len(sub(w[6], w[5]));\n  }\n\n  /* ================= 卷筒演示 ================= */\n  var spool = document.getElementById('spool');\n  var spoolT = 0;\n  function drawSpool(){\n    var c = setupCanvas(spool), x = c.ctx, w = c.w, h = c.h;\n    x.clearRect(0,0,w,h);\n    var cx = w*0.40, cy = h*0.52, R = Math.min(w,h)*0.30;\n    var ang = 0.55 + 0.45*Math.sin(spoolT*0.9);\n\n    /* 轴 */\n    x.save();\n    x.strokeStyle = 'rgba(150,180,255,.25)';\n    x.setLineDash([4,6]);\n    x.beginPath(); x.moveTo(cx-R*1.5, cy); x.lineTo(cx+R*1.9, cy); x.stroke();\n    x.restore();\n\n    /* 圆盘 */\n    var g = x.createRadialGradient(cx, cy, R*0.2, cx, cy, R*1.25);\n    g.addColorStop(0, 'rgba(34,211,238,.20)');\n    g.addColorStop(1, 'rgba(34,211,238,0)');\n    x.fillStyle = g;\n    x.beginPath(); x.arc(cx, cy, R*1.25, 0, Math.PI*2); x.fill();\n\n    x.save();\n    x.strokeStyle = 'rgba(180,215,255,.75)';\n    x.lineWidth = 1.6;\n    x.beginPath(); x.arc(cx, cy, R, 0, Math.PI*2); x.stroke();\n    x.strokeStyle = 'rgba(180,215,255,.25)';\n    x.beginPath(); x.moveTo(cx, cy); x.lineTo(cx+R*Math.cos(ang), cy-R*Math.sin(ang)); x.stroke();\n    x.restore();\n\n    /* 半径标注 */\n    x.save();\n    x.fillStyle = 'rgba(34,211,238,.95)';\n    x.font = '600 12px \"JetBrains Mono\", Consolas, monospace';\n    x.fillText('r', cx+R*0.45, cy-R*0.18);\n    x.restore();\n\n    /* 绳：从切点向下引出 */\n    var tx = cx + R*Math.cos(ang), ty = cy - R*Math.sin(ang);\n    x.save();\n    x.strokeStyle = 'rgba(251,191,36,.9)';\n    x.lineWidth = 3; x.lineCap = 'round';\n    x.shadowColor = 'rgba(251,191,36,.8)'; x.shadowBlur = 12;\n    x.beginPath(); x.moveTo(tx, ty); x.lineTo(tx, h-26); x.stroke();\n    x.restore();\n\n    /* 角度弧 */\n    x.save();\n    x.strokeStyle = 'rgba(255,255,255,.5)';\n    x.lineWidth = 1.2;\n    x.beginPath(); x.arc(cx, cy, R*0.32, 0, -ang, true); x.stroke();\n    x.fillStyle = 'rgba(255,255,255,.8)';\n    x.font = '12px \"JetBrains Mono\", Consolas, monospace';\n    x.fillText('θ', cx+R*0.36, cy-R*0.10);\n    x.restore();\n\n    /* 拉力箭头 */\n    x.save();\n    x.fillStyle = 'rgba(251,191,36,.95)';\n    x.font = '600 13px \"JetBrains Mono\", Consolas, monospace';\n    x.fillText('f', tx+9, h-44);\n    x.beginPath();\n    x.moveTo(tx, h-30); x.lineTo(tx, h-58);\n    x.lineTo(tx-5, h-51); x.lineTo(tx, h-58); x.lineTo(tx+5, h-51);\n    x.closePath(); x.fill();\n    x.restore();\n\n    /* 收线量 dl */\n    x.save();\n    x.strokeStyle = 'rgba(34,211,238,.7)';\n    x.lineWidth = 1;\n    x.setLineDash([2,3]);\n    x.beginPath(); x.moveTo(tx-8, cy); x.lineTo(tx-8, h-30); x.stroke();\n    x.setLineDash([]);\n    x.fillStyle = 'rgba(34,211,238,.85)';\n    x.font = '11px \"JetBrains Mono\", Consolas, monospace';\n    x.fillText('dl = r·dθ', tx-74, h-62);\n    x.restore();\n\n    /* 力矩 */\n    x.save();\n    x.strokeStyle = 'rgba(167,139,250,.45)';\n    x.lineWidth = 1.4;\n    x.beginPath(); x.arc(cx, cy, R*1.16, -1.25, -0.55); x.stroke();\n    x.fillStyle = 'rgba(190,170,255,.9)';\n    x.font = '11px \"JetBrains Mono\", Consolas, monospace';\n    x.fillText('τ = f · r', cx+R*0.72, cy-R*1.28);\n    x.restore();\n  }\n\n  /* ================= 交互 ================= */\n  var slR = document.getElementById('sl-r'), slP = document.getElementById('sl-p');\n  var outR = document.getElementById('out-r'), outP = document.getElementById('out-p');\n  var btnPlay = document.getElementById('btn-play'), btnZero = document.getElementById('btn-zero');\n\n  slR.addEventListener('input', function(){\n    scene.tr = parseFloat(slR.value)*DEG;\n    outR.textContent = parseFloat(slR.value).toFixed(1) + '°';\n    scene.sweep = false;\n    btnPlay.textContent = '继续扫掠';\n    needsChart = true;\n  });\n  slP.addEventListener('input', function(){\n    scene.tp = parseFloat(slP.value)*DEG;\n    outP.textContent = parseFloat(slP.value).toFixed(1) + '°';\n    scene.sweep = false;\n    btnPlay.textContent = '继续扫掠';\n    needsChart = true;\n  });\n\n  btnPlay.addEventListener('click', function(){\n    scene.sweep = !scene.sweep;\n    btnPlay.textContent = scene.sweep ? '暂停扫掠' : '继续扫掠';\n  });\n  btnZero.addEventListener('click', function(){\n    scene.sweep = false;\n    btnPlay.textContent = '继续扫掠';\n    scene.tr = 0; scene.tp = 0;\n    slR.value = 0; slP.value = 0;\n    outR.textContent = '0.0°'; outP.textContent = '0.0°';\n    needsChart = true;\n  });\n\n  canvas.addEventListener('pointerdown', function(e){\n    scene.dragging = true;\n    scene.lastX = e.clientX; scene.lastY = e.clientY;\n    canvas.classList.add('drag');\n    if(canvas.setPointerCapture) canvas.setPointerCapture(e.pointerId);\n  });\n  canvas.addEventListener('pointermove', function(e){\n    if(!scene.dragging) return;\n    scene.azUser += (e.clientX - scene.lastX)*0.008;\n    scene.elUser += (e.clientY - scene.lastY)*0.005;\n    scene.elUser = Math.max(-0.22, Math.min(0.55, scene.elUser));\n    scene.lastX = e.clientX; scene.lastY = e.clientY;\n    resizeScene();\n  });\n  window.addEventListener('pointerup', function(){\n    scene.dragging = false;\n    canvas.classList.remove('drag');\n  });\n\n  /* ================= 动画主循环 ================= */\n  var last = performance.now(), needsChart = true, chartClock = 0;\n\n  function frame(now){\n    var dt = Math.min(0.05, (now-last)/1000); last = now;\n    scene.t += dt;\n    spoolT += dt;\n\n    if(scene.sweep){\n      scene.tr = (16*Math.sin(scene.t*0.55))*DEG;\n      scene.tp = (14 + 18*Math.sin(scene.t*0.37 + 1.1))*DEG;\n      slR.value = (scene.tr/DEG).toFixed(1);\n      slP.value = (scene.tp/DEG).toFixed(1);\n      outR.textContent = (scene.tr/DEG).toFixed(1) + '°';\n      outP.textContent = (scene.tp/DEG).toFixed(1) + '°';\n      needsChart = true;\n    }\n\n    renderScene();\n    drawSpool();\n    updateReadout();\n\n    chartClock += dt;\n    if(needsChart && chartClock > 1/30){\n      drawCharts();\n      chartClock = 0;\n      needsChart = false;\n    }\n    requestAnimationFrame(frame);\n  }\n\n  /* ================= 入场动画 ================= */\n  var io = new IntersectionObserver(function(entries){\n    entries.forEach(function(en){\n      if(en.isIntersecting){\n        en.target.classList.add('in');\n        if(en.target.id === 'bars') animateBars();\n        io.unobserve(en.target);\n      }\n    });\n  }, { threshold:0.12 });\n\n  document.querySelectorAll('.reveal').forEach(function(el){ io.observe(el); });\n\n  function animateBars(){\n    var fills = Array.prototype.slice.call(document.querySelectorAll('.fill'));\n    fills.forEach(function(el){ el.style.transition = 'none'; el.style.width = '0%'; });\n    void document.body.offsetHeight;\n    fills.forEach(function(el, i){\n      el.style.transition = '';\n      setTimeout(function(){ el.style.width = el.getAttribute('data-w') + '%'; }, 80 + i*90);\n    });\n  }\n\n  /* 数字滚动 */\n  var counters = document.querySelectorAll('.counter b');\n  var cio = new IntersectionObserver(function(entries){\n    entries.forEach(function(en){\n      if(!en.isIntersecting) return;\n      var el = en.target;\n      var target = parseFloat(el.getAttribute('data-count'));\n      var dec = parseInt(el.getAttribute('data-dec') || '0', 10);\n      var sci = el.getAttribute('data-sci');\n      var t0 = performance.now(), dur = 1200;\n      function step(t){\n        var k = Math.max(0, Math.min(1, (t-t0)/dur));\n        var e = 1 - Math.pow(1-k, 3);\n        var v = target*e;\n        if(sci) el.textContent = v.toExponential(1);\n        else if(target >= 100) el.textContent = Math.round(v).toLocaleString('en-US');\n        else el.textContent = v.toFixed(dec);\n        if(k < 1) requestAnimationFrame(step);\n        else{\n          if(sci) el.textContent = target.toExponential(1);\n          else if(target >= 100) el.textContent = Math.round(target).toLocaleString('en-US');\n          else el.textContent = target.toFixed(dec);\n        }\n      }\n      requestAnimationFrame(step);\n      cio.unobserve(el);\n    });\n  }, { threshold:0.4 });\n  counters.forEach(function(el){ cio.observe(el); });\n\n  /* 进度条 */\n  var bar = document.getElementById('progress');\n  window.addEventListener('scroll', function(){\n    var h = document.documentElement.scrollHeight - window.innerHeight;\n    bar.style.width = (h > 0 ? (window.scrollY/h*100) : 0) + '%';\n  }, { passive:true });\n\n  /* ================= 启动 ================= */\n  window.addEventListener('resize', function(){\n    resizeScene();\n    needsChart = true;\n  });\n\n  function boot(){\n    fitScene();\n    resizeScene();\n    updateReadout();\n    drawCharts();\n    requestAnimationFrame(frame);\n  }\n\n  if(document.readyState === 'complete') boot();\n  else window.addEventListener('load', boot);\n})();\n</script>\n</body>\n</html>\n";
    /* ==== SANDBOX-PAGE:END ==== */

    const ALL = 'all';

    const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

    const CSS = [
      '.dsh-fp-page{position:relative;box-sizing:border-box;display:flex;flex-direction:column;height:100%;min-height:0;color:var(--dsw-alias-label-primary);font-family:inherit;}',
      '.dsh-fp-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:22px 26px 14px;}',
      '.dsh-fp-headmain{display:flex;flex-direction:column;gap:5px;min-width:0;}',
      '.dsh-fp-eyebrow{margin:0;font-size:10.5px;line-height:1.4;letter-spacing:0.09em;text-transform:uppercase;color:var(--dsw-alias-label-tertiary);}',
      '.dsh-fp-title{margin:0;font-size:21px;font-weight:650;line-height:1.2;letter-spacing:0.01em;}',
      '.dsh-fp-sub{margin:0;font-size:12.5px;line-height:1.55;color:var(--dsw-alias-label-secondary);max-width:52ch;}',
      '.dsh-fp-count{flex:0 0 auto;display:inline-flex;align-items:baseline;gap:4px;margin-top:3px;padding:3px 11px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);font-size:11.5px;line-height:1.6;color:var(--dsw-alias-label-secondary);white-space:nowrap;font-variant-numeric:tabular-nums;}',
      '.dsh-fp-count b{font-weight:600;color:var(--dsw-alias-label-primary);}',
      '.dsh-fp-toolbar{display:flex;flex-direction:column;gap:10px;padding:0 26px 12px;}',
      '.dsh-fp-searchbox{display:flex;align-items:center;gap:9px;height:38px;padding:0 10px 0 12px;box-sizing:border-box;border:1px solid var(--dsw-alias-border-l2);border-radius:11px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-tertiary);transition:border-color 120ms ease,box-shadow 120ms ease,background 120ms ease;}',
      '.dsh-fp-searchbox:hover{border-color:var(--dsw-alias-border-l3);}',
      '.dsh-fp-searchbox:focus-within{border-color:var(--dsw-alias-link);box-shadow:0 0 0 3px color-mix(in srgb, var(--dsw-alias-link) 15%, transparent);color:var(--dsw-alias-label-primary);background:var(--dsw-alias-bg-base);}',
      '.dsh-fp-search{flex:1 1 auto;min-width:0;height:100%;border:none;outline:none;background:transparent;color:inherit;font-family:inherit;font-size:13px;}',
      '.dsh-fp-search::placeholder{color:var(--dsw-alias-label-tertiary);}',
      '.dsh-fp-kbd{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 5px;border-radius:5px;border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-2);color:var(--dsw-alias-label-tertiary);font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;font-size:10.5px;line-height:1;}',
      '.dsh-fp-chips{display:flex;flex-wrap:wrap;gap:6px;}',
      '.dsh-fp-chip{appearance:none;display:inline-flex;align-items:baseline;gap:5px;padding:4px 10px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:transparent;color:var(--dsw-alias-label-secondary);font-family:inherit;font-size:12px;line-height:1.5;cursor:pointer;transition:background 100ms ease,border-color 100ms ease,color 100ms ease;}',
      '.dsh-fp-chip:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary);}',
      '.dsh-fp-chip:focus-visible{outline:2px solid var(--dsw-alias-link);outline-offset:2px;}',
      '.dsh-fp-chip[aria-pressed="true"]{border-color:color-mix(in srgb, var(--dsw-alias-link) 55%, var(--dsw-alias-border-l1));background:color-mix(in srgb, var(--dsw-alias-link) 10%, transparent);color:var(--dsw-alias-label-primary);}',
      '.dsh-fp-chip em{font-style:normal;font-size:10.5px;color:var(--dsw-alias-label-tertiary);font-variant-numeric:tabular-nums;}',
      '.dsh-fp-chip[aria-pressed="true"] em{color:var(--dsw-alias-link);}',
      '.dsh-fp-rule{height:1px;margin:0 26px;background:var(--dsw-alias-border-l1);}',
      '.dsh-fp-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;padding:0 26px 22px;display:flex;flex-direction:column;gap:10px;}',
      '.dsh-fp-group{display:flex;flex-direction:column;gap:10px;padding-top:14px;}',
      '.dsh-fp-grouphead{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:10px;padding:7px 0 6px;background:color-mix(in srgb, var(--dsw-alias-bg-base) 94%, transparent);backdrop-filter:blur(8px);}',
      '.dsh-fp-grouptitle{margin:0;font-size:11px;font-weight:600;letter-spacing:0.08em;color:var(--dsw-alias-label-secondary);white-space:nowrap;}',
      '.dsh-fp-groupnum{font-size:10.5px;color:var(--dsw-alias-label-tertiary);font-variant-numeric:tabular-nums;white-space:nowrap;}',
      '.dsh-fp-groupline{flex:1 1 auto;height:1px;background:var(--dsw-alias-border-l1);}',
      '.dsh-fp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(292px,1fr));gap:10px;align-items:start;}',
      '.dsh-fp-card{position:relative;appearance:none;display:flex;flex-direction:column;gap:6px;min-width:0;padding:13px 14px 13px 15px;border-radius:12px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb, var(--dsw-alias-label-primary) 1.5%, var(--dsw-alias-bg-base));color:var(--dsw-alias-label-primary);text-align:left;font-family:inherit;cursor:copy;overflow:hidden;transition:background 130ms ease,border-color 130ms ease,transform 130ms ease,box-shadow 130ms ease;}',
      '.dsh-fp-card:hover{background:color-mix(in srgb, var(--dsw-alias-link) 5%, var(--dsw-alias-bg-base));border-color:color-mix(in srgb, var(--dsw-alias-link) 45%, var(--dsw-alias-border-l2));transform:translateY(-1px);box-shadow:0 10px 22px -18px color-mix(in srgb, var(--dsw-alias-label-primary) 70%, transparent);}',
      '.dsh-fp-card:active{transform:translateY(0);}',
      '.dsh-fp-card:focus-visible{outline:2px solid var(--dsw-alias-link);outline-offset:2px;}',
      '.dsh-fp-card::before{content:"";position:absolute;left:0;top:13px;bottom:13px;width:2px;border-radius:0 2px 2px 0;background:var(--dsw-alias-link);opacity:0;transition:opacity 130ms ease;}',
      '.dsh-fp-card:hover::before{opacity:0.9;}',
      '.dsh-fp-card[data-copied="true"]{border-color:color-mix(in srgb, var(--dsw-alias-link) 55%, var(--dsw-alias-border-l2));background:color-mix(in srgb, var(--dsw-alias-link) 6%, var(--dsw-alias-bg-base));}',
      '.dsh-fp-card[data-copied="true"]::before{opacity:1;}',
      '.dsh-fp-cardtop{display:flex;align-items:center;gap:8px;min-width:0;}',
      '.dsh-fp-no{flex:0 0 auto;padding:1px 6px;border-radius:5px;border:1px solid color-mix(in srgb, var(--dsw-alias-link) 26%, var(--dsw-alias-border-l1));background:color-mix(in srgb, var(--dsw-alias-link) 7%, transparent);color:var(--dsw-alias-link);font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;font-size:10px;line-height:1.6;letter-spacing:0.02em;}',
      '.dsh-fp-sym{flex:1 1 auto;min-width:0;font-family:var(--dsw-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif);font-size:15px;letter-spacing:0;font-weight:600;line-height:1.5;color:var(--dsw-alias-label-primary);word-break:break-word;}',
      '.dsh-fp-copybtn{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:6px;color:var(--dsw-alias-label-tertiary);opacity:0;transition:opacity 120ms ease,color 120ms ease;}',
      '.dsh-fp-card:hover .dsh-fp-copybtn,.dsh-fp-card:focus-visible .dsh-fp-copybtn{opacity:1;color:var(--dsw-alias-link);}',
      '.dsh-fp-card[data-copied="true"] .dsh-fp-copybtn{opacity:1;color:var(--dsw-alias-state-success-primary);}',
      '.dsh-fp-name{display:block;font-size:12.5px;line-height:1.5;color:var(--dsw-alias-label-primary);word-break:break-word;}',
      '.dsh-fp-formula{display:block;margin-top:1px;padding:6px 8px;border-radius:7px;border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-markdown-code-block);font-family:var(--dsw-font-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);font-size:11px;line-height:1.7;color:var(--dsw-alias-label-secondary);word-break:break-word;}',
      '.dsh-fp-m{font-family:var(--dsw-font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif);font-variant-ligatures:none;}',
      '.dsh-fp-formula .dsh-fp-m{font-family:var(--dsw-font-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);}',
      '.dsh-fp-mi{font-style:italic;}',
      '.dsh-fp-formula .dsh-fp-mi{font-style:normal;}',
      '.dsh-fp-mup{font-style:normal;}',
      '.dsh-fp-msub,.dsh-fp-msup{font-size:0.7em;line-height:0;}',
      '.dsh-fp-msub{vertical-align:-0.24em;}',
      '.dsh-fp-msup{vertical-align:0.42em;}',
      '.dsh-fp-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;padding:56px 12px;text-align:center;color:var(--dsw-alias-label-secondary);}',
      '.dsh-fp-emptytitle{margin:0;font-size:13px;color:var(--dsw-alias-label-primary);}',
      '.dsh-fp-emptyhint{margin:0;font-size:12px;color:var(--dsw-alias-label-tertiary);}',
      '.dsh-fp-reset{appearance:none;margin-top:6px;padding:5px 12px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font-family:inherit;font-size:12px;cursor:pointer;}',
      '.dsh-fp-reset:hover{background:var(--dsw-alias-interactive-bg-hover);}',
      '.dsh-fp-toast{position:absolute;left:50%;bottom:18px;transform:translate(-50%,6px);display:inline-flex;align-items:center;gap:7px;max-width:calc(100% - 48px);padding:6px 13px;border-radius:999px;background:var(--dsw-alias-toast-bg);color:var(--dsw-alias-toast-label);font-size:12px;line-height:1.5;box-shadow:0 8px 22px -14px color-mix(in srgb, var(--dsw-alias-label-primary) 80%, transparent);opacity:0;pointer-events:none;transition:opacity 150ms ease,transform 150ms ease;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.dsh-fp-toast[data-visible="true"]{opacity:1;transform:translate(-50%,0);}',
      '.dsh-fp-tabs{flex:0 0 auto;display:inline-flex;margin-top:3px;padding:2px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);gap:2px;}',
      '.dsh-fp-tab{appearance:none;padding:4px 11px;border-radius:999px;border:0;background:transparent;color:var(--dsw-alias-label-secondary);font-family:inherit;font-size:12px;line-height:1.5;cursor:pointer;white-space:nowrap;transition:background 100ms ease,color 100ms ease;}',
      '.dsh-fp-tab:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary);}',
      '.dsh-fp-tab:focus-visible{outline:2px solid var(--dsw-alias-link);outline-offset:1px;}',
      '.dsh-fp-tab[aria-selected="true"]{background:color-mix(in srgb, var(--dsw-alias-link) 12%, transparent);color:var(--dsw-alias-label-primary);}',
      '.dsh-fp-slot{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;padding:0 26px 20px;}',
      '.dsh-fp-slotframe{padding:0 26px 20px;}',
      '.dsh-fp-page[data-tab="3d"] .dsh-fp-toolbar,.dsh-fp-page[data-tab="3d"] .dsh-fp-rule,.dsh-fp-page[data-tab="3d"] .dsh-fp-scroll{display:none;}',
      '.dsh-fp-page[data-tab="guide"] .dsh-fp-toolbar,.dsh-fp-page[data-tab="guide"] .dsh-fp-rule,.dsh-fp-page[data-tab="guide"] .dsh-fp-scroll{display:none;}',
      '.dsh-fp-slot .dsh-fp3{flex:1 1 auto;min-height:0;}',
      '.dsh-fp-slot .dsh-fp3-head{display:none;}',
      '.dsh-fp-slot .dsh-fp3-scroll{padding:0 0 4px;}',
      '.dsh-fp-frame{flex:1 1 auto;min-height:0;display:block;width:100%;height:100%;border:1px solid var(--dsw-alias-border-l2);border-radius:12px;overflow:hidden;background:#0b0e14;}',
      '.dsh-fp-frame iframe{display:block;width:100%;height:100%;border:0;background:#0b0e14;}',
      '.dsh-fp-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}',
    ].join('');

    const UPRIGHT = /^(?:sin|cos|tan|asin|acos|atan2|atan|exp|log|ln|max|min|sqrt|sign|Rot)(?![A-Za-z])/;
    const LATIN = /^[A-Za-z]+/;
    const GREEK = /^[\u0391-\u03A9\u03B1-\u03C9]+/;

    /** Split a compact formula into upright, italic, subscript and superscript runs. */
    function mathRuns(source) {
      const runs = [];
      let i = 0;
      while (i < source.length) {
        const ch = source.charAt(i);
        if ((ch === '_' || ch === '^') && i + 1 < source.length) {
          let next = i + 1;
          let body;
          if (source.charAt(next) === '{') {
            const close = source.indexOf('}', next);
            if (close > next) {
              body = source.slice(next + 1, close);
              next = close + 1;
            }
          }
          if (body === undefined) {
            body = source.charAt(next);
            next += 1;
          }
          runs.push({ kind: ch === '_' ? 'sub' : 'sup', text: body });
          i = next;
          continue;
        }
        const rest = source.slice(i);
        const upright = UPRIGHT.exec(rest);
        if (upright) {
          runs.push({ kind: 'up', text: upright[0] });
          i += upright[0].length;
          continue;
        }
        const latin = LATIN.exec(rest);
        if (latin) {
          runs.push({ kind: 'i', text: latin[0] });
          i += latin[0].length;
          continue;
        }
        const greek = GREEK.exec(rest);
        if (greek) {
          runs.push({ kind: 'i', text: greek[0] });
          i += greek[0].length;
          continue;
        }
        runs.push({ kind: 'n', text: ch });
        i += 1;
      }
      return runs;
    }

    function inlineRuns(text, keyPrefix) {
      return mathRuns(text).map((run, index) => {
        const key = keyPrefix + '-' + index;
        if (run.kind === 'sub') return h('span', { key: key, className: 'dsh-fp-msub dsh-fp-mup' }, run.text);
        if (run.kind === 'sup') return h('span', { key: key, className: 'dsh-fp-msup dsh-fp-mup' }, run.text);
        if (run.kind === 'i') return h('span', { key: key, className: 'dsh-fp-mi' }, run.text);
        if (run.kind === 'up') return h('span', { key: key, className: 'dsh-fp-mup' }, run.text);
        return h('span', { key: key }, run.text);
      });
    }

    function Formula(props) {
      return h(
        'span',
        { className: 'dsh-fp-m', 'data-formula': true },
        inlineRuns(props.text || '', props.prefix || 'f'),
      );
    }

    function glyph(path, size) {
      return h(
        'svg',
        {
          viewBox: '0 0 24 24',
          width: size,
          height: size,
          fill: 'none',
          stroke: 'currentColor',
          strokeWidth: 1.7,
          strokeLinecap: 'round',
          strokeLinejoin: 'round',
          'aria-hidden': true,
          focusable: false,
          style: { display: 'block' },
        },
        path,
      );
    }

    function copyGlyph(size) {
      return glyph(
        [
          h('rect', { key: 'a', x: 9, y: 9, width: 11, height: 11, rx: 2.5 }),
          h('path', { key: 'b', d: 'M15 5.5H6.5A2.5 2.5 0 0 0 4 8v8.5' }),
        ],
        size,
      );
    }

    function checkGlyph(size) {
      return glyph(h('path', { d: 'M4.5 12.5l5 5L19.5 7' }), size);
    }

    function searchGlyph(size) {
      return glyph(
        [
          h('circle', { key: 'a', cx: 10.5, cy: 10.5, r: 6.5 }),
          h('path', { key: 'b', d: 'M15.6 15.6L21 21' }),
        ],
        size,
      );
    }

    function emptyGlyph(size) {
      return glyph(
        [
          h('path', { key: 'a', d: 'M4 6h9M4 12h6M4 18h7' }),
          h('circle', { key: 'b', cx: 16.5, cy: 16.5, r: 3.5 }),
          h('path', { key: 'c', d: 'M19.2 19.2L21 21' }),
        ],
        size,
      );
    }

    /** Drop the subscript markup so the toast shows readable text. */
    function plainSymbol(value) {
      return String(value || '')
        .replace(/_\{([^}]*)\}/g, '_$1')
        .replace(/\^\{([^}]*)\}/g, '^$1');
    }

    function copyText(value) {
      const clipboard = navigator.clipboard;
      if (clipboard && typeof clipboard.writeText === 'function') {
        return clipboard.writeText(value).then(
          () => true,
          () => fallbackCopy(value),
        );
      }
      return Promise.resolve(fallbackCopy(value));
    }

    function fallbackCopy(value) {
      try {
        const area = document.createElement('textarea');
        area.value = value;
        area.setAttribute('readonly', '');
        area.style.position = 'fixed';
        area.style.top = '0';
        area.style.left = '-9999px';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(area);
        return ok;
      } catch (error) {
        return false;
      }
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        /** The locale client service; it can mount after this plugin, so never cache it. */
        function localeService() {
          try {
            return ctx.get('locale');
          } catch (error) {
            return undefined;
          }
        }

        /** Active language tag: locale service first, then the <html lang> the shell keeps in sync. */
        function languageTag() {
          try {
            const locale = localeService();
            const snapshot =
              locale && typeof locale.getSnapshot === 'function' ? locale.getSnapshot() : undefined;
            let active = snapshot && typeof snapshot.active === 'string' ? snapshot.active : '';
            if (!active && locale && typeof locale.getLocale === 'function') {
              const current = locale.getLocale();
              if (current && typeof current.active === 'string') active = current.active;
            }
            if (!active && typeof document !== 'undefined' && document.documentElement) {
              active = document.documentElement.lang || '';
            }
            if (!active && typeof navigator !== 'undefined' && typeof navigator.language === 'string') {
              active = navigator.language;
            }
            return active.toLowerCase();
          } catch (error) {
            return '';
          }
        }

        /** The plugin ships zh + en: an English tag selects en, everything else reads zh. */
        function activeLanguage() {
          return languageTag().indexOf('en') === 0 ? 'en' : 'zh';
        }

        /** Follow language switches: ride the locale service when it appears, else watch <html lang>. */
        function watchLanguage(setLanguage) {
          let stop;
          let timer;
          let observer;
          const attach = () => {
            const locale = localeService();
            if (!locale || typeof locale.subscribe !== 'function') return false;
            stop = locale.subscribe(() => setLanguage(activeLanguage()));
            setLanguage(activeLanguage());
            return true;
          };
          if (!attach()) {
            let tries = 0;
            timer = window.setInterval(() => {
              tries += 1;
              if (attach() || tries >= 10) {
                window.clearInterval(timer);
                timer = undefined;
              }
            }, 200);
            if (
              typeof MutationObserver === 'function' &&
              typeof document !== 'undefined' &&
              document.documentElement
            ) {
              observer = new MutationObserver(() => setLanguage(activeLanguage()));
              observer.observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
            }
          }
          return () => {
            if (timer !== undefined) window.clearInterval(timer);
            if (observer) observer.disconnect();
            if (typeof stop === 'function') stop();
          };
        }

        function useLocale() {
          const [language, setLanguage] = React.useState(activeLanguage);
          React.useEffect(() => watchLanguage(setLanguage), []);
          return { text: TEXT[language], language: language };
        }

        /** Sidebar artwork: a sigma built from the same stroke weight as the shell icons. */
        function PanelIcon(props) {
          const size = typeof props.size === 'number' && props.size > 0 ? props.size : 20;
          return h(
            'svg',
            {
              viewBox: '0 0 24 24',
              width: size,
              height: size,
              fill: 'none',
              stroke: 'currentColor',
              strokeWidth: 1.7,
              strokeLinecap: 'round',
              strokeLinejoin: 'round',
              'aria-hidden': true,
              focusable: false,
              style: { display: 'block' },
            },
            h('path', { d: 'M6.5 5.5h11l-5.6 6.5 5.6 6.5h-11' }),
          );
        }

        function Card(props) {
          const entry = props.entry;
          return h(
            'button',
            {
              type: 'button',
              className: 'dsh-fp-card',
              'data-copied': props.copied ? 'true' : 'false',
              title: entry.copy,
              onClick: props.onPick,
            },
            h(
              'span',
              { className: 'dsh-fp-cardtop' },
              entry.no ? h('span', { className: 'dsh-fp-no' }, entry.no) : null,
              h('span', { className: 'dsh-fp-sym' }, h(Formula, { text: entry.sym, prefix: props.uid + '-s' })),
              h('span', { className: 'dsh-fp-copybtn' }, props.copied ? checkGlyph(14) : copyGlyph(14)),
            ),
            h('span', { className: 'dsh-fp-name' }, entry.name),
            entry.f
              ? h('span', { className: 'dsh-fp-formula' }, h(Formula, { text: entry.f, prefix: props.uid + '-f' }))
              : null,
          );
        }

        /** Whole sandbox page, rendered from the inlined HTML so it works offline. */
        function Diagram() {
          return h(
            'div',
            { className: 'dsh-fp-frame' },
            h('iframe', {
              srcDoc: PAGE_HTML,
              title: '图解',
              loading: 'lazy',
            }),
          );
        }

        function Panel() {
          const { text, language } = useLocale();
          const [query, setQuery] = React.useState('');
          const [scope, setScope] = React.useState(ALL);
          const [tab, setTab] = React.useState('list');
          const [feedback, setFeedback] = React.useState(null);
          const searchRef = React.useRef(null);
          const scrollRef = React.useRef(null);

          React.useEffect(() => {
            if (!feedback) return undefined;
            const timer = window.setTimeout(() => setFeedback(null), 1800);
            return () => window.clearTimeout(timer);
          }, [feedback]);

          React.useEffect(() => {
            const onKey = (event) => {
              const target = event.target;
              const typing =
                target &&
                (target.tagName === 'INPUT' ||
                  target.tagName === 'TEXTAREA' ||
                  target.isContentEditable === true);
              const key = typeof event.key === 'string' ? event.key : '';
              const cmdK = (event.metaKey || event.ctrlKey) && key.toLowerCase() === 'k';
              if (!typing && (key === '/' || cmdK)) {
                event.preventDefault();
                if (searchRef.current) searchRef.current.focus();
                return;
              }
              if (key === 'Escape' && typing) {
                setQuery('');
                if (searchRef.current) searchRef.current.blur();
              }
            };
            document.addEventListener('keydown', onKey);
            return () => document.removeEventListener('keydown', onKey);
          }, []);

          React.useEffect(() => {
            if (scrollRef.current) scrollRef.current.scrollTop = 0;
          }, [scope]);

          const counts = React.useMemo(() => {
            const map = {};
            let total = 0;
            GROUPS.forEach((group) => {
              map[group.id] = group.entries.length;
              total += group.entries.length;
            });
            map[ALL] = total;
            return map;
          }, []);

          const needle = query.trim().toLowerCase();
          const sections = React.useMemo(() => {
            return GROUPS.map((group) => ({
              id: group.id,
              title: group.title,
              entries: group.entries.filter((entry) => {
                if (scope !== ALL && scope !== group.id) return false;
                if (!needle) return true;
                const haystack =
                  (entry.no || '') +
                  ' ' +
                  entry.sym +
                  ' ' +
                  entry.name +
                  ' ' +
                  (entry.f || '') +
                  ' ' +
                  entry.copy;
                return haystack.toLowerCase().indexOf(needle) >= 0;
              }),
            })).filter((group) => group.entries.length > 0);
          }, [needle, scope]);

          const total = sections.reduce((sum, section) => sum + section.entries.length, 0);
          const filtered = needle.length > 0 || scope !== ALL;

          const pick = (key, entry) => {
            copyText(entry.copy).then((ok) =>
              setFeedback({
                key: key,
                ok: ok === true,
                symbol: (entry.no ? entry.no + ' ' : '') + plainSymbol(entry.sym),
              }),
            );
          };

          const notice = feedback
            ? (feedback.ok ? text.copied : text.copyFailed) + ' · ' + feedback.symbol
            : '';

          return h(
            'div',
            { className: 'dsh-fp-page', 'data-tab': tab },
            h('style', { key: 'panel-styles' }, CSS),
            h(
              'header',
              { className: 'dsh-fp-head' },
              h(
                'div',
                { className: 'dsh-fp-headmain' },
                h('p', { className: 'dsh-fp-eyebrow' }, text.eyebrow),
                h('h1', { className: 'dsh-fp-title' }, text.title),
                h('p', { className: 'dsh-fp-sub' }, text.subtitle),
              ),
              h(
                'div',
                { className: 'dsh-fp-tabs', role: 'tablist' },
                [
                  ['list', text.tabReference],
                  ['3d', text.tabScene],
                  ['guide', text.tabGuide],
                ].map(([key, label]) =>
                  h(
                    'button',
                    {
                      key: key,
                      type: 'button',
                      role: 'tab',
                      className: 'dsh-fp-tab',
                      'aria-selected': tab === key,
                      onClick: () => setTab(key),
                    },
                    label,
                  ),
                ),
              ),
            ),
            h(
              'div',
              { className: 'dsh-fp-toolbar' },
              h(
                'label',
                { className: 'dsh-fp-searchbox' },
                searchGlyph(15),
                h('input', {
                  ref: searchRef,
                  className: 'dsh-fp-search',
                  type: 'search',
                  value: query,
                  placeholder: text.search,
                  'aria-label': text.search,
                  onChange: (event) => setQuery(event.target.value),
                }),
                h('kbd', { className: 'dsh-fp-kbd', title: text.shortcut }, '/'),
              ),
              h(
                'div',
                { className: 'dsh-fp-chips', role: 'group', 'aria-label': text.groupsLabel },
                h(
                  'button',
                  {
                    type: 'button',
                    className: 'dsh-fp-chip',
                    'aria-pressed': scope === ALL,
                    onClick: () => setScope(ALL),
                  },
                  text.all,
                  h('em', null, counts[ALL]),
                ),
                GROUPS.map((group) =>
                  h(
                    'button',
                    {
                      key: group.id,
                      type: 'button',
                      className: 'dsh-fp-chip',
                      'aria-pressed': scope === group.id,
                      onClick: () => setScope(group.id),
                    },
                    group.title[language],
                    h('em', null, counts[group.id]),
                  ),
                ),
              ),
            ),
            h('div', { className: 'dsh-fp-rule' }),
            h(
              'div',
              { className: 'dsh-fp-scroll', ref: scrollRef },
              sections.length === 0
                ? h(
                    'div',
                    { className: 'dsh-fp-empty' },
                    emptyGlyph(30),
                    h('p', { className: 'dsh-fp-emptytitle' }, text.empty),
                    h('p', { className: 'dsh-fp-emptyhint' }, text.emptyHint),
                    h(
                      'button',
                      {
                        type: 'button',
                        className: 'dsh-fp-reset',
                        onClick: () => {
                          setQuery('');
                          setScope(ALL);
                        },
                      },
                      text.reset,
                    ),
                  )
                : sections.map((section, sectionIndex) =>
                    h(
                      'section',
                      { key: section.id, className: 'dsh-fp-group' },
                      h(
                        'div',
                        { className: 'dsh-fp-grouphead' },
                        h('h2', { className: 'dsh-fp-grouptitle' }, section.title[language]),
                        h('span', { className: 'dsh-fp-groupnum' }, text.count(section.entries.length)),
                        h('span', { className: 'dsh-fp-groupline' }),
                      ),
                      h(
                        'div',
                        { className: 'dsh-fp-grid' },
                        section.entries.map((entry, index) => {
                          const key = section.id + '-' + index;
                          return h(Card, {
                            key: key,
                            entry: entry,
                            uid: sectionIndex + '-' + index,
                            copied: feedback !== null && feedback.key === key,
                            onPick: () => pick(key, entry),
                          });
                        }),
                      ),
                    ),
                  ),
            ),
            tab === '3d' ? h('div', { className: 'dsh-fp-slot' }, h(Scene3D)) : null,
            tab === 'guide' ? h('div', { className: 'dsh-fp-slot dsh-fp-slotframe' }, h(Diagram)) : null,
            h(
              'div',
              {
                className: 'dsh-fp-toast',
                'data-visible': feedback !== null && feedback.ok ? 'true' : 'false',
              },
              feedback && feedback.ok ? checkGlyph(13) : null,
              feedback ? (feedback.ok ? text.copied : text.copyFailed) : '',
            ),
            h('span', { className: 'dsh-fp-sr', role: 'status', 'aria-live': 'polite' }, notice),
          );
        }


        const TEXT_3D = {
          zh: {
            nav: '3D 腕部',
            eyebrow: '绳驱二轴腕部 · 交互模型',
            title: '3D 腕部模型',
            sub: '拖动旋转视角，滑块改关节角；绳长与 R 矩阵实时重算。',
            drag: '拖动旋转 · 双击复位',
            thetaR: 'roll θr',
            thetaP: 'pitch θp',
            zero: '回零位',
            matrix: 'R 力臂矩阵（mm/rad）',
            torque: 'τ = R·f，f = 10 N（N·mm）',
            lengths: '绳长：几何真值 vs 闭式',
            geo: '几何',
            closed: '闭式',
            diff: 'Δ',
          },
          en: {
            nav: '3D Wrist',
            eyebrow: 'Rope-driven two-axis wrist',
            title: '3D wrist model',
            sub: 'Drag to orbit, slide the joint angles; rope lengths and R recompute live.',
            drag: 'Drag to orbit · double-click to reset',
            thetaR: 'roll θr',
            thetaP: 'pitch θp',
            zero: 'Reset angles',
            matrix: 'Lever-arm matrix R (mm/rad)',
            torque: 'τ = R·f with f = 10 N (N·mm)',
            lengths: 'Rope length: geometry vs closed form',
            geo: 'geometry',
            closed: 'closed',
            diff: 'Δ',
          },
        };

        const CSS_3D = [
          '.dsh-fp3{box-sizing:border-box;display:flex;flex-direction:column;height:100%;min-height:0;color:var(--dsw-alias-label-primary);font-family:inherit;}',
          '.dsh-fp3-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:22px 26px 12px;}',
          '.dsh-fp3-headmain{display:flex;flex-direction:column;gap:5px;min-width:0;}',
          '.dsh-fp3-eyebrow{margin:0;font-size:10.5px;line-height:1.4;letter-spacing:0.09em;text-transform:uppercase;color:var(--dsw-alias-label-tertiary);}',
          '.dsh-fp3-title{margin:0;font-size:21px;font-weight:600;line-height:1.2;}',
          '.dsh-fp3-sub{margin:0;font-size:12.5px;line-height:1.55;color:var(--dsw-alias-label-secondary);max-width:52ch;}',
          '.dsh-fp3-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;padding:0 26px 24px;display:flex;flex-direction:column;gap:12px;}',
          '.dsh-fp3-stage{position:relative;flex:0 0 auto;height:clamp(240px,38vh,380px);border-radius:12px;overflow:hidden;border:1px solid var(--dsw-alias-border-l2);background:radial-gradient(120% 120% at 50% 30%, #151a24 0%, #0c0f15 72%);cursor:grab;touch-action:none;}',
          '.dsh-fp3-stage:active{cursor:grabbing;}',
          '.dsh-fp3-stage canvas{position:absolute;inset:0;width:100%;height:100%;display:block;}',
          '.dsh-fp3-hint{position:absolute;left:10px;bottom:8px;font-size:10.5px;line-height:1.5;color:rgba(190,205,235,.55);pointer-events:none;letter-spacing:0.02em;}',
          '.dsh-fp3-legend{position:absolute;right:10px;top:8px;display:flex;gap:10px;font-size:10.5px;line-height:1.5;pointer-events:none;color:rgba(226,232,240,.75);}',
          '.dsh-fp3-legend i{display:inline-block;width:7px;height:7px;border-radius:99px;margin-right:4px;vertical-align:1px;}',
          '.dsh-fp3-controls{display:grid;grid-template-columns:1fr 1fr auto;gap:14px;align-items:center;padding:10px 12px;border-radius:11px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb, var(--dsw-alias-label-primary) 1.5%, var(--dsw-alias-bg-base));}',
          '.dsh-fp3-slider{display:flex;flex-direction:column;gap:4px;min-width:0;}',
          '.dsh-fp3-slider span{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;color:var(--dsw-alias-label-secondary);}',
          '.dsh-fp3-slider b{font-weight:600;color:var(--dsw-alias-label-primary);font-variant-numeric:tabular-nums;}',
          '.dsh-fp3-slider input{width:100%;margin:0;accent-color:var(--dsw-alias-link);}',
          '.dsh-fp3-reset{appearance:none;padding:5px 11px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font-family:inherit;font-size:12px;cursor:pointer;white-space:nowrap;}',
          '.dsh-fp3-reset:hover{background:var(--dsw-alias-interactive-bg-hover);}',
          '.dsh-fp3-panel{border-radius:11px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);padding:12px 14px;display:flex;flex-direction:column;gap:8px;}',
          '.dsh-fp3-caption{font-size:11px;letter-spacing:0.06em;color:var(--dsw-alias-label-tertiary);}',
          '.dsh-fp3-matrix{display:grid;grid-template-columns:56px repeat(3,minmax(0,1fr));gap:5px 10px;font-family:var(--dsw-font-mono, ui-monospace, Consolas, monospace);font-size:12px;}',
          '.dsh-fp3-matrix .h{color:var(--dsw-alias-label-tertiary);font-size:11px;text-align:right;padding-right:14px;}',
          '.dsh-fp3-matrix .cell{padding:2px 14px 2px 0;text-align:right;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-primary);}',
          '.dsh-fp3-tau{display:flex;flex-wrap:wrap;gap:14px;font-family:var(--dsw-font-mono, ui-monospace, Consolas, monospace);font-size:12px;color:var(--dsw-alias-label-secondary);}',
          '.dsh-fp3-tau b{color:var(--dsw-alias-label-primary);font-weight:600;}',
          '.dsh-fp3-lens{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;}',
          '.dsh-fp3-len{display:flex;flex-direction:column;gap:2px;font-family:var(--dsw-font-mono, ui-monospace, Consolas, monospace);font-size:11.5px;}',
          '.dsh-fp3-len em{font-style:normal;font-size:11px;color:var(--dsw-alias-label-tertiary);}',
          '.dsh-fp3-len span{color:var(--dsw-alias-label-secondary);}',
          '.dsh-fp3-len span.ok{color:var(--dsw-alias-state-success-primary);}',
        ].join('');

        /** Sidebar artwork for the scene panel: an isometric cube. */
        function Scene3DIcon(props) {
          const size = typeof props.size === 'number' && props.size > 0 ? props.size : 20;
          return h(
            'svg',
            {
              viewBox: '0 0 24 24',
              width: size,
              height: size,
              fill: 'none',
              stroke: 'currentColor',
              strokeWidth: 1.7,
              strokeLinecap: 'round',
              strokeLinejoin: 'round',
              'aria-hidden': true,
              focusable: false,
              style: { display: 'block' },
            },
            h('path', { d: 'M12 3.2l7.5 4.3v9l-7.5 4.3-7.5-4.3v-9z' }),
            h('path', { d: 'M4.5 7.5L12 11.8l7.5-4.3M12 11.8V20.8' }),
          );
        }

        /** 2×3 lever-arm table: header row, then roll/pitch rows. */
        function matrixCells(readout, fmt) {
          const cells = [
            h('span', { key: 'h0', className: 'h' }),
            h('span', { key: 'h1', className: 'h' }, 'C1'),
            h('span', { key: 'h2', className: 'h' }, 'C2'),
            h('span', { key: 'h3', className: 'h' }, 'C3'),
          ];
          ['roll', 'pitch'].forEach((row, rowIndex) => {
            cells.push(h('span', { key: row, className: 'h' }, row));
            [0, 1, 2].forEach((column) => {
              cells.push(
                h(
                  'span',
                  { key: row + column, className: 'cell' },
                  readout ? fmt(readout.R[rowIndex][column], 3) : '—',
                ),
              );
            });
          });
          return cells;
        }

        function Scene3D() {
          const { language } = useLocale();
          const text = TEXT_3D[language];
          const canvasRef = React.useRef(null);
          const viewRef = React.useRef(null);
          const dragRef = React.useRef(null);
          const [thetaR, setThetaR] = React.useState(0);
          const [thetaP, setThetaP] = React.useState(0);
          const [ready, setReady] = React.useState(false);

          React.useEffect(() => {
            const canvas = canvasRef.current;
            if (!canvas) return undefined;
            const view = createWristView(canvas);
            viewRef.current = view;
            view.resize();
            setReady(true);
            let observer;
            const host = canvas.parentElement;
            if (typeof ResizeObserver === 'function' && host) {
              observer = new ResizeObserver(() => view.resize());
              observer.observe(host);
            }
            return () => {
              if (observer) observer.disconnect();
              viewRef.current = null;
              setReady(false);
            };
          }, []);

          React.useEffect(() => {
            const view = viewRef.current;
            if (!view) return;
            view.state.tr = (thetaR * Math.PI) / 180;
            view.state.tp = (thetaP * Math.PI) / 180;
            view.render();
          }, [thetaR, thetaP, ready]);

          const onPointerDown = (event) => {
            dragRef.current = { x: event.clientX, y: event.clientY };
            if (event.currentTarget.setPointerCapture) {
              event.currentTarget.setPointerCapture(event.pointerId);
            }
          };
          const onPointerMove = (event) => {
            const drag = dragRef.current;
            const view = viewRef.current;
            if (!drag || !view) return;
            view.state.azUser += (event.clientX - drag.x) * 0.006;
            view.state.elUser = Math.max(
              -0.22,
              Math.min(0.85, view.state.elUser - (event.clientY - drag.y) * 0.005),
            );
            drag.x = event.clientX;
            drag.y = event.clientY;
            view.render();
          };
          const onPointerUp = () => {
            dragRef.current = null;
          };
          const resetView = () => {
            const view = viewRef.current;
            if (!view) return;
            view.state.azUser = 0;
            view.state.elUser = 0;
            view.render();
          };

          const readout = React.useMemo(() => {
            const view = viewRef.current;
            if (!view || !ready) return null;
            return view.readout((thetaR * Math.PI) / 180, (thetaP * Math.PI) / 180);
          }, [thetaR, thetaP, ready]);

          const fmt = (value, digits) => (Math.abs(value) < 5e-4 ? 0 : value).toFixed(digits);

          return h(
            'div',
            { className: 'dsh-fp3' },
            h('style', { key: 'scene-styles' }, CSS_3D),
            h(
              'header',
              { className: 'dsh-fp3-head' },
              h(
                'div',
                { className: 'dsh-fp3-headmain' },
                h('p', { className: 'dsh-fp3-eyebrow' }, text.eyebrow),
                h('h1', { className: 'dsh-fp3-title' }, text.title),
                h('p', { className: 'dsh-fp3-sub' }, text.sub),
              ),
            ),
            h(
              'div',
              { className: 'dsh-fp3-scroll' },
              h(
                'div',
                {
                  className: 'dsh-fp3-stage',
                  onPointerDown: onPointerDown,
                  onPointerMove: onPointerMove,
                  onPointerUp: onPointerUp,
                  onPointerCancel: onPointerUp,
                  onDoubleClick: resetView,
                },
                h('canvas', { ref: canvasRef }),
                h('span', { className: 'dsh-fp3-hint' }, text.drag),
                h(
                  'span',
                  { className: 'dsh-fp3-legend' },
                  ['#22d3ee', '#a78bfa', '#fbbf24'].map((color, index) =>
                    h('span', { key: color }, h('i', { style: { background: color } }), 'C' + (index + 1)),
                  ),
                ),
              ),
              h(
                'div',
                { className: 'dsh-fp3-controls' },
                h(
                  'label',
                  { className: 'dsh-fp3-slider' },
                  h('span', null, text.thetaR, h('b', null, thetaR.toFixed(1) + '°')),
                  h('input', {
                    type: 'range',
                    min: -25,
                    max: 25,
                    step: 0.5,
                    value: thetaR,
                    onChange: (event) => setThetaR(Number(event.target.value)),
                  }),
                ),
                h(
                  'label',
                  { className: 'dsh-fp3-slider' },
                  h('span', null, text.thetaP, h('b', null, thetaP.toFixed(1) + '°')),
                  h('input', {
                    type: 'range',
                    min: -25,
                    max: 45,
                    step: 0.5,
                    value: thetaP,
                    onChange: (event) => setThetaP(Number(event.target.value)),
                  }),
                ),
                h(
                  'button',
                  {
                    type: 'button',
                    className: 'dsh-fp3-reset',
                    onClick: () => {
                      setThetaR(0);
                      setThetaP(0);
                      resetView();
                    },
                  },
                  text.zero,
                ),
              ),
              h(
                'section',
                { className: 'dsh-fp3-panel' },
                h('span', { className: 'dsh-fp3-caption' }, text.matrix),
                h('div', { className: 'dsh-fp3-matrix' }, matrixCells(readout, fmt)),
                h(
                  'div',
                  { className: 'dsh-fp3-tau' },
                  h('span', null, text.torque),
                  h('span', null, 'τ roll ', h('b', null, readout ? fmt(readout.tau[0], 1) : '—')),
                  h('span', null, 'τ pitch ', h('b', null, readout ? fmt(readout.tau[1], 1) : '—')),
                ),
              ),
              h(
                'section',
                { className: 'dsh-fp3-panel' },
                h('span', { className: 'dsh-fp3-caption' }, text.lengths),
                h(
                  'div',
                  { className: 'dsh-fp3-lens' },
                  (readout ? readout.lengths : []).map((row) =>
                    h(
                      'div',
                      { key: row.name, className: 'dsh-fp3-len' },
                      h('em', null, row.name),
                      h('span', null, text.geo + ' ' + row.geo.toFixed(3)),
                      h('span', null, text.closed + ' ' + row.closed.toFixed(3)),
                      h('span', { className: 'ok' }, text.diff + ' ' + row.diff.toExponential(1)),
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        ctx.slots.inject('sidebar.panellist', () =>
          ctx.slots.register(
            {
              name: 'sidebar.panellist',
              id: PANEL_KEY,
              order: 20,
              label: () => TEXT[activeLanguage()].nav,
            },
            PanelIcon,
          ),
        );

        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: PANEL_KEY }, Panel));
      },
    };
  },
});
