# PLAN v8.2：绳状态徽章 + 逐缆状态章 + 一键紧/松绳 + 张紧地板 + 阈值单源（实施版，待修改）

> 版本：v8.2（v8 + v8.1 补丁 + REVIEW_v8.1 不变式修正）
> 日期：2026-11-03
> 范围：PC 上位机 `mmhand_scope.py`、`wrist_force_law.py`、测试
> 前提：运行中松绳分级守卫/看门狗已按用户决定删除；守卫维持“松绳仅⚠、过载停环”；不动 α/TDA/增量律。
> 状态：**可开工；本文件为待用户修改版**。代码尚未改动。

---

## 0. 版本链与本版裁定

| 轮 | 拦下的真错 | 处置 |
|---|---|---|
| v5→v6 | 地板条件 `sign×step<0` 在 sign=−1 时方向全反 | 改为 `step<0` |
| v6→v7 | `clamp(t,0,0)=0` 紧绳键到手即死；地板保证不了逐缆 fmin；fmin_eff 漏守卫；ramp/闭环互踩 | 条件式 t 界、t_min_req、effective limits、D9 |
| v7→v8 | 缆序断言错；地板/t_min_req 语义互斥；t_use 未复验 | 入口拒绝低 t；t_use 二次校验 |
| v8→v8.1 | v8 的 `T=t·n` 期望是 TDA 解，不是张紧律终态；D2 `or` 短路 | 期望改仿真真值；`targets is not None` |
| v8.1→v8.2 | **v8.1 的“全员 ≥fmin”不变式在低目标下不成立** | 按目标分域断言；低目标允许起始低于 fmin 的缆保持低 |

**核心结论：**

- 张紧律的终态**不是** `T=t·n`，不能拿 TDA 解做 golden；
- 地板只保证“**原本在 fmin 以上的缆不被放穿**”，不保证“起始低于 fmin 的缆被抬到 fmin”；
- 因此测试断言必须分域，不能用一条 `all(f_i >= fmin)` 打天下。

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

### D1. 恢复状态机

`_force_recovery`：

- 置 True：仅一键紧绳 `_start_closed_loop()` 成功（`cl_enabled=True`）后；
- 清：三缆进 `[fmin_eff,fmax_eff]` 连续 300 ms（30 拍），或 `_stop_closed_loop()`，或启动失败回滚；
- 优先级：无数据 > 过紧 > 放松 > 恢复中 > 正常；
- 15 Hz；0.05 N 滞回。

### D2. 松绳方向（含 v8.1 `or` 修正）

```python
release_delta_i = -RELEASE_COUNTS(2500) * trim_sign[i]

target = self.targets.get(m)
baseline_i = target if target is not None else self._motor_pos_now(m)
target_i = clamp(baseline_i + release_delta_i, -30000, +30000)
```

门禁：

```
armed ∧ not cl_enabled ∧ 张力新鲜<0.5s
∧ trim_sign 合法（长度 3，元素 ±1）
∧ 至少一根缆勾选
```

三缆全不勾 → 拒绝；走 `_send_motor_target`（保留 ramp）。

**注意：** `targets=0` 是合法值，不能用 `targets.get(m) or ...`；必须 `is not None`。

### D3. 一键紧绳（事务化）

门禁：

```
armed ∧ not cl_enabled ∧ 张力新鲜<0.5s ∧ 三缆全勾选
∧ n̂ 存在且全正
∧ 位姿 in angle_in_range（模型行程内）
∧ t_min_req ≤ t_tgt_raw ≤ t_max_allow
```

其中：

```
t_min_req  = fmin_eff / min(n̂)
t_max_allow= fmax_eff / max(n̂)
```

`t_use` 计算：

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

权威：一键紧绳用 `t_tgt`，力矩模式手动用 `preload`。

### D4. 张紧地板与入口约束

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
    return None   # "t 太小，单缆会低于 fmin"
if t_tgt > t_max_allow:
    return None   # "t 太大，单缆会超过 fmax"
```

**职责边界：**

- `_tight_params` 保证“目标分布本身可行”；
- 地板只保证“运行中因扰动/积分/进位导致某缆到 fmin 时不再继续放”；
- **地板不是“把低目标拉到 fmin”的工具**；
- 因此 `t=0.5/1.0` 这类低目标在 UI 路径会被 `_tight_params` 拒绝；纯律测试可直接构造 `WristTightParams`，但必须标注“UI 不可达”。

### D5. 有效阈值单源

```python
fmin_eff = max(边界fmin or 0, 守卫fmin or 0)
fmax_eff = min(边界fmax_f 默认30, 守卫fmax or +inf)
valid = fmax_eff > fmin_eff
```

`_tension_guard` 用 effective 构造 `TensionConfig`；接入五处：`_force_params_v2`、`_tight_params`、`_tension_guard`、`_force_fmax`、缆卡/章/徽章。

### D6. 状态判定纯函数

`rope_state(f, fmin, fmax, recovery, has_data, hyst=0.05)`：

- 六态：`no_data / over / slack / recovering / normal / unset`；
- 绝对张力判定；样本龄 >500 ms → 无数据；
- `fmin≤0` 跳下界（fmax 仍判）；两者都无效 → unset；
- 过紧优先于恢复；逐缆四态；汇总行。

### D7. UI

- 徽章 + 汇总行（15 Hz）；缆卡逐缆章；
- `trim_sign` 默认 `1,1,1`，tooltip 改为“三台 counts↑=收绳；换接线后点动复核”；
- 两按钮随门禁刷新使能 + tooltip 原因。

### D8. 松绳安全

baseline 回退 `_motor_pos_now`；±30000；张力新鲜；ramp 保留；`RELEASE_COUNTS` 常量。

### D9. ramp/闭环互斥

`_start_closed_loop()` 开头：

```python
self._ramp_timer.stop()
self._ramp_state.clear()
```

---

## 3. 测试矩阵（v8.2 修正版）

### 3.1 仿真真值（纯律，勿作 golden）

仿真设置（忠实复刻计划 D4 律）：

```
初态 f=(10,3,0)、fmin=0.5、零位 n̂=(0.26444,0.59491,0.75905)
sign=+1×3、kp=50、ki=10、max_step=5、deadband=0.05
植物 0.002 N/c、40k 拍
```

| t 目标 | 终态（参考） | 行为 |
|---|---|---|
| 0.2 | `(0.498, 0.490, 0.000)`, t=0.42 | 目标低于可达底（≈0.43），驻停；C3 锁死不可提 |
| 0.5 | `(0.498, 0.552, 0.104)`, t=0.54 | 收敛进死区；C1 贴地板，C3 仍低于 fmin |
| 1.0 | `(0.498, 0.752, 0.498)`, t=0.96 | 收敛进死区；C1/C3 双贴地板（windup 过冲） |
| 3.0 | `(0.498, 0.498, 3.402)`, t=3.01 | 收敛；两缆贴地板、C3 独扛 |
| sign=(−1,1,1), C1=0.4 → t=8 | `(6.44, 5.43, 4.09)`, t=8.04 | 地板禁放不禁紧，方向修正成立 |

**两条行为真相（写进注释）：**

1. `max_step` 饱和把三缆放绳速率抹平，不按 n̂ 比例；
2. 积分 windup 会穿过目标继续放到地板，再回程；终态分布是参数/路径依赖的。

### 3.2 断言策略（v8.2 核心修正）

**不要**对所有目标统一断言 `all(f_i >= fmin-0.02)`。按目标分域：

```python
if t_target >= t_min_req:
    # 入口保证目标分布可行：所有缆应 ≥ floor
    assert all(f_i >= fmin - 0.02 for i in range(3))
else:
    # 低目标：只承诺“原本在 fmin 以上的缆不被放穿”
    for i in range(3):
        if f_start[i] >= fmin:
            assert f_i >= fmin - 0.02
    # 起始低于 fmin 的缆允许保持低（C3=0/0.104 是合法终态）
```

另外统一：

```python
assert all(f_i <= fmax for i in range(3))          # 无过载
if t_target >= reachable_bottom:
    assert abs(t_meas - t_target) <= deadband + 0.1
else:
    # 驻停分支：t 停在可达底附近，最后 100 拍 step 恒 0
```

### 3.3 `test_wrist_force_modes.py`（纯律）

| 用例 | 断言 |
|---|---|
| `(10,3,0), t=0.2, fmin=0.5` | 驻停分支：`t≈0.42`，C3≈0，C1/C2≥0.48；最后 100 拍 step=0 |
| `(10,3,0), t=0.5, fmin=0.5` | 低目标分支：C1≈0.498、C2≈0.552、C3≈0.104；**C3 允许 <fmin**；`t≈0.54` |
| `(10,3,0), t=1.0, fmin=0.5` | 低目标分支：`(0.498,0.752,0.498)`；C1/C3 贴地板；`t≈0.96` |
| `(10,3,0), t=3.0, fmin=0.5` | 高目标分支：`(0.498,0.498,3.402)`；**all f≥0.48**；`t≈3.01` |
| `sign=(-1,1,1)`, C1=0.4 贴地板拉到 t=8 | 地板禁放不禁紧；C1 允许上升；`t≈8.04` |

> `t=0.2/0.5/1.0` 是**纯律、UI 不可达**（`_tight_params` 拒绝 `t<1.89`）；测试必须直接构造 `WristTightParams`，并加注释。

### 3.4 `tests/test_scope_rope_state.py`（新增）

- `rope_state` 六态/优先级/滞回/空阈值降级/`fmin≤0` 跳下界/清零下仍绝对判定；
- `release_delta`：`sign=(+1,-1,+1)` → `(-2500,+2500,-2500)`；`sign=None` → 拒绝；
- `release_baseline`：`targets[m]=0` 时必须用 0，**不能**回退 `_motor_pos_now`；
- 紧绳 `t_use` 专项：
  - `t_min="" / t_max=""` → `t_use=t_tgt_raw`，不被钳 0；
  - 单边设置各生效；
  - `t_use>100` 拒绝；
  - `t_use<=0` 拒绝；
  - `t_min_ui > t_max_allow` → 拒绝；
  - `t_max_ui < t_min_req` → 拒绝；
- precheck 全拒路径（n̂ 缺/非全正/位姿出行程/t 太小/t 太大/张力过期/非三缆全勾）+ 成功 + 失败回滚；
- 松绳落点/None 基线/±30000/全不勾拒绝/`trim_sign` 非法拒绝；
- ramp 互斥：ramp 活动时启动闭环 → ramp 停止且状态清；
- 端到端：放松→紧绳→恢复中→全缆正常 300ms→正常。

### 3.5 `_tight_params` 专项

- `nd=None` → 返回 None（不先做除法）；
- `nd` 含 0/负 → 返回 None；
- `t=1.5` → None；
- `t=3.0` → 通过；
- `fmin_eff=0` → `t_min_req=0`，`t_target=0` 仍应被“t_use>0”拒绝（一键紧绳）；张紧模式 `t=0` 允许（floor 禁用）。

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
- `t_min/t_max` 两框留空时，一键紧绳可正常启动；
- `t_use` 被 UI 界推出 `[t_min_req,t_max_allow]` 时明确拒绝；
- `targets[m]=0` 时松绳基准为 0，不回退；
- `sign=-1` 时松绳方向正确、地板禁放不禁紧；
- 紧绳各拒路径不改现有设置；失败全回滚；
- 恢复中→全缆正常 300ms→正常；停环亦清；
- ramp 进行中启动闭环 → ramp 即停；
- 全套 pytest 绿；台架先 1 N/小 `max_step`，再回 5 N。

---

## 6. 待用户修改的开放点

1. 低目标 `t=0.5/1.0` 的纯律测试是否保留？保留则必须标注“UI 不可达”；不保留则只测 `t=3.0` 与 `sign=-1`。
2. `t=0.2` 驻停分支的容差（`t≈0.42`）是否固定，还是只断言“最后 100 拍 step=0”。
3. 紧绳失败“启动成功但首拍停”是否需要自动回滚？v8.1 决定不回滚，只提示。
4. 默认 `trim_sign=1,1,1` 是否最终定案；若换线，需台架点动复核。

---

## 7. 一句话

v8.2 = v8.1 的仿真真值 + **断言分域**：高目标（`t≥t_min_req`）才承诺全员 ≥fmin；低目标只承诺“原本在 floor 以上的缆不被放穿”，C3 可以合法低于 fmin。这样测试不会再用 TDA 的 `T=t·n` 去要求张紧律。
