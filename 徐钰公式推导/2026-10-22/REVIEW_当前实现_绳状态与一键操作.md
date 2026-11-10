# REVIEW：当前绳状态 / 一键紧松绳实现审查

> 日期：2026-11-03
> 范围：`mmhand_scope.py` 当前 4696 行版本、`wrist_force_law.py`、新增测试
> 结论：**功能骨架已经落地，但显示层和恢复态有 5 个 P0 级行为错误；测试 79 条 wrist 全绿，但这些用例没覆盖到。**

---

## 0. 测试现状

| 测试集 | 结果 |
|---|---|
| `test_scope_rope_state.py` + `test_wrist_force_modes.py` + `test_scope_cable_enable.py` + `test_wrist_force_v2.py` | **79 passed** |
| 全套 pytest | 447 passed / **13 failed**（均在 `tests/desktop/*` 旧桌面协议/架构测试，与本次绳状态改动无关，但 CI 是红的） |

**关键：** 79 条全绿不代表 UI 没问题；下面几条都是测试没覆盖的显示/生命周期路径。

---

## 1. P0：会直接显示错误或状态错误

### P0-1 逐缆状态章不判 stale / no-data

代码：[`_refresh` 缆卡循环](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L987-L1035)

```python
if fvals is None:
    card.set_row(...)
    continue                    # ← 没更新 card.chip
...
if fvals is not None and v_abs is not None:
    if fmax ...: chip = 过紧
    elif fmin ...: chip = 放松
    ...
```

问题：

- `fvals is None` 时直接 `continue`，**chip 保留上一次的“正常”**；
- `stale=True`（张力样本 >500 ms）时，缆卡数字变灰并标“旧”，但 **chip 仍是“正常/放松/过紧”**；
- 整体徽章 `rope_state(f_for_state=None)` 会显示“无数据”，逐缆章却显示“正常”，两者打架。

**实测（offscreen 探针）：**

```
fresh chip: 🟢 正常
stale chip: 🟢 正常      ← 1 s 无新样本仍是正常
none chip:  🟢 正常      ← fvals=None 仍是正常
```

**修复：**

```python
if fvals is None or stale:
    card.chip.setText("<span style='color:#8b95a6'>⚪ 无数据</span>")
    if fvals is None:
        card.set_row(...); continue
# stale 时仍显示旧值/旧曲线，但 chip 必须是“无数据”
```

---

### P0-2 逐缆 τ 用“相对张力”算，去皮/清零后显示错

代码：[`_refresh` 缆卡 τ](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L990-L1016)

```python
v_abs = fvals[i]                       # 绝对张力，判定用
v = v_abs - (zero[i] if zero ...)     # 显示相对值
...
tr = out.r_m[ROLL][i]  * v * 1000.0   # ← 用了相对值
tp = out.r_m[PITCH][i] * v * 1000.0
```

张力判定用了 `v_abs`，但逐缆 τ 显示用了 `v`。一旦做了“去皮/清零”，τ 会跟着零点偏移，**显示的不是真实力矩**。

**实测：** C1 清零 1 N，实际 2 N：

```
τ 显示 ≈ -58 mN·m（按 1 N 算）
真实应为 ≈ -116 mN·m（按 2 N 算）
```

**修复：**

```python
tr = out.r_m[ROLL][i]  * v_abs * 1000.0
tp = out.r_m[PITCH][i] * v_abs * 1000.0
```

---

### P0-3 恢复 300 ms 计时器不重置，第二次一键紧绳会“秒结束”

代码：

- [`_update_recovery_flag`](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L3074-L3096)
- [`_stop_closed_loop`](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L3463-L3467)
- [`_on_tighten_rope`](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L4107-L4197)

`_stop_closed_loop` 只清：

```python
self._force_recovery = False
```

**没有清 `_recovery_ok_since`**。`_on_tighten_rope` 成功后又只：

```python
self._force_recovery = True
```

**没有把 `_recovery_ok_since` 置 None**。

于是第二次一键紧绳时，`_recovery_ok_since` 可能还是上一轮的旧时间戳；下一次张力样本一进来，`now - since >= 0.3` 立刻成立，**“恢复中”瞬间变“正常”**。

**实测：**

```
_force_recovery=True, _recovery_ok_since=now-1.0
_on_tension_sample(2,2,2)
→ _force_recovery 立刻变 False
```

**修复：**

- `_stop_closed_loop()` 里 `self._recovery_ok_since = None`（放在 early return 之前）；
- `_on_tighten_rope()` 置 `_force_recovery=True` 时同时 `self._recovery_ok_since = None`；
- 失败回滚也清 `_recovery_ok_since`。

---

### P0-4 `tighten_t_use` 不拒绝 `t_min_ui > t_max_ui`

代码：[`tighten_t_use`](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L184-L202)

```python
t_use = float(t_tgt_raw)
if t_min_ui > 0: t_use = max(t_use, t_min_ui)
if t_max_ui > 0: t_use = min(t_use, t_max_ui)
...
if not (t_min_req <= t_use <= t_max_allow): reject
```

如果用户把 `tmin` 填 5、`tmax` 填 3：

```python
tighten_t_use(4, 5, 3, 1.89, 39.5) -> (3, None)
```

它先 `max→5` 再 `min→3`，最后用 **3** 通过校验，**违反了 tmin=5**。`_tight_params` 对同样的输入会 `return None`，一键紧绳和张紧模式行为不一致。

**修复：**

```python
if t_min_ui > 0 and t_max_ui > 0 and t_max_ui <= t_min_ui:
    return None, "tmin 必须 < tmax"
```

---

### P0-5 armed 状态改逐绳勾选，P4 活动域不更新（存量，但直接影响一键紧绳）

代码：[`_on_cable_enable_toggled`](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L2587-L2601)

```python
if self.cl_enabled:
    self._stop_closed_loop("使能范围变更")
# 只 refresh/保存，没有重新使能、没有重发 active scope
```

P4 的 `active_motor_mask` 还是旧的。一键紧绳虽然检查“三缆全勾选”，但 P4 可能只认旧的 1–2 台：

- 新勾选的绳：`_send_motor_batch` 发了目标，P4 活动域不含它 → **不动**；
- 取消勾选的绳：P4 仍含它 → **继续按旧目标保持/运动**。

这会让一键紧绳“界面显示在跑，实际只有部分绳在动”，然后 TDA/张力环一直积误差。

**修复：** 改勾选时如果 `armed`，先 `_on_stop()` 强制解除武装；用户必须重新使能，使能时才会重发 active scope。或 STOP → active scope → 重新使能。

---

## 2. P1：会留脏状态 / 显示不一致

### P1-1 一键紧绳不预检“当前张力已过载/NaN”

`_on_tighten_rope` 只检查样本年龄，不检查：

```python
any(not math.isfinite(v) for v in last[1])
any(v > fmax_eff for v in last[1])
```

如果当前已经过载：

1. 它先切力矩模式、改 tau/preload；
2. `_start_closed_loop()` 成功；
3. 第一拍 `_tension_guard` 检测过载 → `_stop_closed_loop`；
4. `_force_recovery` 被清，但 **模式/tau/preload 已经改了，不会回滚**。

用户看到“启动后立刻停止”，参数却已被覆盖。建议在事务前加：

```python
if any(not math.isfinite(v) or v > fmax_eff for v in last[1]):
    reject("当前张力已过载/非法，先松绳")
```

### P1-2 一键紧绳只捕获 `KeyError/RuntimeError`

```python
except (KeyError, RuntimeError) as exc:
```

`_start_closed_loop()` 内部任何其他异常（`AttributeError`、`TypeError`、`ValueError` 从某条 UI 路径冒出）都会跳过回滚，留下“力矩模式 + tau=0 + 新 preload”的脏状态。建议 `except Exception`（UI 事务层可以宽）并回滚。

### P1-3 三套阈值判定不一致

- 整体徽章：`rope_state` 用 **0.05 N 滞回**；
- 逐缆章：直接用 `v_abs > fmax` / `v_abs < fmin`，**无滞回**；
- 汇总行：直接用 `f_for_state[i] < fmin` / `> fmax`，**无滞回**。

在 fmin=0.5、f=0.46 时：

- 徽章：0.46 > 0.45 → **正常**；
- 逐缆章：0.46 < 0.5 → **放松**；
- 汇总：0.46 < 0.5 → **放松**。

同一个样本三种显示。另外 `_ok`（fmax>fmin）在 `_refresh` 里被忽略：阈值非法时仍可能显示“过紧/正常”，而不是“阈值非法”。

**修复：** 抽一个 `cable_state(v, fmin, fmax, hyst)` 给三处共用；`_ok=False` 时统一显示“⚠阈值非法”。

### P1-4 `rope_state` 不处理 NaN / 非法阈值

```python
if has_hi and any(v > fmax + hyst ...):
if has_lo and any(v < fmin - hyst ...):
```

`v=NaN` 时两个 `any` 都 False，返回 `normal`。传感器 NaN 会显示“正常”。建议开头：

```python
if any(not math.isfinite(v) for v in f_vals):
    return "no_data", "⚪ 无数据"
```

`fmin/fmax` 非法（fmax≤fmin）也应返回 `unset`。

### P1-5 松绳 `baseline` 回退与 `_send_motor_target` 起点不一致

`_on_release_rope`：

```python
baseline = t if t is not None else self._motor_pos_now(m)
out = baseline + delta
self._send_motor_target(m, out)
```

但 `_send_motor_target` 内部：

```python
cur = self.targets.get(motor)
start = cur if cur is not None else self._soft_limit_base(motor)
```

如果 `targets[m]` 是 None，`_on_release` 用**实际位置**算目标，`_send_motor_target` 却从**原点**开始斜坡；ramp 打开时会从 origin 往目标走，可能大跳。

**修复：** 在 `_on_release` 里先 `self.targets[m] = baseline`，或给 `_send_motor_target` 增加显式 `start` 参数。

### P1-6 按钮不刷新 enabled/tooltip

`tighten_rope_btn` / `release_rope_btn` 一直可点，只有 handler 里 gate。用户点击后才知道“未使能/闭环中/无张力”。计划里的“随门禁刷新使能+tooltip 原因”没实现。不是功能错误，但体验差。

### P1-7 死代码/冗余

- `_tension_cfg()` 已无人调用（`_tension_guard` 改用 `_effective_flimits`）——可删；
- `_on_tighten_rope` 里 `idx = {...}[self._cl_mode]` 未使用——可删；
- `_on_tighten_rope` 的 `backup` 不含 `_recovery_ok_since`——与 P0-3 同源。

---

## 3. P2：旧问题仍在，和这次功能叠加

### P2-1 状态包 `direct_reject=st[29]` 仍是错的

[`mmhand_scope.py:425-435`](E:/SLAHAND/mmhand_wrist_control_1.0/code/mmhand-main/mmhand_scope.py#L425-L435)

`direct_reject_reason` 是第 34 位，`st[29]` 是 `rope_init_sequence`。一键紧绳启动失败时，界面显示的拒绝原因是错的。

同时 `status_info` 仍没有：
- `system_fault`
- `encoder_warn/encoder_fault`
- `collision_hold`
- `active_motor_mask`

这会让 P0-5 的“活动域是否真的包含三缆”无法从 PC 侧校验。

### P2-2 `_update_recovery_flag` 没有滞回/NaN 保护

`all(fmin <= v <= fmax)` 对 NaN 为 False，会重置计时；但徽章可能显示正常。建议与 `rope_state` 共用 finite/阈值判断。

---

## 4. 建议修复顺序

1. **P0-1/P0-2**：显示层，先让“无数据/过载/τ”不再骗人；
2. **P0-3**：恢复计时器重置，保证“恢复中”语义；
3. **P0-4/P1-3**：阈值/边界一致性；
4. **P0-5**：改勾选强制重新使能（或重发 active scope）；
5. **P1-1/P1-2**：一键紧绳事务补 current-f 预检 + 宽异常回滚；
6. **P1-5/P1-6**：松绳起点、按钮状态；
7. 清死代码，补测试。

---

## 5. 必须补的测试

- `_refresh`：`fvals=None` / `stale=True` 时逐缆章必须是“无数据”；
- `_refresh`：清零/去皮后逐缆 τ 用绝对张力（与 `v_abs` 一致）；
- `rope_state`：NaN、fmax≤fmin、fmin=0；
- `_on_tighten`：`tmin>tmax` 拒绝；`recovery_ok_since` 旧值不导致秒清；
- `_on_tighten`：当前 f 过载/NaN 拒绝且不改模式；
- `_on_release`：`targets[m]=None` 时 ramp 起点用实际位置；
- `_on_cable_enable_toggled`：armed 时改勾选后，active scope/重新使能行为有断言（需要 fake P4/status）。

---

## 6. 一句话

当前实现“主路径能跑”，但显示层有三处会**把 stale 显示成正常、把相对张力当绝对张力算 τ、三个阈值判定各说各话**；恢复态有一个**旧计时器导致秒结束**；一键紧绳还有一个**tmin>tmax 仍接受**的边界洞。先把这五个 P0 修掉，再谈台架紧绳。
