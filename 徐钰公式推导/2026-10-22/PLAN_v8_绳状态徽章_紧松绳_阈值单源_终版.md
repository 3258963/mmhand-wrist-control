# PLAN v8：绳状态徽章 + 逐缆状态章 + 一键紧/松绳 + 张紧地板 + 阈值单源（v7 审阅修正版）

> 版本：v8（v7 + `REVIEW_v7` 三条 P0 + 相关 P1）
> 日期：2026-11-03
> 范围：PC 上位机 `mmhand_scope.py`、`wrist_force_law.py`、测试
> 前提：运行中松绳分级守卫/看门狗已按用户决定删除；守卫维持“松绳仅⚠、过载停环”；不动 α/TDA/增量律。

---

## 0. v7 → v8 修正记录

| # | v7 问题 | v8 修正 |
|---|---|---|
| P0-1 | 测试把 `t=1.0` 的缆序写反：写成 C1/C2≥0.5、C3<0.5 | 改为 **C1<0.5、C2/C3≥0.5**；所有期望值用固定姿态 n̂ 算，不凭记忆 |
| P0-2 | “地板保证三缆贴 fmin”与“`_tight_params` 拒绝 t<t_min_req”语义互斥 | **选 A：入口拒绝低 t**；地板只做“运行时防放穿”；删掉“0.81 应用驻点”的说法，纯律测试标注“UI 不可达” |
| P0-3 | `t_use` 在 UI `t_min/t_max` 之后没有复验可行域 | UI 界之后**再验** `t_min_req ≤ t_use ≤ t_max_allow`；不满足拒绝 |
| P1-1 | `t_use ≤ 0` 未拒绝 | 增加 `t_use > 0` 检查 |
| P1-2 | `_force_trim_sign()` 为 None 时松绳会 `-2500*None` | 松绳门禁先验 `trim_sign`，非法拒绝 |
| P1-3 | `_tight_params` 只查 `t_min_req`，未查 `t_max_allow` | 上下界都查；超上界拒绝 |
| P1-4 | `n̂=None` 时先算 `t_min_req` 会异常 | 先判 `nd is None / 非全正`，再算 t 界 |
| P1-5 | 启动成功但首拍即停，模式/参数不会回滚 | 明确“成功即视为会话开始”，状态行提示；不自动回滚，避免与停环原因打架 |

v7 保留有效的部分：`step<0` 方向修正、清 `integ/resid`、事务骨架、恢复 300ms 自动清、D5 阈值取严、D9 ramp 互斥。

---

## 1. 代码实况基线（2026-11-03）

| 事实 | 状态 |
|---|---|
| 布局 `trim_sign="1,1,1"`、`f_min="-5000"`（钳 0=禁用下界）、`t_min/t_max=""`、`cl_mode=tension` | 已核 |
| UI 默认 `trim_sign` 文本 `-1,1,1` + tooltip 旧口径 | 待改（D7） |
| `_force_fmax` 单源 `fmax_f`；缆卡着色 `v_abs`；边界行六框已存在 | 已存在勿重复 |
| `_tight_params` 未传 `f_min`；`WristTightParams` 无 `f_min` | 待加 |
| `_start_closed_loop` 不停 ramp | 待修（D9） |

---

## 2. 终版设计决策

### D1. 恢复状态机（v7 原样）

`_force_recovery`：

- 置 True：仅一键紧绳 `_start_closed_loop()` 成功（`cl_enabled=True`）后；
- 清：三缆进 `[fmin_eff,fmax_eff]` 连续 300 ms，或 `_stop_closed_loop()`，或启动失败回滚；
- 优先级：无数据 > 过紧 > 放松 > 恢复中 > 正常；
- 15 Hz；0.05 N 滞回。

### D2. 松绳方向（v7 原样 + P1-2）

```python
release_delta_i = -RELEASE_COUNTS(2500) * trim_sign[i]
baseline_i = targets.get(m) or _motor_pos_now(m)
target_i = clamp(baseline_i + release_delta_i, -30000, +30000)
```

门禁：

```
armed ∧ not cl_enabled ∧ 张力新鲜<0.5s
∧ trim_sign 合法（长度 3，元素 ±1）
∧ 至少一根缆勾选
```

三缆全不勾 → 拒绝；走 `_send_motor_target`（保留 ramp）。

### D3. 一键紧绳（v8 修正版）

门禁（全满足才动）：

```
armed ∧ not cl_enabled ∧ 张力新鲜<0.5s ∧ 三缆全勾选
∧ n̂ 存在且全正
∧ 位姿 in angle_in_range（模型行程内）
∧ t_min_req ≤ t_tgt_raw ≤ t_max_allow
```

其中：

```
t_min_req  = max_i(fmin_eff / n_i) = fmin_eff / min(n̂)
t_max_allow= min_i(fmax_eff / n_i) = fmax_eff / max(n̂)
```

`t_use` 计算（**空界跳过；UI 界后再复验**）：

```python
t_use = t_tgt_raw
if t_min_ui > 0: t_use = max(t_use, t_min_ui)
if t_max_ui > 0: t_use = min(t_use, t_max_ui)

if t_use <= 0:        reject("t_use 必须 > 0")
if t_use > 100:       reject("预紧上限 100N")
if not (t_min_req <= t_use <= t_max_allow):
    reject("t_use 超出当前位姿可行域（UI t 界与 f 盒冲突）")
```

执行：

```
① 备份 mode / tau_roll / tau_pitch / preload
② 切力矩模式、τ=0、preload=t_use
③ _start_closed_loop()
④ cl_enabled=True 才置 _force_recovery
⑤ 启动失败：恢复备份 + 清 flag + 提示原因
```

权威：一键紧绳用 `t_tgt`（张紧行），力矩模式手动用 `preload`；tooltip 写明。

### D4. 张紧地板（v8 定案：入口拒绝低 t，地板只防放穿）

`wrist_tight_step` 内、`_incr_step` 算出 step 后：

```python
if p.f_min > 0.0 and f_n[i] <= p.f_min and step < 0:
    step = 0.0
    state.integ[i] = 0.0
    state.resid[i] = 0.0
trim[i] = p.trim_sign[i] * step
```

`_tight_params` 入口：

```python
if nd is None or any(v <= 0 for v in nd):
    return None
t_min_req  = fmin_eff / min(nd)
t_max_allow= fmax_eff / max(nd)
if t_tgt < t_min_req:
    return None   # 状态行："t 太小，单缆会低于 fmin"
if t_tgt > t_max_allow:
    return None   # 状态行："t 太大，单缆会超过 fmax"
```

**职责边界（写进文档/注释）**：

- `_tight_params` 保证“目标分布本身可行”：`t_tgt·n̂_i` 全部在 `[fmin_eff, fmax_eff]`；
- 地板只保证“运行中因扰动/积分/进位导致某缆到 fmin 时不再继续放”；
- **地板不是“把低目标拉到 fmin”的工具**。因此：

  - `t=0.5`、`t=1.0` 这类低目标在 UI 路径上会被 `_tight_params` 拒绝；
  - 纯律测试可以直接构造 `WristTightParams` 验证地板，但必须标注“UI 不可达，只验证律”；
  - 不再宣称“0.81 N 安全驻点”是应用状态。

### D5. 有效阈值单源（v7 原样）

```python
fmin_eff = max(边界fmin or 0, 守卫fmin or 0)
fmax_eff = min(边界fmax_f 默认30, 守卫fmax or +inf)
valid = fmax_eff > fmin_eff
```

`_tension_guard` 用 effective 构造 `TensionConfig`；接入五处：`_force_params_v2`、`_tight_params`、`_tension_guard`、`_force_fmax`、缆卡/章/徽章。

### D6. 状态判定纯函数（v7 原样）

`rope_state(f, fmin, fmax, recovery, has_data, hyst=0.05)`：六态 `no_data/over/slack/recovering/normal/unset`；绝对张力；`fmin≤0` 跳下界；逐缆四态；汇总行。

### D7. UI（v7 原样）

- 徽章 + 汇总行（15 Hz）；缆卡逐缆章；
- `trim_sign` 默认 `1,1,1`，tooltip 改为“三台 counts↑=收绳；换接线后点动复核”；
- 两按钮随门禁刷新使能 + tooltip 原因。

### D8. 松绳安全（v7 原样）

baseline 回退 `_motor_pos_now`；±30000；张力新鲜；ramp 保留；`RELEASE_COUNTS` 常量。

### D9. ramp/闭环互斥（v7 原样）

`_start_closed_loop()` 开头：

```python
self._ramp_timer.stop()
self._ramp_state.clear()
```

---

## 3. 修正后的测试矩阵

### 3.1 `test_wrist_force_modes.py`（地板，纯律）

固定 `(0,0)` 姿态：

```
n = (0.264, 0.595, 0.759)
fmin = 0.5
```

| 用例 | 期望 |
|---|---|
| `(10,3,0)`、`t=0.5`、`fmin=0.5`、sign=(+1,+1,+1) | 三缆最终都到 0.5；`t_meas≈0.81`；**纯律、UI 不可达**（入口会拒 t<1.89） |
| `(10,3,0)`、`t=1.0`、`fmin=0.5` | 收敛 t=1；**C1=0.264<0.5，C2=0.595≥0.5，C3=0.759≥0.5**；纯律、UI 不可达 |
| `t=1.5`、`fmin=0.5` | `_tight_params` 因 `t < t_min_req(1.89)` 拒绝 |
| `t=3.0`、`fmin=0.5` | `_tight_params` 通过；T=(0.79,1.78,2.28)，全部 ≥0.5 |
| `sign=(-1,+1,+1)` + `integ≠0` | 地板禁放不禁紧；不出现“sign=-1 时反向”回归 |

> 说明：`t=0.5/1.0` 是纯律行为，不是 UI 可达状态；应用里 `_tight_params` 会拒绝它们。测试注释必须写明，否则后人会误以为 UI 能跑。

### 3.2 `tests/test_scope_rope_state.py`（新增）

- `rope_state` 六态/优先级/滞回/空阈值降级/`fmin≤0` 跳下界/清零下仍绝对判定；
- `release_delta`：`sign=(+1,-1,+1)` → `(-2500,+2500,-2500)`；`sign=None` → 拒绝；
- 紧绳 `t_use` 专项：
  - `t_min="" / t_max=""` → `t_use=t_tgt_raw`，不被钳 0；
  - 单边设置各生效；
  - `t_use>100` 拒绝；
  - `t_use<=0` 拒绝；
  - `t_min_ui > t_max_allow` → `t_use` 超上界 → 拒绝；
  - `t_max_ui < t_min_req` → `t_use` 低于下界 → 拒绝；
- precheck 全拒路径（n̂ 缺/非全正/位姿出行程/t 太小/t 太大/张力过期/非三缆全勾）+ 成功 + 失败回滚；
- 松绳落点/None 基线/±30000/全不勾拒绝/`trim_sign` 非法拒绝；
- ramp 互斥：ramp 活动时启动闭环 → ramp 停止且状态清；
- 端到端：放松→紧绳→恢复中→全缆正常 300ms→正常。

### 3.3 `_tight_params` 新增测试

- `nd=None` → 返回 None（不先做除法）；
- `nd` 含 0/负 → 返回 None；
- `t=1.5` → None；
- `t=3.0` → 通过；
- `fmin_eff=0` → `t_min_req=0`，`t_target=0` 仍应被“t_use>0”拒绝（一键紧绳），张紧模式 `t=0` 允许（floor 禁用）。

---

## 4. 实施顺序

1. **Phase 0**：`_effective_flimits` / `rope_state` / `release_delta` / `_tighten_precheck` / `_incr_step` 地板 / `_tight_params` t 上下界 + 单测；
2. **Phase 1**：缆卡章、汇总徽章、15 Hz 刷新、着色接入 effective；
3. **Phase 2**：两个按钮 + 事务 + 失败回滚；
4. **Phase 3**：`_tension_guard` effective、`_start_closed_loop` ramp 互斥、端到端回归。

---

## 5. 验收

- 三缆松紧不均 → 章/汇总一致；清零后判定仍绝对；
- 双阈值同设取严；守卫框空时位置模式仍有 fmax 过载停环；
- `t_min/t_max` 两框留空时，一键紧绳可正常启动（不被 `clamp(...,0,0)` 拒绝）；
- `t_use` 被 UI 界推出 `[t_min_req,t_max_allow]` 时，明确拒绝，不启动；
- `sign=-1` 时松绳方向正确、地板禁放不禁紧；
- 紧绳各拒路径不改现有设置；失败全回滚；
- 恢复中→全缆正常 300ms→正常；停环亦清；
- ramp 进行中启动闭环 → ramp 即停；
- 全套 pytest 绿；台架先 1 N/小 `max_step`，再回 5 N。

---

## 6. 一句话

v8 = v7 + 三条“终版级”修正：

1. `t=1.0` 的缆序改为 **C1<0.5、C2/C3≥0.5**；
2. 地板与 `t_min_req` 分工定死：**入口拒绝低 t，地板只防放穿**，删掉“0.81 应用驻点”；
3. `t_use` 在 UI 界后**再验** `[t_min_req,t_max_allow]`，并补 `t_use>0 / ≤100 / trim_sign 合法` 门禁。

至此 v5→v8 的每个方向、边界、空值语义都有推导或测试钉死。
