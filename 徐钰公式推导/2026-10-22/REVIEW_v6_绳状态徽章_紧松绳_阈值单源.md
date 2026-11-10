# REVIEW v6：绳状态徽章 / 紧松绳 / 张紧地板 / 阈值单源

> 审阅对象：`PLAN_v6_绳状态徽章_紧松绳_阈值单源.md`
> 审阅日期：2026-11-03
> 代码基线：`mmhand_scope.py` 4326 行、`wrist_force_law.py`（当前工作区）
> 结论：**P0-4 的修正正确；但 v6 仍有 4 个 P0 + 3 个 P1，直接实现会出现“一键紧绳永远拒绝 / 张紧仍有缆低于 fmin / fmin 两套 / 换布局方向反”。**

---

## 0. 先确认 v6 做对的部分

### 0.1 P0-4 的方向修正正确

v6 把 v5 的：

```python
if f_n[i] <= f_min and trim_sign[i] * step < 0:
```

改成：

```python
if p.f_min > 0 and f_n[i] <= p.f_min and step < 0:
```

推导：

```
trim = sign × step
Δ张力方向 = sign × trim = sign² × step = step
```

因为 `sign ∈ {+1,−1}`，`sign²=1`，所以：

- `step<0` 永远是物理放绳；
- `step>0` 永远是紧绳；
- 与 `trim_sign` 无关。

v5 的 `sign*step<0` 在 `sign=-1` 时等价于 `step>0`，会把“紧”禁掉、把“放”放行，确实全反。**v6 这一条是对的。**

### 0.2 v6 采纳的“清 integ/resid”也正确

只清 `e_i` 不够：`_incr_step` 里 `raw = kp*e + ki*integ`，即使 `e=0`，积分仍可能输出负 step，继续放绳。v6 同时清 `step/integ/resid` 是对的。

---

## 1. P0：必须改，否则功能不可用

### P0-1：D3 的 `clamp(t_tgt, t_min_ui, t_max_ui)` 在空值时会变成 0

v6 D3 写：

```python
t_use = clamp(t_tgt, t_min_ui, t_max_ui)
```

但 `t_min/t_max` 的语义是 **空 = 0 = 不启用**。当前布局正是：

```json
"t_min": "",
"t_max": ""
```

`_cl_fval("t_min", 0.0, ...)` 和 `_cl_fval("t_max", 0.0, ...)` 都返回 0，于是：

```
t_use = clamp(3.0, 0, 0) = 0
→ t_use ≤ 0 → 一键紧绳拒绝
```

**当前配置下一键紧绳会永远被“t 太小”拒绝。**

#### 正确写法

```python
t_use = t_tgt
if t_min_ui > 0:
    t_use = max(t_use, t_min_ui)
if t_max_ui > 0:
    t_use = min(t_use, t_max_ui)
```

或者把 `t_min/t_max` 解析成 `Optional[float]`（空=None），不要用 `clamp(..., 0, 0)`。

#### 必须补的测试

- `t_min="" / t_max=""` → 一键紧绳不应因 `t_use=0` 被拒；
- `t_min=2 / t_max=""` → 只下界生效；
- `t_min="" / t_max=4` → 只上界生效。

---

### P0-2：D4 地板不能保证“三缆贴 fmin”，`(10,3,0) t=1` 测试会失败

地板只在 `step<0` 时阻止放绳，**不能把已经低于 fmin 的缆拉回来**。

用你的 n̂：

```
n = (0.264, 0.595, 0.759)
f_min = 0.5
t_target = 1

T = t·n = (0.264, 0.595, 0.759)
C1 = 0.264 < 0.5
```

此时 `t_meas = f·n = 1 = t_target`，`err=0`，`step=0`；地板条件 `step<0` 不成立，**C1 就停在 0.264**。

所以：

- `t_target=1` 的终态不是“三缆贴 0.5”，而是 C1 低于 fmin；
- `(10,3,0) t=1` 的“全员贴地”断言会失败；
- 只有 `t_target ≤ fmin·Σn̂ ≈ 0.81` 时，地板才可能把三缆都压到 fmin；
- 要保证**每缆 ≥ fmin**，需要 `t_target ≥ fmin/min(n̂) ≈ 1.89`，或在 `_tight_params` 里把 `t_target` 钳到 `t_min_req`。

#### 正确做法（二选一）

**A. 拒绝不可行目标（推荐）**

`_tight_params` 里：

```python
t_min_req = fmin_eff / min(n)   # n 全正
if t_tgt < t_min_req:
    return None   # 或显示“t 太小，单缆会低于 fmin”
```

**B. 钳到可行域**

```python
t_tgt = max(t_tgt, t_min_req)
```

但这样“用户设 1，实际跑 1.89”，必须提示，不能静默。

#### 测试修正

- `t_target=0` → 三缆贴 fmin，验证地板；
- `t_target=1` → 断言 C1 低于 fmin（验证地板不足），或加 `t_min_req` 后断言三缆都 ≥ fmin。

---

### P0-3：D5 的 `fmin_eff = max(边界fmin, 0)` 漏掉了守卫 fmin

v6 D5 写：

```
fmin_eff = max(边界fmin, 0)
```

但验收清单又写“边界行与守卫框同设时取严”。如果：

- 边界 fmin = 0.5；
- 守卫 fmin = 2.0；

v6 的 `fmin_eff = 0.5`，显示/控制用 0.5，守卫在 2.0 才判松绳——**没有取严**。

#### 正确写法

```python
fmin_eff = max(boundary_fmin or 0.0, guard_fmin or 0.0)
fmax_eff = min(boundary_fmax, guard_fmax or math.inf)
```

#### 注意

- `fmin` 空/负 = 0（不启用下界）；
- 守卫 fmax 空 = 不额外收紧（+∞），不是 0；
- `fmax_eff ≤ fmin_eff` → invalid，启动拒绝，徽章“未设阈值/阈值非法”。

---

### P0-4：D7 改默认 `trim_sign` 为 `1,1,1`，但 tooltip 还写 M27=−1

当前布局确实是：

```json
"trim_sign": "1,1,1"
```

改默认值本身可以，但：

1. 代码 tooltip 还写着“2026-10-29 实测口径：M27 顺时针=放绳→−1”；
2. 如果实际 M27 仍是 −1，**新布局/重置布局后会变成正反馈**；
3. 仅凭一份布局存档不能证明所有机器/所有接线都是 +1。

#### 建议

- 改默认值的同时，更新 tooltip 和文档；
- 加一次“方向自检”：点动 +100 counts，看该缆张力升/降，确认后再允许一键紧/松；
- 至少在一键紧绳/松绳的门禁里提示“trim_sign 需台架确认”。

---

## 2. P1：会让现场行为不自然/难复现

### P1-1：D3 的 `t_use` 比较顺序 + `preload` 上限 100

v6 说 `t_tgt > t_max_allow` 要拒绝，但代码若先 `clamp` 到 `t_max_ui`，可能把超限目标悄悄压回可行域，变成“接受”。

另外 `preload` 在 `_force_params_v2` 里上限是 **100 N**；`t_use` 若 >100 会被静默钳到 100，一键紧绳的目标和实际不一致。

#### 建议

```
1) 先对原始 t_tgt 检查 [t_min_req, t_max_allow]
2) 再应用 UI t_min/t_max（条件式）
3) 最后检查 t_use ≤ 100（preload 上限）；超限拒绝/提示
```

不要用“先 clamp 再检查”的顺序。

---

### P1-2：D3 门禁缺少“位姿在模型行程内”

v6 门禁只写了 `n̂` 全正、t 区间、张力新鲜、三缆全勾，没有写 `angle_in_range`。

`_force_geo` 只检查 `math_valid`，出模型行程（roll ±25°、pitch −25…45°）仍返回 R；一键紧绳可能在 ±30°/pitch 50° 启动。

#### 建议

门禁增加：

```python
out.angle_in_range
```

不满足时拒绝并提示“位姿超出模型行程”。

---

### P1-3：D8 松绳的 ramp 与“启动闭环”会打架

`_on_release_rope` 走 `_send_motor_target`，会启动 `_ramp_timer`；`_start_closed_loop()`（`mmhand_scope.py:3209` 附近）没有停止 ramp。

用户松绳后马上启动闭环：

- ramp 还在每 50 ms 改 `targets`；
- 闭环又每 10 ms 发批量目标；
- 两者互相覆盖，松绳量/闭环起点都不可控。

#### 建议

`_start_closed_loop` 开头：

```python
self._ramp_timer.stop()
self._ramp_state.clear()
```

或松绳期间禁用“启动闭环”。

---

### P1-4：D5 守卫框留空时，`_tension_guard` 仍要能构造 effective cfg

v6 说“位置模式恢复过载停环”，但当前 `_tension_guard` 是：

```python
cfg = self._tension_cfg()
if cfg is None:
    return None, None
```

守卫框空就 `None` 直接返回。仅把 `fmax_eff` 算出来不够，必须让 `_tension_guard` 用 `_effective_flimits()` 构造判定（fmin/fmax 都来自 effective），否则位置模式仍然没有过载/松绳保护。

#### 建议

```python
fmin_eff, fmax_eff, valid = self._effective_flimits()
if not valid:
    return None, "⚠阈值非法→守卫未启用"
cfg = TensionConfig(f_min_n=fmin_eff, f_max_n=fmax_eff)
```

---

### P1-5：测试缺“空 t_min/t_max”和“t_target 在 0.81–1.89”两个用例

这两个用例能直接抓住上面两个 P0：

1. `t_min="" / t_max=""` → 一键紧绳不应 `t_use=0` 拒绝；
2. `t_target=1, f_min=0.5` → C1 低于 fmin，验证 D4 地板不足。

建议加入 `tests/test_scope_rope_state.py`。

---

## 3. v6 其他核对

| 项 | 结论 |
|---|---|
| `_force_fmax` 单源 `fmax_f` | 已存在，属实 |
| 缆卡着色用 `v_abs` | 已存在，属实；不要回退相对值 |
| 边界行六框 | 已存在（`mmhand_scope.py:1960-1992`） |
| `_tight_params` 未传 `f_min` | 属实，待加 |
| 布局 `f_min=-5000` | 属实；`_cl_fval` 下限 0 已钳成 0，迁移写 0 + 提示合理 |
| 布局 `trim_sign=1,1,1` | 属实；但 tooltip 仍旧口径，需同步 |
| `t_min/t_max` 空=0 | 属实；D3 必须用条件式，不能用 `clamp(...,0,0)` |

---

## 4. 建议的最小修正顺序

1. **P0-1**：D3 的 t 边界改成条件式，先让一键紧绳能跑。
2. **P0-2**：`_tight_params` 增加 `t_min_req` 钳制/拒绝；改测试 `t=1` 的预期。
3. **P0-3**：`fmin_eff` 纳入守卫 fmin。
4. **P0-4**：默认 `trim_sign` 改 +1 的同时更新 tooltip，并加方向自检提示。
5. **P1-1/2/3/4**：比较顺序、位姿门禁、ramp 停止、guard effective cfg。
6. 最后跑全套 pytest + 台架 1 N/小 `max_step`。

---

## 5. 一句话

v6 的 `step<0` 修正正确，事务/状态骨架也可以；但 **D3 的空 t_min/t_max 会让一键紧绳永远拒绝**，**D4 地板无法保证 fmin**，**D5 的 fmin 漏了守卫**，**D7 默认符号与 tooltip 冲突**——这四条不改，v6 落地后仍会出现“一键紧绳没反应 / 张紧仍有缆低于 fmin / 显示与控制两套 fmin / 换布局后方向反”。
