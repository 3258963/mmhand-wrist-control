# PLAN v7：绳状态徽章 + 逐缆状态章 + 一键紧/松绳 + 张紧地板 + 阈值单源（终版）

> 版本：v7（v6 + REVIEW_v6 全部采纳；链条 v5→审→v6→审→v7）
> 日期：2026-11-03
> 范围：PC 上位机 `mmhand_scope.py`、`wrist_force_law.py`、测试
> 前提：运行中松绳分级守卫/看门狗已按用户决定删除；守卫维持"松绳仅⚠、过载停环"；不动 α/TDA/增量律。

---

## 0. v6 → v7 修正记录（REVIEW_v6 裁定：4 P0 全部成立，P1 五条采纳四条）

| # | 来源 | v6 缺陷 | v7 修正 |
|---|---|---|---|
| P0-1 | REVIEW | `clamp(t_tgt, t_min_ui, t_max_ui)` 在两框空时=clamp(x,0,0)=0 → 一键紧绳永远拒绝 | **条件式**：空(=0)的界跳过，不参与 clamp（§2-D3） |
| P0-2 | REVIEW | 地板只拦"放"不"提"，t=1 收敛态 C3≈0.45<fmin；v6 测试断言"全员贴地"必挂 | ①`_tight_params` 加 `t_min_req = fmin_eff/min(n̂)` 拒绝（"t 太小，单缆会低于 fmin"）；②测试期望按真实分域改写（§3） |
| P0-3 | REVIEW | `fmin_eff=max(边界,0)` 漏守卫 fmin，与"取严"验收自相矛盾 | `fmin_eff = max(边界fmin, 守卫fmin, 0)`；`fmax_eff = min(边界fmax_f, 守卫fmax 或 +∞)`（§2-D5） |
| P0-4 | REVIEW | 默认 sign 改 1,1,1 但 tooltip 仍写旧口径"M27=−1" | tooltip 同步改写为修正口径（三台 counts↑=收绳），附"换接线后点动复核"提示（§2-D7）；自动点动自检暂缓 |
| P1-1 | REVIEW | 检查顺序 + preload 静默钳 100 | 顺序定为：原始 t_tgt 验可行域 → 条件式 UI 界 → t_use>100 拒绝（§2-D3） |
| P1-2 | REVIEW | 门禁缺位姿行程检查 | precheck 加 `out.angle_in_range`（§2-D3） |
| P1-3 | REVIEW | ramp 与启动闭环互踩（**存量 bug**，位置模式同样存在） | `_start_closed_loop` 开头 `_ramp_timer.stop()` + 清 ramp 状态（§2-D9） |
| P1-4 | REVIEW | 守卫必须用 effective 构造 cfg | v6 已列"接入五处"，v7 落成明确代码（§2-D5） |

v6 保留有效的部分：P0-4 方向修正 `step<0`（REVIEW §0.1 确认推导正确）、清 integ/resid、事务化骨架、恢复 300ms 自动清、阈值单源方向。

---

## 1. 代码实况基线（2026-11-03 复核）

| 事实 | 状态 |
|---|---|
| 布局 `trim_sign="1,1,1"`、`f_min="-5000"`（钳0=禁用下界）、`t_min/t_max=""`、`cl_mode=tension` | 已核 |
| UI 默认 `trim_sign` 文本 `-1,1,1`（mmhand_scope.py:1950）+ tooltip 旧口径 | 待修（D7） |
| `_force_fmax` 单源 `fmax_f`；缆卡着色 `v_abs` 绝对；边界行六框已存在 | 已存在勿重复 |
| `_tight_params` 未传 f_min；`WristTightParams` 无 f_min | 待加 |
| `_start_closed_loop` 不停 ramp（:3209 区域） | 待修（D9） |

---

## 2. 设计决策（终版）

### D1. 恢复状态机（不变，v6 原样）
`_force_recovery`：置=紧绳启动成功后；清=三缆进界连续 300ms（30 拍）∨ 停环 ∨ 失败回滚。
优先级 无数据>过紧>放松>恢复中>正常；15Hz；0.05N 滞回。

### D2. 松绳方向（不变）
`release_delta_i = -RELEASE_COUNTS(2500) × trim_sign[i]`；baseline=targets（None→`_motor_pos_now`）；
钳 ±30000；张力新鲜<0.5s；三缆全不勾→拒绝；走 `_send_motor_target`。

### D3. 一键紧绳（事务化 + P0-1/P1-1/P1-2 修正）
门禁（全满足才动）：
```
armed ∧ not cl_enabled ∧ 张力新鲜(<0.5s) ∧ 三缆全勾选
∧ n̂ 存在且全正 ∧ 位姿 in angle_in_range（模型行程内）
∧ t_min_req ≤ t_tgt_raw ≤ t_max_allow
    t_min_req  = max_i(fmin_eff/n_i)        # = fmin_eff/min(n̂)
    t_max_allow= min_i(fmax_eff/n_i)
```
t_use 计算（**条件式，空界跳过，绝不用 clamp(·,0,0)**）：
```python
t_use = t_tgt_raw                    # 先对原始值验可行域（上）
if t_min_ui > 0: t_use = max(t_use, t_min_ui)
if t_max_ui > 0: t_use = min(t_use, t_max_ui)
if t_use > 100: 拒绝("预紧上限 100N")   # preload 参数域上限，不静默钳
```
执行（事务）：①备份 mode/tau_roll/tau_pitch/preload → ②切力矩模式、τ=0、preload=t_use →
③`_start_closed_loop()` → ④cl_enabled=True 才置 recovery → ⑤失败恢复备份+清 flag+提示。
权威：紧绳用 `t_tgt`，力矩模式手动用 `preload`（tooltip 写明）。

### D4. 张紧地板（v6 修正版维持 + P0-2 补 t_min_req）
律内（`_incr_step` 之后）：
```python
if p.f_min > 0.0 and f_n[i] <= p.f_min and step < 0:   # step<0=物理放（推导见 v6 §1.3，REVIEW 确认）
    step = 0.0; state.integ[i] = 0.0; state.resid[i] = 0.0
trim[i] = p.trim_sign[i] * step
```
**地板职责澄清（P0-2）**：只拦"放"不"提"；逐缆 ≥fmin 的保证由 `_tight_params` 的 t_min_req 拒绝承担
（t 目标 < fmin_eff/min(n̂) → 参数非法拒绝启动）。两者分工：地板=运行时防放穿；t_min_req=入口处保证可达逐缆下界。
`_tight_params` 传 `fmin_eff`（含 t_min_req 检查）。

### D5. 有效阈值单源（P0-3 修正）
```python
def _effective_flimits(self):
    fmin_eff = max(边界fmin 或 0, 守卫fmin 或 0)      # 负值一律视 0（禁用下界）
    fmax_eff = min(边界fmax_f 默认30, 守卫fmax 或 +inf)
    valid = fmax_eff > fmin_eff
```
`_tension_guard` 改造（P1-4 落死）：
```python
fmin_eff, fmax_eff, valid = self._effective_flimits()
if not valid: return None, "⚠阈值非法→守卫未启用"
cfg = TensionConfig(f_min_n=fmin_eff, f_max_n=fmax_eff)
```
接入五处：`_force_params_v2` / `_tight_params` / `_tension_guard`（位置模式恢复过载停环）/
`_force_fmax` / 缆卡着色·逐缆章·徽章。

### D6. 状态判定纯函数（不变）
`rope_state(f, fmin, fmax, recovery, has_data, hyst=0.05)`：六态 no_data/over/slack/recovering/normal/unset；
绝对张力判定；fmin≤0 跳下界（fmax 仍判）；逐缆章四态；汇总"放松：Cx｜过紧：无｜正常：…"。

### D7. UI（P0-4 修正）
- 徽章+汇总行加力状态块（15Hz）；缆卡逐缆章；
- **trim_sign 默认文本与 tooltip 同步改**：默认 `1,1,1`；tooltip 改写为
  "修正口径（2026-10-29 更正）：三台 counts↑=收绳 → 全 +1；换接线后请点动复核（+100c 看张力升/降）"；
- 两按钮随门禁刷新使能+tooltip 原因。

### D8. 松绳安全（不变）
### D9. ramp/闭环互斥（P1-3 新增）
`_start_closed_loop()` 开头：
```python
self._ramp_timer.stop()
self._ramp_state.clear()      # 或等价清空，按现有属性名
```
（存量 bug 修复：位置模式今天同样存在 ramp 改 targets 与闭环批量帧互踩。）

---

## 3. 测试（按 P0-2 真实分域改写）

`tests/test_wrist_force_modes.py` 地板组：
- (10,3,0)、t=0.5、fmin=0.5 → **全员贴 0.5、t≈0.81 安全驻点**（t<0.81 分域：地板全权）；
- (10,3,0)、t=1.0、fmin=0.5 → 收敛 t=1 且 C1/C2≥0.5、**允许 C3<0.5**（0.81<t<1.89 分域：地板只防放穿，逐缆下界不保证——文档化行为）；
- t=1.5、fmin=0.5 → `_tight_params` 因 t<t_min_req(1.89) **拒绝**（入口保证分域）；
- sign=−1 + integ≠0 用例（防 v5 方向 BUG 回归 + 地板不误禁紧）。

`tests/test_scope_rope_state.py`：
- rope_state 六态/优先级/滞回/空阈值降级/fmin≤0 跳下界/清零下绝对判定；
- release_delta：sign=(+1,−1,+1) → (−2500,+2500,−2500)；
- **紧绳 t_use 计算专项（钉 P0-1）**：t_min=""/t_max="" → t_use=t_tgt 不被钳 0；单边设置各生效；>100 拒绝；
- precheck 全拒路径（n̂缺/非全正/位姿出行程/t 太小/t 太大/张力过期/非三缆全勾）+ 成功 + 失败回滚（模式/参数/flag 全还原）；
- 松绳落点/None 基线/±30000/全不勾拒绝；
- **ramp 互斥（钉 P1-3）**：ramp 活动时启动闭环 → ramp 停止且状态清；
- 端到端：放松→紧绳→恢复中→全缆正常 300ms→正常。

---

## 4. 迁移
fmin 负值→0（禁用）+提示一次；fmax_f 空→写 30+提示；t_min/t_max 空=0 不启用；`_force_recovery` 不落盘。

## 5. 实施顺序
Phase 0 纯函数+单测（effective_flimits/rope_state/release_delta/precheck/地板/t_min_req）→
Phase 1 UI 显示 → Phase 2 按钮事务 → Phase 3 守卫/TDA 单源 + ramp 互斥 + 端到端回归。

## 6. 验收（台架）
- 三缆松紧不均 → 章/汇总一致；清零后判定仍绝对；
- 双阈值同设取严；守卫框空时位置模式仍有 fmax 过载停环；
- sign=−1 时松绳方向正确、地板禁放不禁紧；
- 紧绳各拒路径不动现有设置；失败全回滚；**t 两框留空时紧绳键可正常启动**；
- 恢复中→正常 300ms 自动；停环亦清；
- ramp 进行中启动闭环 → ramp 即停；
- 全套 pytest 绿；台架先 1N/小 max_step，再回 5N。

## 7. 一句话
v7 = v6 骨架 + 四个 P0 修正（t_use 条件式、地板/t_min_req 分工、fmin 取严、tooltip 同步）+
三个 P1（检查顺序、位姿门禁、ramp 互斥存量修复）；至此 v5→v7 的每一处方向与边界都有推导或测试钉死。
