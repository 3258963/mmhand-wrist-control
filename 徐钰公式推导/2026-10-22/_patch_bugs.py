# -*- coding: utf-8 -*-
"""一次性修复位置闭环 + 扫掠的已知 BUG（2026-11-10）。

每条补丁都先断言锚点唯一存在，避免误改；改完打印清单。
用法：python _patch_bugs.py [--check]   （--check 只校验不落盘）
"""
import pathlib
import sys

ROOT = pathlib.Path(r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main")
SCOPE = ROOT / "mmhand_scope.py"
LAW = ROOT / "wrist_control_law.py"
TEST_SINE = ROOT / "tests" / "test_sweep_sine.py"
TEST_ROPE = ROOT / "tests" / "test_scope_rope_state.py"

CHECK = "--check" in sys.argv
applied = []


def read_lines(path):
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def find_line(lines, needle):
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    assert len(hits) == 1, f"锚点命中 {len(hits)} 次: {needle!r}"
    return hits[0]


def find_exact(lines, text):
    hits = [i for i, ln in enumerate(lines) if ln.rstrip("\r\n") == text]
    assert len(hits) == 1, f"整行锚点命中 {len(hits)} 次: {text!r}"
    return hits[0]


def insert_after(lines, needle, block, tag):
    i = find_line(lines, needle)
    lines[i + 1:i + 1] = [b + "\n" for b in block]
    applied.append(tag)


def insert_before(lines, needle, block, tag):
    i = find_line(lines, needle)
    lines[i:i] = [b + "\n" for b in block]
    applied.append(tag)


def replace_at(lines, idx, to_delta, block, tag):
    lines[idx:idx + to_delta + 1] = [b + "\n" for b in block]
    applied.append(tag)


def replace_text(path, old, new, tag):
    src = path.read_text(encoding="utf-8")
    assert src.count(old) == 1, f"{tag}: 文本命中 {src.count(old)} 次"
    if not CHECK:
        path.write_text(src.replace(old, new), encoding="utf-8", newline="")
    applied.append(tag)


# =====================================================================
# 一、mmhand_scope.py
# =====================================================================
lines = read_lines(SCOPE)

# --- 1. 位置模式没有模型前馈 → 启动即拒绝（不再静默保持） ---
insert_after(lines, "模型前馈已勾选但标定未载入", [
    '        if self._cl_mode == "position" and not (',
    '                self.cl_model_check.isChecked() and self.wrist_calib is not None):',
    "            # 2026-11-10：手填系数已删，没有前馈的位置环输出恒等于 origin；",
    "            # 启动时 targets 也等于 origin，变更抑制会把每一帧都滤掉——",
    "            # 现象就是「点了启动，一动不动」。宁可直接拒绝，也不静默保持。",
    '            return ("位置模式需要「模型前馈」：先点「📥 载入标定」并勾选「模型前馈」"',
    '                    "（手填系数已删除，无前馈时位置环不会产生任何输出）")',
], "scope: 位置模式门禁")

# --- 2. 启动时刷新 origin + 空参数框回填生效值 ---
i = find_line(lines, "没有模型前馈时位置环只能")
replace_at(lines, i - 1, 3, [
    '        if self._cl_mode == "position":',
    "            # 2026-11-10 修复①：origin 记的是「使能那一刻」的位置。使能后点动过",
    "            # （或重力下沉），启动闭环会先朝旧起点跳一段。位置模式的起点改用",
    "            # 启动时的实测位置；无数据的电机保留原值。",
    "            for m in SERVO_TARGETS:",
    '                v = self.channels[f"m{m}_abs"].buf.last()',
    "                if v is not None and not math.isnan(v):",
    "                    self._motor_origin[m] = int(v)",
    "            # 2026-11-10 修复②：空框=走默认值（死区 0.3° 等），界面上看不出来。",
    "            # 启动时把生效值写回框里，所见即所算。",
    '            for key, default in (("kp", 0.6), ("deadband", 0.3),',
    '                                 ("limit", 25.0), ("max_step_f", 5.0)):',
    "                e = self.cl_edits.get(key)",
    "                if e is not None and not e.text().strip():",
    '                    e.setText(f"{default:g}")',
], "scope: 启动刷新 origin + 参数回填")

# --- 3. 模型路径传入分轴开关 ---
i = find_line(lines, "prm, self.wrist_calib, roll, pitch, roll_tgt, pitch_tgt)")
replace_at(lines, i - 1, 1, [
    "            outputs, flags = wrist_control_step_model(",
    "                prm, self.wrist_calib, roll, pitch, roll_tgt, pitch_tgt,",
    "                roll_enabled=self.cl_roll_check.isChecked(),",
    "                pitch_enabled=self.cl_pitch_check.isChecked())",
], "scope: 分轴开关接入模型路径")

# --- 4. 未勾选的缆不推目标曲线（模型 / v1 两处） ---
i = find_exact(lines, "                raw = {}")
replace_at(lines, i, 4, [
    "                raw = {}",
    "                for m, out in zip(SERVO_TARGETS, outputs):",
    "                    if m in self._cl_motor_on:",
    "                        raw[m] = out        # 未勾选的缆不推曲线（看着动、实际不下发）",
    '                        self.channels[f"m{m}_tgt"].buf.append(now_rel, float(out))',
], "scope: 模型路径目标曲线只推已驱动缆")

i = find_exact(lines, "        raw = {}")
replace_at(lines, i, 4, [
    "        raw = {}",
    "        for m, out in zip(SERVO_TARGETS, outputs):",
    "            if m in self._cl_motor_on:",
    "                raw[m] = out        # 未勾选的缆不推曲线（同上）",
    '                self.channels[f"m{m}_tgt"].buf.append(now_rel, float(out))',
], "scope: v1 路径目标曲线只推已驱动缆")

# --- 5. _sweep_tick：真实 dt + 独立幅值 + 相位取模 ---
i = find_exact(lines, "    def _sweep_tick(self) -> None:")
replace_at(lines, i, 21, [
    "    def _sweep_tick(self, dt: float | None = None) -> None:",
    '        """20Hz：闭环运行且勾选扫掠时推进所选轴目标波形（±幅值内）。',
    "",
    "        三角波：按速度°/s 线性往返（录标定用，慢到准）。",
    "        正弦波：目标 = A·sin(2πf·t)，A=「幅值°」框（默认跟随限幅）、f=频率框、",
    "        相位从勾选时刻起算。峰值速度需求 = A·2πf——超过每拍限幅折算的速度",
    "        上限（max_step_f×100Hz）就会削顶/滞后，正是带宽测试要观察的现象。",
    "",
    "        dt：本拍步长（s）。缺省按真实墙钟算——旧版写死 0.05，主线程忙时",
    "        定时器延迟会让实际频率低于设定值，带宽测试会系统性低估（2026-11-10 修复）。",
    "        显式传 dt 供测试复现固定步长。",
    '        """',
    "        if not (self.cl_enabled and self.sweep_check.isChecked()):",
    "            return",
    "        now = time.monotonic()",
    '        last = getattr(self, "_sweep_ts", None)',
    "        self._sweep_ts = now",
    "        if dt is None:",
    "            # 首拍按标称 50ms；卡顿/挂起时钳到 0.2s，别让相位一次跳半圈",
    "            dt = 0.05 if last is None else min(max(now - last, 0.001), 0.2)",
    '        lim = self._cl_fval("limit", 25.0, 1.0, 90.0)',
    "        amp = min(self.sweep_amp.value(), lim)",
    "        if self.sweep_wave_combo.currentIndex() == 1:      # 正弦波",
    "            self._sweep_phase = (self._sweep_phase",
    "                                 + 2.0 * math.pi * self.sweep_freq.value() * dt)",
    "            self._sweep_phase %= 2.0 * math.pi",
    "            v = amp * math.sin(self._sweep_phase)",
    "        else:                                              # 三角波（原有）",
    "            v = self._sweep_val + self._sweep_dir * self.sweep_speed.value() * dt",
    "            if v >= amp:",
    "                v, self._sweep_dir = amp, -1.0",
    "            elif v <= -amp:",
    "                v, self._sweep_dir = -amp, 1.0",
    "        self._sweep_val = v",
    '        self.cl_edits[self._sweep_key()].setText(f"{v:+.2f}")',
], "scope: 扫掠真实 dt + 幅值 + 相位取模")

# --- 6. 勾选扫掠时重置时间戳 ---
insert_after(lines, "self._sweep_phase = 0.0   # 正弦从相位 0 重新起算", [
    "        self._sweep_ts = None     # 下一拍按标称步长起算",
], "scope: 勾选扫掠重置时间戳")

# --- 7. 幅值输入框 ---
insert_after(lines, "tgt_row.addWidget(self.sweep_speed)", [
    "        self.sweep_amp = QDoubleSpinBox()",
    "        self.sweep_amp.setRange(0.5, 90.0)",
    "        self.sweep_amp.setDecimals(1)",
    "        self.sweep_amp.setValue(25.0)",
    '        self.sweep_amp.setSuffix("°")',
    "        self.sweep_amp.setToolTip(",
    '            "波形幅值（峰）°：正弦/三角都按它摆；超过「限幅°」时按限幅截断。\\n"',
    '            "正弦峰值速度 = 幅值×2πf，超过每拍限幅折算的速度就会削顶。")',
    "        tgt_row.addWidget(self.sweep_amp)",
], "scope: 扫掠幅值框")

# --- 8. 切轴信号 ---
insert_after(lines, 'self.sweep_axis.addItems(["ROLL", "PITCH"])', [
    "        # 扫掠中切轴：按新轴目标框重新播种（否则目标跳到上一轴的值）",
    "        self.sweep_axis.currentIndexChanged.connect(self._on_sweep_axis_changed)",
], "scope: 切轴信号")

# --- 9. 切轴处理函数 ---
insert_before(lines, "def _sweep_tick(self, dt: float | None = None) -> None:", [
    "    def _on_sweep_axis_changed(self, _index: int) -> None:",
    '        """扫掠中切轴：按新轴目标框重新播种 + 相位归零（2026-11-10 修复）。"""',
    "        try:",
    "            self._sweep_val = float(",
    '                self.cl_edits[self._sweep_key()].text().strip().replace("−", "-"))',
    "        except ValueError:",
    "            self._sweep_val = 0.0",
    "        self._sweep_dir = 1.0 if self._sweep_val <= 0 else -1.0",
    "        self._sweep_phase = 0.0",
    "        self._sweep_ts = None",
    "",
], "scope: 切轴重播种")

# --- 10. 停环时把扫掠轴目标收口到实测角度 ---
i = find_line(lines, "self.sweep_check.setChecked(False)   # 停闭环同时停扫掠")
replace_at(lines, i, 0, [
    "        was_sweep = self.sweep_check.isChecked()",
    "        self.sweep_check.setChecked(False)   # 停闭环同时停扫掠",
    '        if was_sweep and self._cl_mode == "position":',
    "            # 扫掠把目标框推到过 ±幅值，停环后留在那儿，下次启动会先跳过去。",
    "            # 用实测姿态收口：目标就停在你现在所在的角度（2026-11-10 修复）。",
    "            pose = self._wrist_pose_now()",
    "            if pose is not None:",
    "                key = self._sweep_key()",
    "                self.cl_edits[key].setText(",
    "                    f\"{pose[0] if key == 'roll_tgt' else pose[1]:+.2f}\")",
], "scope: 停环收口扫掠目标")

# --- 11. 标定静默载入 ---
i = find_exact(lines, "    def _load_wrist_calib(self) -> None:")
replace_at(lines, i, 1, [
    "    def _load_wrist_calib(self, quiet: bool = False) -> None:",
    '        """载入 wrist_calib.json -> self.wrist_calib；失败显式提示原因。',
    "",
    "        quiet=True 供启动自动载入：不写状态行，免得盖掉开机提示。",
    '        """',
], "scope: _load_wrist_calib quiet")

i = find_line(lines, "已载入腕部标定：模型前馈可用")
replace_at(lines, i, 0, [
    "        if not quiet:",
    '            self._ctrl_status("📥 已载入腕部标定：模型前馈可用")',
], "scope: 载入标定静默")

i = find_line(lines, "self.cl_load_btn.clicked.connect(self._load_wrist_calib)")
replace_at(lines, i, 0, [
    "        self.cl_load_btn.clicked.connect(lambda: self._load_wrist_calib())",
], "scope: 载入按钮 lambda")

# --- 12. 持久化 cl_model_on + 启动自动载入标定 ---
insert_after(lines, '"cl_params": {k: e.text() for k, e in self.cl_edits.items()},', [
    "            # 模型前馈勾选随布局持久化（2026-11-10：重启后位置模式不再静默失效）",
    '            "cl_model_on": self.cl_model_check.isChecked(),',
], "scope: 保存模型前馈勾选")

insert_after(lines, 'self.cl_pitch_check.setChecked(bool(data["cl_pitch_on"]))', [
    '            if data.get("cl_model_on") and self.wrist_calib is not None:',
    "                self.cl_model_check.setChecked(True)",
], "scope: 恢复模型前馈勾选")

insert_after(lines, "self.exportFinished.connect(self._export_done)", [
    "        # 标定文件存在就随启动载入（否则「模型前馈」永远是灰的，每次重启都得手点）",
    "        self._load_wrist_calib(quiet=True)",
], "scope: 启动自动载入标定")

if not CHECK:
    SCOPE.write_text("".join(lines), encoding="utf-8", newline="")

# =====================================================================
# 二、wrist_control_law.py：分轴开关
# =====================================================================
replace_text(LAW,
             "def wrist_control_step_model(p: WristControlParams,\n"
             "                             calib: WristCalib,\n"
             "                             roll_deg: float,\n"
             "                             pitch_deg: float,\n"
             "                             roll_tgt_deg: float,\n"
             "                             pitch_tgt_deg: float) -> tuple:\n",
             "def wrist_control_step_model(p: WristControlParams,\n"
             "                             calib: WristCalib,\n"
             "                             roll_deg: float,\n"
             "                             pitch_deg: float,\n"
             "                             roll_tgt_deg: float,\n"
             "                             pitch_tgt_deg: float,\n"
             "                             roll_enabled: bool = True,\n"
             "                             pitch_enabled: bool = True) -> tuple:\n",
             "law: 分轴开关签名")

replace_text(LAW,
             "    out = [0] * MOTOR_COUNT\n"
             "    for i in range(MOTOR_COUNT):\n"
             "        dl = ((out_t.s_m[ROLL][i] + out_t.s_m[PITCH][i])\n"
             "              - (out_ref.s_m[ROLL][i] + out_ref.s_m[PITCH][i]))\n"
             "        ff = calib.k_counts_per_m[i] * dl\n"
             "        corr = (-p.kp * calib.k_counts_per_m[i]\n"
             "                * (out_fb.r_m[ROLL][i] * e_r_rad\n"
             "                   + out_fb.r_m[PITCH][i] * e_p_rad))\n",
             "    out = [0] * MOTOR_COUNT\n"
             "    for i in range(MOTOR_COUNT):\n"
             "        # 分轴开关（2026-11-10）：关掉的轴从「前馈 + 校正」里整体剔除。\n"
             "        # 旧实现只在 v1 把系数置零，模型路径照样用整张 R 和整段绳长，\n"
             "        # 勾掉 ROLL环/PITCH环 毫无作用。\n"
             "        dl = 0.0\n"
             "        if roll_enabled:\n"
             "            dl += out_t.s_m[ROLL][i] - out_ref.s_m[ROLL][i]\n"
             "        if pitch_enabled:\n"
             "            dl += out_t.s_m[PITCH][i] - out_ref.s_m[PITCH][i]\n"
             "        ff = calib.k_counts_per_m[i] * dl\n"
             "        corr = (-p.kp * calib.k_counts_per_m[i]\n"
             "                * ((out_fb.r_m[ROLL][i] * e_r_rad if roll_enabled else 0.0)\n"
             "                   + (out_fb.r_m[PITCH][i] * e_p_rad if pitch_enabled else 0.0)))\n",
             "law: 分轴开关生效")

# =====================================================================
# 三、测试同步
# =====================================================================
src = TEST_SINE.read_text(encoding="utf-8")
assert src.count("win._sweep_tick()") == 4, src.count("win._sweep_tick()")
if not CHECK:
    TEST_SINE.write_text(src.replace("win._sweep_tick()", "win._sweep_tick(0.05)"),
                         encoding="utf-8", newline="")
applied.append("test: 扫掠步长显式传 0.05")

replace_text(TEST_ROPE,
             '        win._tension_last = (time.monotonic(), [2, 2, 2])\n'
             '        win._cl_mode = "position"\n'
             "        win._start_closed_loop()\n",
             '        win._tension_last = (time.monotonic(), [2, 2, 2])\n'
             '        win._cl_mode = "position"\n'
             "        # 2026-11-10：位置模式必须带模型前馈才能启动（门禁新增），这里补齐\n"
             "        from wrist_control_law import WristCalib\n"
             "        win.wrist_calib = WristCalib([130380.0] * 3, [0.0, 0.0])\n"
             "        win.cl_model_check.setEnabled(True)\n"
             "        win.cl_model_check.setChecked(True)\n"
             "        win._start_closed_loop()\n",
             "test: 位置模式启动补齐前馈")

print(f"[{'CHECK' if CHECK else 'OK'}] {len(applied)} 处补丁：")
for a in applied:
    print("  -", a)
