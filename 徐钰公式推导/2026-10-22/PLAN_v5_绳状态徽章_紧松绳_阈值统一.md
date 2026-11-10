# PLAN v5：绳状态徽章 + 逐缆状态章 + 一键紧/松绳 + 张紧地板 + 阈值统一

> 版本：v5（对 v4 的修订版）
> 日期：2026-11-03
> 范围：PC 上位机 `mmhand_scope.py`、`wrist_force_law.py`、测试
> 前提：运行中松绳分级守卫/看门狗已按用户决定删除；守卫维持“松绳仅 ⚠、过载停环”；不动 α/TDA/增量律。

---

## 0. 一页结论

v4 的方向是对的，但有 **5 个 P0 级逻辑洞**，直接实现会出现“方向反、状态卡死、失败留脏状态、地板继续放绳、阈值只统一了显示”：

| # | v4 问题 | v5 决策 |
|---|---|---|
| P0-1 | `_force_recovery` 只在停环清，端到端却要求“恢复中→正常” | 全缆回到 `[fmin,fmax]` 稳定 300 ms 自动清；停环兜底 |
| P0-2 | 松绳统一 `−2500`，与 `trim_sign=-1,1,1` 冲突 | 每台 `delta_i = -RELEASE_COUNTS * trim_sign[i]` |
| P0-3 | 一键紧绳先写模式/参数/flag，再启动；失败留脏状态 | precheck → start → 成功后才置 flag；失败回滚 |
| P0-4 | 张紧地板只清 `e_i`，清不掉 integral/resid，且 `e_i<0` 不等于物理放绳 | 算完 step 后按 `trim_sign[i]*step<0` 判释放，清零 step/integ/resid |
| P0-5 | “阈值统一”只改显示，TDA/守卫仍两套；守卫留空会丢位置模式过载保护 | 新增 `_effective_flimits()`，显示/TDA/守卫共用；守卫不得留空免责 |

另外，当前代码已经有一部分 v4 提到的内容，**不要重复实现**：

- 边界行 `fmin/fmax_f/t_min/t_max/τr/τp` 已存在（`mmhand_scope.py:1960-1992`）；
- `_force_fmax()` 已改为只读 `fmax_f`（`:3356`）；
- 缆卡着色已用 `v_abs` 绝对张力（`:906-913`）；
- `t_min/t_max` 的提示/钳制已有（`_t_bound_note`、`_tight_params`）。

v5 只做“补齐 + 纠错 + 统一”，不重写已有边界行。

---

## 1. 目标与非目标

### 目标

1. 观测台能一眼看出：三根缆分别“放松 / 正常 / 过紧 / 无数据”，以及整体是否在恢复。
2. 一键紧绳：在安全前提下把三缆拉到预紧，TDA 分配，不出现单缆承重退化。
3. 一键松绳：按每台真实方向放绳，不出现“按松绳结果收紧”。
4. 张紧模式有“方向地板”：任何缆到 `f_min` 后不再被继续放绳。
5. 阈值只保留一套“有效值”：显示、TDA、守卫同源；空值/双阈值语义明确。
6. 所有 P0 行为有纯函数单测；启动失败可回滚，不留脏状态。

### 非目标

- 不做运行中松绳分级守卫/看门狗；
- 不改 α 缩放、TDA 求解、增量 PI 形式；
- 不做自动恢复/自动停环（除状态 flag 自动清）；
- 不改 P4 固件（本轮只 PC）。

---

## 2. 当前代码事实（实现前先核对）

| 事实 | 位置 | 对 v4 的影响 |
|---|---|---|
| 边界行已有 `fmin/fmax_f/t_min/t_max/τr/τp` | `mmhand_scope.py:1960-1992` | v4“新增边界行”改为“复用/扩展” |
| `_force_fmax()` 只读 `fmax_f` | `:3356` | 力控上限已单源；守卫框独立 |
| 缆卡着色用 `v_abs` 绝对张力 | `:906-913` | v4 BUG#2 已修，勿回退 |
| `_tight_params` 未传 `f_min` | `:3437-3465` | 需加 `f_min` 参数 |
| `WristTightParams` 无 `f_min` | `wrist_force_law.py:334-373` | 需加默认 0 |
| `_force_recovery`、`_rope_state`、两个按钮 | 不存在 | v5 新增 |
| `trim_sign` 默认 `-1,1,1` | `:1946-1950` | 松绳方向必须按它算 |
| `_send_motor_target` 无限位、仅斜坡 | `:2651` | 松绳需自己加安全限幅 |

---

## 3. 设计决策（D1–D8）

### D1. 恢复状态机：flag 必须能自动清

- `_force_recovery` 只在 `_start_closed_loop()` **成功返回后**置 True。
- 清除条件（任一）：
  1. 三缆都满足 `fmin_eff ≤ f_i ≤ fmax_eff` 连续 **300 ms**（30 拍 @100 Hz）；
  2. `_stop_closed_loop()`；
  3. 启动失败/参数非法（由事务回滚清）。
- 状态优先级：

```
无数据 > 过紧 > 放松 > 恢复中 > 正常
```

- 若阈值未设/非法，状态为“未设阈值”，不能显示“正常”。
- 徽章 15 Hz 刷新；比较加 0.05 N 滞回，避免边界抖动。

### D2. 松绳方向：按 `trim_sign` 逐台算

`trim_sign[i]` 语义：`+1 = counts 增 ⇒ 该缆张力增`；`−1 = 反向`。

```
release_delta_i = -RELEASE_COUNTS * trim_sign[i]
target_i = baseline_i + release_delta_i
```

- `trim_sign=+1` → `−2500`（counts 减 = 松）；
- `trim_sign=−1` → `+2500`（counts 增 = 松）。

禁止硬编码“三台都 −2500”。

### D3. 一键紧绳：事务化

门禁（全部满足才允许）：

```
armed ∧ not cl_enabled
∧ 张力样本 < 0.5 s
∧ 三根缆都已勾选
∧ 当前位姿在模型行程内
∧ n̂ 存在且三分量都 > 0
∧ t_min_req ≤ t_max_allow
```

其中：

```
t_min_req  = max_i( fmin_eff / n_i )
t_max_allow= min_i( fmax_eff / n_i )
t_use      = clamp(t_tgt, max(t_min_req, t_min_ui), min(t_max_allow, t_max_ui))
```

- `t_tgt < t_min_req` → 拒绝，提示“t 太小，单缆会低于 fmin”；
- `t_tgt > t_max_allow` → 拒绝/钳到 `t_max_allow`（建议拒绝，避免静默）；
- `n̂` 有 ≤0 分量或 None → 拒绝，不能除；
- `t_use ≤ 0` → 拒绝。

执行顺序：

```
1) 保存 backup: mode / tau_roll / tau_pitch / preload
2) 全部校验通过后，再切模式、写 tau=0、preload=t_use
3) _start_closed_loop()
4) 只有 cl_enabled=True 后才 _force_recovery=True
5) 失败：恢复 backup，清 flag，提示原因
```

恢复完不自动停环；D1 的全缆正常 300 ms 自动清 flag。

### D4. 张紧地板：按物理 step 判，不只清 `e_i`

在 `wrist_tight_step` 中，`_incr_step` 算出 `step` 后：

```python
if f_n[i] <= p.f_min and p.trim_sign[i] * step < 0:
    step = 0
    state.integ[i] = 0.0
    state.resid[i] = 0.0
trim[i] = p.trim_sign[i] * step
```

理由：

- `trim_sign[i] * step < 0` 才表示“这一拍会让该缆张力下降”；
- 只清 `e_i` 不清 `integ/resid`，积分仍可能驱动放绳；
- `n_i<0` 或 `trim_sign=-1` 时，`e_i<0` 并不等于物理放绳。

`f_min` 默认 0；`_tight_params` 传 `fmin_eff`。

### D5. 有效阈值：一个函数，三条路径共用

新增：

```python
def _effective_flimits(self):
    """返回 (fmin_eff, fmax_eff, valid)。
    fmin: 边界 fmin（空=0）与守卫 fmin（空=0）取 max。
    fmax: 边界 fmax_f（默认 30）与守卫 fmax（空=+∞）取 min。
    """
```

规则：

- `fmin_eff = max(boundary_fmin or 0, guard_fmin or 0)`；
- `fmax_eff = min(boundary_fmax, guard_fmax or +∞)`；
- `fmax_eff <= fmin_eff` → invalid，启动拒绝，徽章“阈值非法”；
- 空值语义：
  - `fmin` 空 = 0（不启用下限）；
  - `fmax_f` 不允许空/0（必须有有限上限，否则 TDA 无盒）；
  - 守卫 `fmax` 空 = 不额外收紧，不是 0；
  - `t_min/t_max` 空 = 0 = 不启用。

使用点：

- `_force_params_v2`（TDA 的 f_min/f_max）；
- `_tight_params`（floor + f_max）；
- `_tension_guard`（过载/松绳判定）；
- `_refresh` / `CableCard` / `_rope_state`（显示）；
- `_force_fmax` 改为返回 `fmax_eff`。

**守卫不得建议留空**：位置模式没有模式级 f 检查，守卫是唯一过载停环路径；留空等于丢保护。

### D6. 状态章：纯函数，无停环权力

```python
def rope_state(f, fmin, fmax, recovery,
               has_data=True, hysteresis=0.05):
    # 返回 ("no_data"|"over"|"slack"|"recovering"|"normal"|"unset", text, color)
```

- 绝对张力判定；显示相对值不影响；
- `has_data=False` 或样本龄 > 500 ms → 无数据；
- `fmin/fmax` 无效 → 未设阈值；
- 过紧优先于恢复；
- 单缆章四态；整体徽章五态 + 未设阈值；
- 汇总：“放松：C3｜过紧：无｜正常：C1 C2”。

### D7. UI

- 边界行复用，不新增重复字段；新增只读 `t区间` 显示（可选）。
- 力控状态块加徽章 QLabel，15 Hz 节流。
- 缆卡数字旁加逐缆章。
- 直控面板零位行下加两个按钮：
  - `🪢 一键紧绳`
  - `🪢 一键松绳`
- 按钮状态随 `armed / cl_enabled / 张力新鲜` 刷新；不满足时禁用并 tooltip 说明原因。

### D8. 松绳安全

- `baseline = targets.get(m)`；若 None → `_motor_pos_now(m)`，不要回退 origin；
- `target = baseline + release_delta_i`；
- 目标必须钳到 P4 安全域（建议 `±30000` counts，小于硬件 `±30719`）；
- 松绳前要求张力新鲜（<0.5 s）；不新鲜只允许“手动点动”，不允许一键松绳；
- 逐绳勾选：只松勾选的；若一根都没勾，拒绝；
- `_send_motor_target` 的 ramp 保留；松绳量 `RELEASE_COUNTS=2500` 作为常量，不散落魔法数。

---

## 4. 改动清单

### 4.1 `wrist_force_law.py`

- [ ] `WristTightParams` 增加 `f_min: float = 0.0`，`__slots__`/校验/赋值；
- [ ] `wrist_tight_step` 地板逻辑按 D4；
- [ ] 单测：`f_n=(10,3,0)`、`t_target=1`、`trim_sign=(-1,1,1)`、`integ` 非零 → 三缆贴 `fmin`，无继续放绳。

### 4.2 `mmhand_scope.py`

- [ ] `_effective_flimits()`（D5）；
- [ ] `_force_params_v2`/`_tight_params`/`_tension_guard`/`_force_fmax` 改用有效值；
- [ ] `_refresh`/`CableCard` 着色改用有效值；
- [ ] `rope_state()` 纯函数（模块级，便于单测）；
- [ ] `_rope_badge_refresh()` 15 Hz；
- [ ] `_release_delta(trim_sign, counts)` 纯函数；
- [ ] `_on_release_rope()`（D2/D8）；
- [ ] `_tighten_precheck()` 纯函数（D3）；
- [ ] `_on_tighten_rope()` 事务化（D3）；
- [ ] `_force_recovery` 状态机（D1）；
- [ ] 按钮行 + 缆卡章 + 汇总徽章（D7）；
- [ ] 边界行 `fmin/fmax_f` 默认值/空值语义统一（D5）。

### 4.3 测试

新增 `tests/test_scope_rope_state.py`（纯函数优先）：

- [ ] `rope_state` 六态：no_data / over / slack / recovering / normal / unset；
- [ ] 优先级：over > slack > recovering > normal；
- [ ] 空阈值降级；
- [ ] 清零/去皮后判定仍用绝对 f；
- [ ] 双阈值取严：`fmin=max`、`fmax=min`；
- [ ] 滞回：边界 ±0.05 N 不抖动；
- [ ] `release_delta`：`trim_sign=(+1,-1,+1)` → `(-2500,+2500,-2500)`；
- [ ] `_tighten_precheck`：n̂ None/含 0 或负、t 太小/太大、张力过期、非三缆全选；
- [ ] `_on_tighten_rope` 成功置 flag；失败回滚 mode/参数/flag；
- [ ] `_on_release_rope` 目标落点、None baseline、软限位；
- [ ] 端到端：slack → 紧绳 → recovering →（全缆正常 300 ms）→ normal；
- [ ] 地板测试含 `trim_sign=-1` 与 `integ≠0`。

`test_wrist_force_modes.py` 增加：

- [ ] `WristTightParams(f_min=...)` 默认兼容旧测试；
- [ ] 地板仿真：`(10,3,0)`、`t=1`、`f_min=0.5`、`trim_sign=(-1,1,1)` → 三缆不低于 0.5，不出现单缆退化。

---

## 5. 兼容与迁移

- 旧布局没有 `t_min/t_max`/`fmax_f`：`_cl_fval_opt` 返回空 → 用默认（`fmin=0.5`、`fmax=30`、`t_min/t_max=0`）。
- 旧布局 `f_min=-3000`：按空/非法处理，回默认 0.5，并在状态行提示“已修正”。
- `fmax_f` 必须有限；若旧布局为空，写 30 并提示。
- 新增 `_force_recovery` 不落盘；重启即 False。
- 按钮只影响本次会话，不写布局。

---

## 6. 实施顺序

### Phase 0：纯函数与单测（不动 UI）

1. `_effective_flimits` + `rope_state` + `release_delta` + `_tighten_precheck`；
2. `wrist_tight_step` 地板；
3. 单测先绿。

### Phase 1：UI 显示

4. 缆卡章 + 汇总徽章 + 15 Hz 刷新；
5. 边界行有效值接入着色。

### Phase 2：两个按钮

6. 松绳按钮（D2/D8）；
7. 紧绳按钮（D3 事务）；
8. 失败回滚/提示。

### Phase 3：统一与回归

9. TDA/守卫/显示全部走 `_effective_flimits`；
10. 端到端测试 + 台架小目标验证。

---

## 7. 验收清单

- [ ] 三缆分别放松/正常/过紧时，逐缆章和汇总行一致；
- [ ] 清零后显示相对值，但状态判定仍按绝对张力；
- [ ] 边界行与守卫框同时设置时，显示/控制都取更严者；
- [ ] 守卫框留空时，位置模式仍有 `fmax_f` 过载停环（不能丢）；
- [ ] `trim_sign=-1` 时一键松绳方向正确（不会把 M27 收紧）；
- [ ] 一键紧绳在 n̂ 非全正/t 太小/张力过期/非三缆全选时拒绝，且不改模式/参数；
- [ ] 一键紧绳启动失败后模式/参数/flag 回滚；
- [ ] 恢复中在三缆正常 300 ms 后自动变正常；停环也清；
- [ ] 张紧地板在积分非零、`trim_sign=-1` 时仍不放绳；
- [ ] 全套 pytest 绿；台架 1 N/小 `max_step` 先验，再恢复 5 N。

---

## 8. 待确认（实现前拍板）

1. 一键紧绳是否强制“三缆全勾选”？建议是；只勾 1–2 根时 TDA 目标对未勾选缆无意义。
2. `t_tgt` 与 `preload` 的权威关系：建议一键紧绳用 `t_tgt`，力矩模式手动用 `preload`，UI 文案写清。
3. 松绳是否要求张力新鲜？建议要求；否则只能手动点动。
4. 一键紧绳失败后是否自动恢复原模式/参数？建议恢复，并在状态行提示。
5. 守卫框是否保留过载停环？建议保留，不能靠“留空”免责。

---

## 9. 一句话

v5 的核心不是“再加几个控件”，而是把 v4 的 **恢复状态、松绳方向、紧绳事务、地板物理方向、阈值单源** 五件事定死；这五件不定，UI 做得再漂亮，台架上也会出现“按松绳变紧、恢复中永远不结束、失败后卡在力矩模式、到了 fmin 还继续放、显示和控制两套阈值”的问题。
