# PLAN v6：绳状态徽章 + 逐缆状态章 + 一键紧/松绳 + 张紧地板 + 阈值单源

> 版本：v6（v5 审阅修正版；v5 作者=并行会话，审阅=本会话）
> 日期：2026-11-03
> 范围：PC 上位机 `mmhand_scope.py`、`wrist_force_law.py`、测试
> 前提：运行中松绳分级守卫/看门狗已按用户决定删除；守卫维持"松绳仅⚠、过载停环"；不动 α/TDA/增量律。

---

## 0. 一页结论

v5 审阅裁定：P0-1/3/5 照单全收；P0-2 采纳公式（当前配置下与统一−2500等价，一劳永逸）；
**P0-4 采纳"清 integ/resid"但条件必须改**——v5 的 `trim_sign[i]*step<0` 在 sign=−1 时方向全反，
正确条件是 `step < 0`（推导见 §1.3）。另有三项代码实况核对结果并入（§1.4）。

---

## 1. 关键裁定与事实

### 1.1 v5 五个 P0 的裁定

| # | v5 指控 | 裁定 | v6 处置 |
|---|---|---|---|
| P0-1 恢复标志永不清 | 真 | ✅ 收 | 三缆进界连续 300ms 自动清 + 停环兜底 + 失败回滚清 |
| P0-2 松绳按 sign 算 | 真（潜伏） | ✅ 收 | `delta_i = -2500 × trim_sign[i]`；当前 1,1,1 下与统一−2500 等价 |
| P0-3 紧绳事务化 | 真 | ✅ 收 | backup → 校验 → 切换 → 启动 → 成功才置 flag；失败全回滚 |
| P0-4 地板清 integ/resid | 半真 | ⚠️ **修正** | 保留"清 step/integ/resid"；条件改 `step < 0`（v5 原条件在 sign=−1 时禁紧放反） |
| P0-5 阈值单源 | 真 | ✅ 收 | `_effective_flimits()` 显示/TDA/守卫三路共用；位置模式恢复过载停环 |

### 1.2 v5"已存在勿重复"清单核对（全部属实）

- 边界行六框已存在（`mmhand_scope.py:1960-1992`）；
- `_force_fmax()` 已单源读 `fmax_f`（`:3356`）；
- 缆卡着色已用 `v_abs` 绝对张力（`:906-913`）；
- `_tight_params` 未传 `f_min`（待 v6 加）；
- v5 迁移节"旧布局 f_min=−3000"与实际不符（实为 −5000，见 1.4），处置规则同步修正。

### 1.3 P0-4 方向推导（为何条件必须是 `step < 0`）

trim_sign 定义：`sign=+1 ⟺ counts↑ ⇒ 张力↑`，即 Δ张力方向 = sign × Δcounts 方向。

```
律内：trim(发出的 counts 步长) = sign × step
代入：Δ张力方向 = sign × (sign × step) = sign(step)
```

**结论：step>0 永远是紧、step<0 永远是放，与 trim_sign 无关。**

- v4 的 `e_i<0` 判方向其实正确（e<0→放松意图，任意 sign 成立）；真洞是只清 e 不清 integ/resid；
- v5 的 `sign×step<0` 在 sign=−1 电机上等价于 `step>0`——地板上把"紧"禁了、"放"放了，全反；
- 当前配置全 +1 时两者碰巧等价（潜伏 bug），但写进律里的必须是对的。

另：v5 提及的 "n_i<0" 场景不存在——`positive_null_direction` 保证返回 n̂ 全正或 None。

### 1.4 代码实况核对（2026-11-03，三项新事实）

| # | 事实 | 证据 | v6 处置 |
|---|---|---|---|
| 1 | 运行配置 `trim_sign="1,1,1"` | 布局存档 `:44` | 方向口径定案落盘；P0-2/D4 均为潜伏态，仍按正确公式实现 |
| 2 | UI 默认文本仍是 `-1,1,1`（过时旧口径） | `mmhand_scope.py:1950` | **新增强制项：默认改 `1,1,1`**（防布局重置/换机时 M27 符号错） |
| 3 | 布局 `f_min="-5000"` | 布局存档 | 用户意图=禁用下界。`_cl_fval` 下限 0 已把它钳成 0=禁用。**迁移规则：负值→0（禁用）+状态行提示一次**；不得回默认 0.5；徽章在 fmin≤0 时下界判定显示"未设阈值" |

---

## 2. 设计决策（D1–D8，v5 版基础上修订）

### D1. 恢复状态机
- `_force_recovery` 置 True：仅在一键紧绳 `_start_closed_loop()` 成功（cl_enabled=True）后；
- 清除（任一）：① 三缆均 `fmin_eff ≤ f_i ≤ fmax_eff` 连续 300ms（30 拍 @100Hz）；② `_stop_closed_loop()`；③ 启动失败回滚；
- 状态优先级：无数据 > 过紧 > 放松 > 恢复中 > 正常；阈值非法 → "未设阈值"，不得显示"正常"；
- 徽章 15Hz；比较加 0.05N 滞回防边界抖动。

### D2. 松绳方向
```
release_delta_i = -RELEASE_COUNTS * trim_sign[i]     # RELEASE_COUNTS = 2500
target_i  = baseline_i + release_delta_i
```
sign=+1 → −2500（counts 减=松）；sign=−1 → +2500（counts 增=松）。禁止硬编码统一 −2500。

### D3. 一键紧绳（事务化）
门禁（全满足才动）：
```
armed ∧ not cl_enabled ∧ 张力样本<0.5s ∧ 三缆全勾选
∧ n̂ 存在且全正 ∧ t_min_req ≤ t_use ≤ t_max_allow
其中 t_min_req = max_i(fmin_eff/n_i)   # 即 fmin_eff/min(n̂)，零位≈1.9N(fmin=0.5时)
     t_max_allow = min_i(fmax_eff/n_i)
     t_use = clamp(t_tgt, t_min_ui, t_max_ui)   # t_min/t_max 界内再验可行域
```
- `t_tgt < t_min_req` → 拒绝"t 太小，单缆会低于 fmin"；`> t_max_allow` → 拒绝（不静默钳）；
- n̂ None/含非正 → 拒绝；t_use ≤ 0 → 拒绝。
- 执行：①备份 mode/tau_roll/tau_pitch/preload → ②校验全过后切模式、写 τ=0、preload=t_use → ③`_start_closed_loop()` → ④cl_enabled=True 才置 recovery → ⑤失败恢复备份+清 flag+提示原因。
- 恢复完不自动停环；D1 条件①自动清 flag。
- 权威口径：一键紧绳用 `t_tgt`（张紧行），力矩模式手动用 `preload`，tooltip 写明。

### D4. 张紧地板（修正版）
`wrist_tight_step` 内、`_incr_step` 算出 step 之后：
```python
if p.f_min > 0.0 and f_n[i] <= p.f_min and step < 0:   # step<0=物理放（§1.3 推导）
    step = 0.0
    state.integ[i] = 0.0
    state.resid[i] = 0.0
trim[i] = p.trim_sign[i] * step
```
`f_min` 默认 0（禁用）；`_tight_params` 传 `fmin_eff`。

### D5. 有效阈值单源
```python
def _effective_flimits(self):
    """fmin_eff = max(边界fmin, 0)；负值→0（禁用，提示一次）
       fmax_eff = min(边界fmax_f 默认30, 守卫fmax 或 +∞)
       返回 (fmin_eff, fmax_eff, valid)；fmax≤fmin → invalid"""
```
空值语义：fmin 空/负 = 0（不启用下界）；fmax_f 必须有限（空→写 30+提示）；守卫 fmax 空 = 不额外收紧（非 0）；t_min/t_max 空 = 0 不启用。
接入五处：`_force_params_v2`（TDA）、`_tight_params`、`_tension_guard`（**位置模式恢复过载停环**）、`_force_fmax`、缆卡着色/逐缆章/徽章。

### D6. 状态判定纯函数
模块级 `rope_state(f, fmin, fmax, recovery, has_data, hyst=0.05)`：
- 返回 no_data/over/slack/recovering/normal/unset + 文案 + 颜色；
- 绝对张力判定（清零/去皮不影响）；样本龄>500ms→无数据；
- fmin≤0 → 下界判定跳过（fmax 仍判）；两者都无效 → unset；
- 过紧优先于恢复；逐缆章四态（正常/放松/过紧/无数据）；整体徽章六态；
- 汇总行："放松：C3｜过紧：无｜正常：C1 C2"。

### D7. UI
- 徽章 QLabel 加力状态块（15Hz）；缆卡数字旁加逐缆章；汇总行；
- 直控面板零位行下两按钮：🪢一键紧绳 / 🪢一键松绳，随门禁刷新使能+tooltip 原因；
- **trim_sign 默认文本 `-1,1,1` → `1,1,1`**（§1.4-2）；
- 边界行复用不新增重复字段。

### D8. 松绳安全
- baseline=`targets.get(m)`，None 回退 `_motor_pos_now(m)`（不回退 origin）；
- 目标钳 ±30000（小于 P4 硬限 ±30719）；逐绳勾选门禁，全不勾→拒绝；
- 张力新鲜要求（<0.5s）；ramp 保留；RELEASE_COUNTS 为常量。

---

## 3. 改动清单

### 3.1 `wrist_force_law.py`
- [ ] `WristTightParams` + `f_min=0.0`（slots/校验/赋值）；
- [ ] `wrist_tight_step` 地板按 D4（`step<0` 版）；
- [ ] 单测：(10,3,0)、t=1、f_min=0.5、sign=(−1,1,1)、integ≠0 → 三缆贴 fmin 无退化。

### 3.2 `mmhand_scope.py`
- [ ] `_effective_flimits()`（D5）；五处接入；
- [ ] `rope_state()` 模块级纯函数（D6）；
- [ ] `_release_delta()`、`_tighten_precheck()` 纯函数；
- [ ] `_on_release_rope()`（D2/D8）、`_on_tighten_rope()` 事务化（D3）；
- [ ] `_force_recovery` 状态机（D1）；
- [ ] 徽章/汇总行/逐缆章 + 15Hz 刷新（D7）；
- [ ] trim_sign 默认文本修正（D7）；
- [ ] 按钮行 UI + 门禁使能刷新。

### 3.3 测试（新增 `tests/test_scope_rope_state.py`）
- [ ] rope_state 六态/优先级/滞回/空阈值降级/fmin≤0 跳下界/清零下仍绝对判定；
- [ ] release_delta：sign=(+1,−1,+1) → (−2500,+2500,−2500)；
- [ ] 紧绳 precheck 全拒路径（n̂缺/t太小/t太大/张力过期/非三缆全勾）+ 成功路径 + 失败回滚（模式/参数/flag 全还原断言）；
- [ ] 松绳落点/None 基线/±30000 钳/全不勾拒绝；
- [ ] 端到端：放松→紧绳→恢复中→全缆正常 300ms→正常；
- [ ] `test_wrist_force_modes.py`：地板含 sign=−1+integ≠0 用例（防 v5 方向 BUG 回归）。

---

## 4. 迁移
- 旧布局 `f_min` 负值 → 0（禁用）+ 状态行提示一次（用户 −5000 意图=禁用下界）；
- `fmax_f` 空 → 写 30 + 提示；`t_min/t_max` 空=0 不启用；
- `_force_recovery` 不落盘；按钮不写布局。

## 5. 实施顺序
1. Phase 0：纯函数+单测（effective_flimits/rope_state/release_delta/precheck/地板）；
2. Phase 1：UI 显示（章/徽章/着色接入）；
3. Phase 2：两按钮+事务+回滚；
4. Phase 3：守卫/TDA 单源接入 + 端到端回归。

## 6. 验收清单
- [ ] 三缆松紧不均时章/汇总一致；清零后判定仍绝对；
- [ ] 边界行与守卫框同设时取严；守卫框空时位置模式仍有 fmax 过载停环；
- [ ] sign=−1 时松绳方向正确（不收紧）；**sign=−1 时地板禁放不禁紧**；
- [ ] 紧绳各拒路径不改现有设置；失败全回滚；
- [ ] 恢复中→全缆正常 300ms→自动变正常；停环亦清；
- [ ] 地板在积分非零时仍止放；
- [ ] 全套 pytest 绿；台架先 1N/小 max_step 验，再回 5N。

## 7. 已定决策（原 v5 §8 五问，全部拍板）
① 紧绳强制三缆全勾=是；② t_tgt 权威=是（preload 归手动）；③ 松绳要求张力新鲜=是（保守）；
④ 失败自动回滚=是；⑤ 守卫保留过载停环=是（经 effective limits，守卫框空亦有保护）。

## 8. 一句话
v6 = v5 的骨架 + 四处修正（D4 条件 `step<0`、默认 sign `1,1,1`、fmin 负值→0 禁用、迁移规则）；
方向语义以"trim_sign 定义 + sign(step)=物理张力方向"为唯一推导基准，不再依赖任何硬编码符号。
