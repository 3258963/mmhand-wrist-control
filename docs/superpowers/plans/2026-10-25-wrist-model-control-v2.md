# 腕部解析模型前馈控制 v2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把腕部闭环从「手填 6 个 counts/° 常数系数」升级为「解析模型绳长前馈 + R 矩阵 P 校正」，核心代码全部纯函数、与 C 一一对应，可逐行移植 STM32。

**Architecture:** 三层纯函数模块：`wrist_model.py`（几何核心，镜像 H7 包 wrist_r.c 的稳定投影式）→ `wrist_control_law.py` v2（控制律，v1 原样保留）→ `wrist_filter.py`（中值5+EMA，从 mmhand_scope.py 抽出）。`mmhand_scope.py` 只做薄适配（载标定 + 开关 + 状态显示）。STM32 侧 = H7 包 `wrist_r.c`/`wrist_default_model.c` 原样 + 本计划 Python 文件的逐行 C 翻译。

**Tech Stack:** Python 3.12 标准库 + pytest（PC 参考实现与测试）；C99（移植目标 STM32H7，本计划只锁定接口与移植清单，不写 C）。

**Spec:**
- `E:\SLAHAND\mmhand_wrist_control_1.0\徐钰公式推导\2026-10-22\绳驱二轴腕部_解析公式.pdf`（v2.0，公式口径来源）
- `E:\SLAHAND\mmhand_wrist_control_1.0\徐钰公式推导\H7_腕部R实时算法_20261022\H7_腕部R实时算法_20261022\`（wrist_r.c / wrist_default_model.c / data/derived_constants.json / data/R_grid_corrected.csv / README_先读.md）
- `docs/控制算法与标定.md`（P4 链路语境）；`wrist_control_law.py`（v1 现状，文件头含 C 结构体建议）
- 本计划上游：2026-10-25 会话中交付的六阶段 PLAN（本计划实现其阶段 1+3 的代码部分；阶段 2 标定数据采集另行）
- 2026-10-25 用户确认可用输入：PITCH/ROLL 轴角度、**电机编码器值（M27-29）**、**当前绳张力**——张力使能 τ=Rf 观测与张力守卫，力矩层从「暂缓」升级为「可部分实施」
- 2026-10-25 用户确认三项口径：①J16/J17 关节磁编继续作角度反馈，电机编码器用于标定/绳滑监测；②张力用**独立拉力传感器**（应变片/采集盒，非帕西尼）；③张力经**独立串口到 PC**，上位机解析（复用 S3 触觉串口的 UI 模式）。仍待定：采集盒帧格式/波特率——以原始字节日志兜底，捕获后离线定帧再补解码器

## Global Constraints

- 纯函数模块：无 Qt / 串口 / 全局可变状态 / 动态分配（C 侧还禁递归、禁硬件访问）。
- 角度单位：**控制律接口一律 deg，模型内部 rad，deg→rad 转换只在控制律入口做一次**。R 输出按 rad 求导，数值单位 m（τ=R·f，f 单位 N）。
- 零偏只校正一次：`θ_model = θ_rel + δ`；**基线零位（PC angle_baseline）被假设为模型零位**，δ 是二者偏差，只能来自机械基准（不得与 β/γ 一起拟合）。
- `k_i` 符号约定：**counts 增大 ⟺ 绳放长**（缆长增大 → 电机放绳 → counts 增）。每电机符号由台架点动确认后写入标定。
- 几何常数取自 H7 包 `data/derived_constants.json`（source_sha256=952e9c40…），**不手抄小数**：把 JSON 数值原样嵌入常量表并在注释注明来源与 SHA。
- 本目录**不是 git 仓库**：各任务以「自查清单」代替 commit 步骤，列明新建/修改的文件。
- H7 包内文件一律不改；不改 `calibration_confirmed`/`guards_confirmed`（默认 false 是设计行为）。
- 不引用 PDF 印刷式 (27)/(S4)（已确认印刷符号错误），一律用通式 (22)(23) 或固件投影式。
- 每任务完成标准：`​.venv/Scripts/python.exe -m pytest tests/ -v` 全绿 + `python wrist_control_law.py` 自测通过。

## Review Focus

1. **deg 当 rad 喂模型**（差 57.3 倍）→ 期望：1° 目标在 k=1e5 c/m 下前馈约 ±39 counts，而不是数千。→ Task 2 golden 测试。
2. **δ / 基线双重校正**（θ 已减过基线又减一次，或 δ 加两次）→ 期望：θ=0、目标 0 时输出恒等于 origin，与 δ 取值无关。→ Task 2 不变性测试。
3. **C1/pitch 短段低置信区**（≤−24°，s≈3.9mm）→ 期望：pitch 目标 −25 被钳到 −24 并置标志，控制不进入未验证区。→ Task 2 钳制测试。
4. **NaN/Inf 输入** → 期望：返回错误标志且 out 不可用，调用方保持上一目标（绝不发送 origin 导致运动）。→ Task 2 nonfinite 测试。
5. **溢出/越界**（增益异常大、目标超程）→ 期望：输出钳到 origin±5000、目标钳到模型行程∩限幅，均有标志。→ Task 2 软限位/钳制测试。
6. **张力样本过期/断流/负值/非有限** → 期望：守卫不得用旧数据做安全判断，置 TENSION_STALE 且 τ/预紧为 NaN，不误报松绳/过载。→ Task 5 stale 测试。

---

## 数据流与状态总表（实现前先读）

### 输入量（每个控制周期）

| 输入 | 来源 | 单位/形式 | 说明 |
|---|---|---|---|
| roll_deg, pitch_deg | J16/J17 raw → `wrist_filter` → `_axis_deg` → Δ基线 | deg，相对基线零位（±180 最短角差） | 已滤波反馈角 |
| roll_tgt_deg, pitch_tgt_deg | UI 目标框 / 上位命令 | deg，相对基线 | 未钳制原值 |
| 电机编码器值 | M27-29 ABS 遥测（100Hz，现成） | counts（多圈 logical） | **闭环律不消费**；用于标定识别（Task 6）与绳滑健康监测（Δcounts 实测 vs k_i·Δl_model 残差） |
| 绳张力 f[3] | 独立拉力传感器 → 独立串口到 PC（已确认；帧格式待采集盒确定，先原始字节日志兜底） | N，float，3 缆 | 张力守卫（Task 5）+ τ=Rf 观测 + 标定时分离弹性/摩擦（Task 6） |
| p: WristControlParams | UI 快照 | origin[3] counts、kp、deadband_deg、target_limit_deg、soft_limit | gain_roll/gain_pitch 仅 v1 模式用 |
| calib: WristCalib | wrist_calib.json（载入一次） | k_counts_per_m[3]（带符号 c/m）、zero_offset_deg[2]（deg） | δ 来自机械基准 |
| 几何常量 | wrist_model.py 常量表 | m / rad | 6 段投影数 + 行程 + 门限，编译期/加载期固定 |

### 状态（谁拥有什么）

| 状态 | 拥有者 | 形式 | 生命周期 |
|---|---|---|---|
| 中值窗口 + EMA 值 ×2 轴 | `WristAxisFilter` 实例（PC 挂在 scope；STM32 挂在控制任务） | buf[5] + ema + primed | 使能时 reset |
| angle_baseline[2] | scope（STM32：任务上下文） | raw counts | 基准按键/闭环启动设定，持久化 |
| motor_origin[3] | scope（使能时刻 ABS 快照） | counts | 每次使能重置 |
| targets[3]（变更抑制） | scope | counts | 闭环期间维护 |
| wrist_calib | scope | WristCalib | 载入后不变 |
| 控制律本身 | **无内部状态**（参数快照模式，同 v1） | — | — |

### 每拍流程（v2 模型模式，100Hz）

1. J16/J17 raw → `WristAxisFilter.update()`（中值5+EMA，输入 raw counts，与 v1 语义一致）。
2. `_axis_deg` 加方向符号 → 减基线得 θ_rel（deg，±180 最短角差）。
3. 律入口一次 deg→rad；钳目标：roll 到 ±min(limit,25)，pitch 到 [max(−limit,−25), min(limit,45)] 再抬底到 −24（低置信区），置 FLAG_TARGET_CLAMPED / FLAG_LOW_PITCH。
4. 反馈角钳入模型行程（越界置 FLAG_FEEDBACK_CLAMPED）。
5. 有限性检查：任一输入 NaN/Inf → 返回 (None, FLAG_NONFINITE)，调用方保持上一目标。
6. 模型求值（3 次 `wrist_eval`）：目标位姿、基线位姿（θ=δ）各一次取 6 段长 → 前馈 `ff_i = k_i·[(s_r(θr_t)+s_p(θp_t)) − (s_r(δr)+s_p(δp))]`；反馈位姿一次取 R → 校正 `corr_i = −kp·k_i·(R_ri·e_r_rad + R_pi·e_p_rad)`（e 过死区）。math_valid=False → (None, FLAG_GEOM_INVALID)。
7. `value_i = origin_i + ff_i + corr_i` → float 钳 origin±soft_limit → int(round) → int 再钳。
8. 张力守卫（Task 5，有张力源后启用）：最新 f[3] 样本年龄 ≤ max_age_ms，任一缆 ≥ f_max → 置 TENSION_OVERLOAD 并停止闭环（走断链退出路径）；< f_min 松绳仅提示；样本过期/非有限 → TENSION_STALE，本拍不做安全判断。
9. 调用方按标志组装状态文本（10Hz），变更抑制后发送 0xDE。

### 失败语义

| 条件 | 行为 |
|---|---|
| 输入非有限 | (None, FLAG_NONFINITE)，调用方不发送 |
| math_valid=False（D≤0/段长低于数值下限） | (None, FLAG_GEOM_INVALID)，调用方不发送 |
| 目标出模型行程/限幅/低置信区 | 钳制后继续，置对应 FLAG |
| 标定未载入但模型模式开 | UI 层拒绝启动闭环（显式提示，不静默回退） |

---

### Task 1: `wrist_model.py` 几何核心

**Files:**
- Create: `wrist_model.py`
- Create: `tests/test_wrist_model.py`
- Copy: `E:\SLAHAND\mmhand_wrist_control_1.0\徐钰公式推导\H7_腕部R实时算法_20261022\H7_腕部R实时算法_20261022\data\R_grid_corrected.csv` → `tests/fixtures/R_grid_corrected.csv`

**Interfaces:**
- Consumes: 无（叶子模块）。
- Produces（Task 2 依赖，名字与类型照此）:
  - `ROLL=0`、`PITCH=1`、`N_CABLES=3`
  - `SEG_PROJ_M[axis][cable] = (u1,u2,v1,v2,h)`，单位 m，6 组
  - `RANGE_DEG = {ROLL:(-25.0,25.0), PITCH:(-25.0,45.0)}`、`LOW_PITCH_LIMIT_DEG=-24.0`、`NUMERICAL_MIN_LENGTH_M=1e-8`
  - `class WristModelOut`：字段 `r_m[2][3]`、`s_m[2][3]`、`math_valid: bool`、`low_pitch_zone: bool`、`angle_in_range: bool`
  - `def wrist_eval(roll_rad: float, pitch_rad: float) -> WristModelOut`
  - `def positive_null_direction(roll_rad: float, pitch_rad: float) -> tuple[float, float, float] | None`：R 两行叉积、必要时整体翻号取全正、归一化；范围内无全正方向返回 None（Task 5 预紧观测依赖）
  - 单段函数 `_segment_length_and_arm(theta_rad, axis, cable) -> (s, r)` 仅为模块内部实现细节（下划线私有，后续任务不直接依赖）

- [ ] **Step 1: 写失败测试 `tests/test_wrist_model.py`**

测试 A（零位解析矩阵，逐位）：`(0,0)` 处 `wrist_eval` 的 `r_m` 与文档零位矩阵一致（单位 m）：
roll 行 `[-0.25943726e-3, -22.04970101e-3, 17.37198247e-3]`，pitch 行 `[-58.10461556e-3, 11.80488412e-3, 10.99035112e-3]`，绝对容差 `1e-8`；并断言 `math_valid=True`、`angle_in_range=True`。

测试 B（全网格对拍 3,621 姿态）：逐行读 `tests/fixtures/R_grid_corrected.csv`（列 `yaw_deg,pitch_deg,L1_m,R_yaw_C1_m,R_pitch_C1_m,L2_m,…,L3_m,R_yaw_C3_m,R_pitch_C3_m,rank2,positive_null,condition`；注意 pitch=0 写作 `-0.0`），对每行：
- `yaw_deg`↔`ROLL`、`pitch_deg`↔`PITCH`；
- 6 个 `R_yaw/R_pitch` 列与 `r_m` 逐项比，绝对容差 `3.5e-5`（该 CSV 是 0.2° 差分参考表，已知最大截断 0.0327mm 在 pitch/C1，见解析公式 PDF 第 8 节——**不得**把该差当作模型误差）；
- 缆长增量：`(L_k(row) − L_k(0,0行))` vs `[(s_r+s_p)(row) − (s_r+s_p)(0,0行)]`，容差同上；
- 每行 `math_valid=True`；`pitch≤-24` 行 `low_pitch_zone=True`；
- `positive_null` 列与 `positive_null_direction(...) is not None` 逐行一致（H7 报告口径：3,621/3,621 一致，其中 1,664 行为 None）。
测试 C（零位零空间方向）：`positive_null_direction(0,0)` ≈ `(0.2644, 0.5949, 0.7590)`，各分量容差 `1e-3`（已用真实常数预验证）。
测试文件 docstring 记录 CSV 的 SHA256。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_model.py -v`
Expected: FAIL，`ModuleNotFoundError: wrist_model`

- [ ] **Step 3: 实现 `wrist_model.py`**

常量表：从 `derived_constants.json` 的 `segments[].plane_coefficients_m` 原样嵌入 6 组 `(u1,u2,v1,v2,h)`（注释：来源 JSON 与 source_sha256，不手改小数）。
算法 = H7 包 `算法说明.md` 固件稳定投影式（每段）：
`v'1=v1·cosθ−v2·sinθ；v'2=v1·sinθ+v2·cosθ；d1=v'1−u1；d2=v'2−u2；s=√(d1²+d2²+h²)；r=(d1·v'2−d2·v'1)/s`。
roll 三段用 θr 求值、pitch 三段用 θp；`math_valid = 所有 s>NUMERICAL_MIN_LENGTH_M 且结果有限`；`low_pitch_zone = pitch≤radians(-24)`；`angle_in_range` 按 `RANGE_DEG`。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_model.py -v`
Expected: PASS（若网格测试超 1s 可给该测试打 `@pytest.mark.slow`，仍默认执行）

- [ ] **Step 5: 自查清单（代替 commit）**

新建 `wrist_model.py`、`tests/test_wrist_model.py`、`tests/fixtures/R_grid_corrected.csv`；无其他文件改动；常量数值与 JSON 逐段核对一遍（6×5 个数）。

---

### Task 2: `wrist_control_law.py` v2 控制律

**Files:**
- Modify: `wrist_control_law.py`（**追加**，v1 函数与自测一行不动）
- Create: `tests/test_wrist_control_law.py`

**Interfaces:**
- Consumes: Task 1 全部 Produces（`import wrist_model`）。
- Produces（Task 4 依赖）:
  - `class WristCalib`：`__init__(self, k_counts_per_m: list[float], zero_offset_deg: list[float])`；`k_counts_per_m` 长 3 带符号（c/m），`zero_offset_deg` 长 2（δr, δp，deg）
  - 标志位：`FLAG_OK=0`、`FLAG_TARGET_CLAMPED=1<<0`、`FLAG_LOW_PITCH=1<<1`、`FLAG_FEEDBACK_CLAMPED=1<<2`、`FLAG_GEOM_INVALID=1<<3`、`FLAG_NONFINITE=1<<4`
  - `def wrist_control_step_model(p: WristControlParams, calib: WristCalib, roll_deg: float, pitch_deg: float, roll_tgt_deg: float, pitch_tgt_deg: float) -> tuple[list[int] | None, int]`
  - 文件头 docstring 追加 v2 的 C 结构体建议：`wrist_calib_t`、`int wrist_control_step_model_c(const wrist_control_params_t*, const wrist_calib_t*, float roll_deg, float pitch_deg, float roll_tgt_deg, float pitch_tgt_deg, int32_t out[3])`（返回 status，out 仅在无错误标志时有效）

- [ ] **Step 1: 写失败测试 `tests/test_wrist_control_law.py`**

公共夹具：`p = WristControlParams()`，`origin=[1000,2000,3000]`，`kp=0.0`，`deadband=0.3`，`limit=25`，`soft_limit=5000`；`calib = WristCalib([1e5,1e5,1e5],[0,0])`（1e5 c/m 便于手算）。

1. `test_golden_feedforward`：反馈 (0,0)、目标 (1°,0°)、kp=0 → C2=+39、C3=−30（`pytest.approx(x, abs=1)`；手算依据：C2/roll `s(1°)−s(0)=+0.3877mm`、C3/roll `−0.2965mm`，×1e5）。C1 断言 `approx(1, abs=1)`（0.555 counts 舍入边界）。
2. `test_delta_invariance`：`calib=WristCalib([1e5,1e5,1e5],[2.0,0.0])`，反馈 (0,0)、目标 (0,0) → 输出恰为 `[1000,2000,3000]`、flags==FLAG_OK（基线参考取 δ 处段长，δ 不引起漂移）。
3. `test_correction_sign_and_gain`：同夹具但 kp=0.6，反馈 (0.5,0)、目标 (1,0)（e=0.5°>死区）→ C2 ≈ 50±2（ff 38.8 + corr ≈ +11.5，同号——校正把关节往目标方向继续推）。
4. `test_low_pitch_clamp`：目标 pitch=−25 → 输出与目标 pitch=−24 完全一致，且 `flags & FLAG_LOW_PITCH`。
5. `test_nonfinite`：目标 roll=NaN → `(None, ...)` 且 `flags & FLAG_NONFINITE`；反馈 pitch=inf 同。
6. `test_soft_limit`：k=[1e9,1e9,1e9]、目标 (25,45) → 每路输出 ∈ [origin−5000, origin+5000] 且被钳到边界（|out−origin|==5000）。
7. `test_target_range_clamp`：目标 (30, 50) →（limit=25 时）等价于 (25, 25) 的输出，`flags & FLAG_TARGET_CLAMPED`。
8. `test_v1_untouched`：`wrist_control_step` 四组旧断言仍通过（直接调用并以 v1 文件内 `__main__` 自测为准）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_control_law.py -v`
Expected: FAIL，`ImportError: cannot import name 'WristCalib'`

- [ ] **Step 3: 实现 `wrist_control_step_model` + `WristCalib`**

按「每拍流程」第 3–8 步实现；实现要点（签名与测试未决定的仅此四处）：
- deg→rad 只在入口转换一次：`roll_m = radians(roll_deg + δr)` 等 4 个量 + 误差 `radians(e)`；
- 模型求值 3 次：`wrist_eval(roll_m_t, pitch_m_t)`、`wrist_eval(δr_rad, δp_rad)`（前馈参考）、`wrist_eval(roll_m_fb, pitch_m_fb)`（取 R）；段长直接用 `wrist_eval` 返回的 `s_m`，不另调 `_segment_length_and_arm`；
- `FLAG_LOW_PITCH` 在最终 pitch 目标 ≤ −24° 时置位（含恰好 −24，进区即提示）；`FLAG_TARGET_CLAMPED` 仅在实际发生钳制时置位；
- 死区、钳制、舍入顺序与 v1 完全一致（误差死区 → float 钳 → int(round) → int 钳）。
- docstring 写明：k 符号约定、δ 唯一校正点、基线=模型零位假设。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_control_law.py tests/test_wrist_model.py -v && python wrist_control_law.py`
Expected: 全 PASS + `wrist_control_law 自测全部通过`

- [ ] **Step 5: 自查清单（代替 commit）**

v1 代码零改动（diff 仅追加）；6 个 FLAG 值互不冲突；docstring 的 C 签名与 Python 签名参数顺序一致；Review Focus 1–5 各有对应测试且全绿。

---

### Task 3: `wrist_filter.py` 滤波模块（可移植抽出）

**Files:**
- Create: `wrist_filter.py`
- Modify: `mmhand_scope.py`（`_encoder_filter_update` 内部改调模块，对外行为与 `_enc_filt_raw` 语义零变化）
- Create: `tests/test_wrist_filter.py`

**Interfaces:**
- Consumes: 无。
- Produces（Task 4 / STM32 依赖）:
  - `FILTER_MEDIAN_N=5`、`FILTER_ALPHA=0.03`（现值原样搬出，模块内定义，scope 引用它）
  - `class WristAxisFilter`：`reset() -> None`；`update(raw: float) -> float`
  - 语义与现 `_encoder_filter_update` 逐行为一致：预热期（窗口未满）直接返回 raw；窗口满后取中值，首拍返回中值本身，此后 `ema += ALPHA·(median−ema)`；**输入是 raw counts**（0..16383，跨 0/16383 绕回的行为与 v1 相同，注释标注此已知局限）。

- [ ] **Step 1: 写失败测试 `tests/test_wrist_filter.py`**

1. `test_prewarm_passthrough`：前 4 个样本原样返回。
2. `test_spike_rejected`：喂 100×4 后喂 1000 → 返回中值 100（EMI 尖峰不出现在输出）。
3. `test_ema_converge`：持续喂 100 → 输出单调趋近 100 且首拍==100。
4. `test_reset`：reset 后回到预热态。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_filter.py -v`
Expected: FAIL，`ModuleNotFoundError: wrist_filter`

- [ ] **Step 3: 实现 `wrist_filter.py` 并替换 scope 内部实现**

`mmhand_scope.py`：删除局部 `_enc_med_buf`/滤波逻辑，改为 `self._axis_filter = {16: WristAxisFilter(), 17: WristAxisFilter()}`；`_encoder_filter_update(j, raw)` 改为一行委托 `self._enc_filt_raw[j] = self._axis_filter[j].update(raw)`；`FILTER_MEDIAN_N/FILTER_ALPHA` 常量改从 `wrist_filter` 导入（其余引用点零改动）。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: 自查清单（代替 commit）**

`grep -n "_enc_med_buf\|FILTER_MEDIAN_N\|FILTER_ALPHA" mmhand_scope.py` 确认无残留旧实现；`_enc_filt_raw` 的消费端（闭环、大字、表格）未动。

---

### Task 4: `mmhand_scope.py` 模型前馈接入（最小改动）

**Files:**
- Modify: `mmhand_scope.py`
- 数据: `run_data/scope_exports/wrist_calib.json`（用户/标定流程生成，不入库；格式 `{"version":1,"k_counts_per_m":[...3],"zero_offset_deg":[...2],"saved_at":"..."}`）

**Interfaces:**
- Consumes: Task 2 的 `WristCalib`、`wrist_control_step_model`、FLAG_*、`parse_wrist_calib`（该函数定义在 `wrist_control_law.py`，见 Step 3）；Task 3 的 `WristAxisFilter`（已就位）。
- Produces: 无新接口（UI 行为变更）。

- [ ] **Step 1: 写失败测试（可离线验证的最小部分）**

`tests/test_wrist_control_law.py` 已覆盖律本身；scope 侧用导入级冒烟：`.venv/Scripts/python.exe -c "import mmhand_scope"`（无 Qt 环境下若因显示初始化失败，退化为 `ast.parse` 语法检查——二选一，写明用了哪个）。新增 `tests/test_wrist_calib_io.py`：用 `tmp_path` 构造合法/缺字段/负数 k 的 JSON，验证解析函数（见 Step 3：解析逻辑提为模块级纯函数 `parse_wrist_calib(data: dict) -> WristCalib`，非法返回 None 并带原因字符串）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_calib_io.py -v`
Expected: FAIL，`ImportError: cannot import name 'parse_wrist_calib'`（该函数暂放 `wrist_control_law.py`，与 UI 解耦）

- [ ] **Step 3: 实现接入**

1. `wrist_control_law.py` 追加 `parse_wrist_calib(data)`：校验 version/长度/有限性/`k!=0`（全零 k 无意义），非法返回 `(None, 原因)`；**不用裸 except 吞错**（历史教训：静默失败掩盖持久化问题）。
2. 闭环面板追加：按钮「📥 载入标定」→ `load_named_json("wrist_calib.json")` → `parse_wrist_calib` → 成功存 `self.wrist_calib` 并在状态行回显 k/δ 数值；失败显式提示原因。复选框「模型前馈」仅在 `self.wrist_calib` 非空时 enable。
3. `_cl_tick` 分支：模型模式且标定有效 → 调 `wrist_control_step_model`，按返回 flags 在 10Hz 状态行追加「低pitch区/目标钳制/反馈钳制/几何无效(本拍未发)」；否则走 v1 原路径。变更抑制、软限位、斜坡、急停语义全部复用不变。
4. 模型模式运行中：6 个系数框 `setEnabled(False)`，停止时恢复。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v` + 冒烟检查
Expected: 全 PASS

- [ ] **Step 5: 台架人工验收清单（代替 commit，逐项打勾）**

1. 未载标定勾「模型前馈」→ 拒绝启动，有明确提示；
2. 载入 `{"k":[+1e5,+1e5,+1e5],"δ":[0,0]}` → 目标 (0,0) 闭环 → M27-29 不动（不动性）；
3. k 改正负号各试一次 → 小目标阶跃方向正确（k 符号=卷绕方向，确认后写死进 wrist_calib.json）；
4. pitch 目标 −25 → 实际按 −24 执行且状态行有低 pitch 提示；
5. 急停/断链/拔磁编 → 闭环自动退出，行为与 v1 一致；
6. 全程 ±25° 扫一遍，与 v1 手填系数模式对比跟踪误差并记录到 `run_data/`。

---

### Task 5: `wrist_tension.py` 张力守卫与 τ=Rf 观测

> **接口已确认（2026-10-25）**：独立拉力传感器 + 独立串口到 PC，上位机解析（复用 S3 触觉串口的「选择/连接/断开/状态」UI 模式）。仍未知：采集盒帧格式与波特率——不阻塞：先做纯函数（输入 3 个 N 值 + 样本年龄）与**原始字节日志模式**，采集盒上线后抓一段原始字节离线定帧，再补帧解码器。

**Files:**
- Create: `wrist_tension.py`
- Create: `tests/test_wrist_tension.py`
- Modify: `mmhand_scope.py`（张力串口 UI + 原始字节日志 + 守卫/显示接线；帧解码器待采集盒帧格式确认后补）

**Interfaces:**
- Consumes: Task 1 的 `wrist_eval`、`positive_null_direction`。
- Produces（scope 接线 / STM32 移植依赖）:
  - `class TensionConfig`：`f_min_n: float`、`f_max_n: float`（**无默认值**，由用户实测后给定，不得编造）、`max_age_ms: float = 300.0`（对齐 P4 磁编样本 300ms 年龄口径）
  - 标志（独立命名空间，不与控制律 FLAG_* 混用）：`TENSION_OK=0`、`TENSION_STALE=1<<0`、`TENSION_SLACK=1<<1`、`TENSION_OVERLOAD=1<<2`
  - `class TensionEval`：`flags: int`、`tau_roll_nm: float`、`tau_pitch_nm: float`、`preload_n: float`、`slack: list[bool]`（3）、`overload: list[bool]`（3）
  - `def tension_evaluate(f_n: list[float], age_ms: float, cfg: TensionConfig, roll_rad: float, pitch_rad: float) -> TensionEval`

- [ ] **Step 1: 写失败测试 `tests/test_wrist_tension.py`**

夹具：`cfg = TensionConfig(f_min_n=0.5, f_max_n=50.0)`（测试自定数值，仅测逻辑）。
1. `test_tau_from_r`：零位、`f=(1,2,3)` N、age=10 → `tau_roll_nm ≈ +0.007757`、`tau_pitch_nm ≈ −0.001524`（容差 1e-6；τ=R(0)·f，R 单位 m，已预验证）。
2. `test_preload`：同上 → `preload_n ≈ 3.7314`（f·n̂，容差 1e-3）。
3. `test_slack_overload`：f=(0.1, 2, 60) → `slack=[True,False,False]`、`overload=[False,False,True]`、flags 含 SLACK|OVERLOAD。
4. `test_stale`：age=400（>300）→ flags 仅 STALE，τ/预紧为 NaN，slack/overload 全 False（旧数据不做安全判断）。
5. `test_invalid_samples`：f 含 NaN、负值、inf 三种 → 同 STALE 行为。
6. `test_no_null_direction`：取网格中任一 `positive_null=False` 的姿态（如 (−25°,−25°)）→ `preload_n` 为 NaN，但 `tau` 仍正常计算（τ 不依赖零空间）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_wrist_tension.py -v`
Expected: FAIL，`ModuleNotFoundError: wrist_tension`

- [ ] **Step 3: 实现 `wrist_tension.py`**

有限性/年龄/负值检查先行（任一命中 → STALE 短路返回）；`wrist_eval` 取 R 与 `math_valid`（False → 同 STALE 短路）；τ=R·f；`n = positive_null_direction(...)`，非 None 时 `preload_n = f·n`，None 时 NaN；逐缆 f<cfg.f_min_n → slack、> cfg.f_max_n → overload。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: scope 接线（复用触觉串口模式）**

1. 张力串口 UI：下拉选择串口 + 连接/断开 + 状态提示，复用 S3 触觉串口面板的既有模式与线程结构；解析线程把原始字节写入 `run_data/tension_raw_<时间戳>.log`（十六进制，兜底定帧用），帧格式确认后在此处补 `TensionFrameDecoder`（模块级纯函数，可单测）。
2. 解码出的 `f[3]` + 时间戳进 channels 缓冲（新增 `tension_f1/f2/f3` 三个曲线通道，可勾选绘制；「腕部调试」预设追加这三个通道），并记录最新样本到达时间供年龄计算。
3. 闭环运行中每拍用最新样本调 `tension_evaluate`（串口未连接时跳过，行为与现状一致）：TENSION_OVERLOAD → 走断链退出路径停止闭环并在状态行点名超限缆；SLACK/STALE → 10Hz 状态行提示。闭环面板增加 τ_roll/τ_pitch 与三缆张力只读显示（10Hz）。

- [ ] **Step 6: 自查清单（代替 commit）**

TENSION_* 与 FLAG_* 命名空间独立；无张力源时 scope 行为与现状完全一致（回归：不接传感器跑 v1 闭环正常）；Review Focus 6 有钉住测试。

---

### Task 6: 标定数据记录与 k_winch 离线识别（被动记录，不做向导）

> 定位：纯工具链。记录器只被动写 CSV，不驱动电机（沿用 2026-10-22 决定：不做自动点动标定向导）。识别在离线脚本完成。

**Files:**
- Modify: `mmhand_scope.py`（闭环面板加「⏺ 记录标定数据」开关；运行中每拍追加一行）
- Create: `tools/identify_wrist_calib.py`
- Create: `tests/test_identify_wrist_calib.py`
- 数据: `run_data/scope_exports/wrist_calib_capture_<时间戳>.csv`

**Interfaces:**
- Consumes: Task 1 `wrist_model`；Task 5 张力列（可缺省）。
- Produces:
  - CSV 行格式：`t_s, roll_deg, pitch_deg, m27_abs, m28_abs, m29_abs, f1_n, f2_n, f3_n`（张力未接时空列）
  - `tools/identify_wrist_calib.py <capture.csv> [--write]`：输出每电机 k̂（counts/m）、counts 残差 RMSE/95% 分位/最大差、正/返程中位差（迟滞）；`--write` 生成 `wrist_calib.json` 草案（k_counts_per_m + zero_offset_deg 占位 0，注明待机械基准）
  - 可导入纯函数 `fit_k_counts_per_m(d_l: list[float], d_counts: list[float]) -> float`：最小二乘 `Σ(Δl·Δc)/Σ(Δl²)`，Σ(Δl²)<1e-12 时抛 ValueError（退化输入不得静默返回 0）

- [ ] **Step 1: 写失败测试 `tests/test_identify_wrist_calib.py`**

1. `test_fit_recovers_known_k`：合成 200 点，Δl 均匀取 [−4,+4] mm，k=1e5，Δc=k·Δl+噪声(σ=5 counts，固定种子) → `fit_k_counts_per_m` 结果与 1e5 相对误差 < 1%。
2. `test_fit_degenerate_raises`：全零 Δl → pytest.raises(ValueError)。
3. `test_hysteresis_split`：合成正/返程两段各带 +3 counts 偏置 → 报告的正返程中位差 ≈ 3 counts（容差 1）。
4. `test_missing_tension_column`：无 f 列的 CSV 也能完成 k 识别（张力列可选）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_identify_wrist_calib.py -v`
Expected: FAIL，`ModuleNotFoundError: identify_wrist_calib`（tools 无 `__init__` 时直接以文件路径 import 或加 conftest path，写明采用哪种）

- [ ] **Step 3: 实现记录开关与识别脚本**

记录开关：勾选时每拍（100Hz 全量，不做抽稀）追加一行 CSV，用 `mmhand_scope_export.dump_csv` 现有导出通道；停止勾选或退出闭环时收尾。识别脚本：读 CSV → 相对首行求 Δ → 逐电机 `fit_k_counts_per_m` → 残差统计 → 打印报告 + `--write` 出 JSON 草案。zero_offset_deg 不在数据里识别（δ 与 β/γ 相位耦合，必须外部机械基准——脚本输出中固定写 0 并注明）。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: 台架人工验收（代替 commit）**

慢速手动扫 roll 单轴一个往返 + pitch 单轴一个往返（低/中两档预紧各一次），确认 CSV 行数、数值合理；跑识别脚本，k̂ 三值符号一致且残差 RMSE 记入 `run_data/`；k̂ 与手填系数换算对比（k_i ≈ 手填 gain_i / (R_i(0)·π/180) 量级核对）。识别结果经用户确认后才写入正式 `wrist_calib.json`。

---

## STM32 移植清单（本计划不写 C，接口已锁死）

**文件映射**（Python ↔ C 一一对应）：

| PC (Python) | STM32 (C) | 说明 |
|---|---|---|
| `wrist_model.py` | 直接复用 H7 包 `src/wrist_r.c` + `src/wrist_default_model.c`（不改） | Python 版是其数学镜像；律只消费 R 与段长，秩/条件数/零空间诊断由 wrist_r 附带算出，位置级控制暂不消费（力矩层再启用） |
| `wrist_control_law.py` v2 | 新建 `wrist_control_v2.c/.h` | 按 docstring 中 `wrist_calib_t`/`wrist_control_step_model_c` 逐行翻译 |
| `wrist_filter.py` | 新建 `wrist_filter.c/.h` | 定长数组，无堆 |
| `wrist_tension.py` | 新建 `wrist_tension.c/.h` | 纯函数，不依赖张力传输层；张力样本年龄由调用方传参 |
| `mmhand_scope.py` 适配层 | 控制任务（拥有滤波状态/origin/targets/参数双缓冲/最新张力样本） | 调用方持有全部状态，律与守卫无状态 |

**编译与运行规则**（源自 H7 README，逐条遵守）：
- C99；`-O2 -ffp-contract=off`，显式禁用 `-ffast-math` 与 `-ffinite-math-only`（否则 NaN/Inf 检查失效）；FPU/浮点 ABI 与工程一致。
- 数学库 `sinf/cosf/sqrtf/isfinite`；换 CMSIS-DSP 时逐个 API 核实角度单位与精度，不得凭函数名猜。
- 完整 API 用 DWT/CYCCNT 计时取最大值（覆盖 Cache 冷热与中断负载）；先确认计数器已启用，不得把 0 当耗时。
- 跨任务/ISR 发布结果用双缓冲或临界区，消费者不得读到半写矩阵；更新参数不得与求值并发。
- 状态所有权：滤波器、origin、targets、标定参数都在控制任务上下文；`wrist_control_step_model_c` 本身无静态可变状态。

**上板验证顺序**：主机 Python 与板端对拍（同 100 组角度输入，比 R 与 out 逐项 ≤1e-4 mm 量级 float 差）→ DWT 计时报告 → 台架重复 Task 4 Step 5 清单。
