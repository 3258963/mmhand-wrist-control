"""一键张紧/松绳 相关行为断言（离屏，不连硬件）。

逐条验证可疑点，输出 PASS/FAIL：
  1. 守卫阈值是否依赖观测台窗口（关窗后是否放宽 fmax）
  2. 张紧模式是否忽略 t_min（一键紧绳会夹，两处不一致）
  3. 一键紧绳「失败回滚」是否会漏停已启动的闭环
  4. 一键回零的状态行是否声称了并不存在的软限位钳制

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_tight_bugs.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


def arm_scene() -> None:
    win.connected = True
    win.armed = True
    win._tension_last = (time.monotonic(), [2.0, 2.0, 2.0])
    win._enc_filt_raw[16] = 0
    win._enc_filt_raw[17] = 0
    win.angle_baseline[16] = 0.0
    win.angle_baseline[17] = 0.0
    for m in M.SERVO_TARGETS:
        win.cable_enable_checks[m].setChecked(True)
    win.cl_edits["trim_sign"].setText("1,1,1")


# ---------------- 1. 守卫阈值 vs 观测台窗口 ----------------
print("\n=== 1. 守卫阈值是否随观测台关窗而放宽 ===")
arm_scene()
win._toggle_rt_window()
win.tension_fmin_edit.setText("1.0")
win.tension_fmax_edit.setText("8.0")
fmin_open, fmax_open, _ = win._effective_flimits()
check("窗口开着时守卫框生效", abs(fmax_open - 8.0) < 1e-9,
      f"fmin={fmin_open:g} fmax={fmax_open:g}")
win.rt_window.close()
app.processEvents()
fmin_closed, fmax_closed, _ = win._effective_flimits()
check("关窗后仍守住 fmax=8（不放松安全阈值）", abs(fmax_closed - 8.0) < 1e-9,
      f"关窗后 fmin={fmin_closed:g} fmax={fmax_closed:g} —— 用户设的 8N 变成 30N")

# ---------------- 2. 张紧模式忽略 t_min ----------------
print("\n=== 2. 张紧模式是否忽略 t_min（一键紧绳却会夹）===")
win._toggle_rt_window()
win.tension_fmin_edit.setText("")
win.tension_fmax_edit.setText("")
win.cl_edits["f_min"].setText("0")
win.cl_edits["fmax_f"].setText("30")
win.cl_edits["t_min"].setText("10")
win.cl_edits["t_max"].setText("20")
win.cl_edits["t_tgt"].setText("3")
p = win._tight_params(0.0, 0.0)
if p is None:
    check("张紧参数可构造", False,
          f"_tight_params 返回 None，状态行={win.ctrl_status.text()!r}")
else:
    # UI tooltip 明确 t_min 是"低于则⚠预紧丢失"，只告警；一键紧绳才硬夹。
    warn = win._t_bound_note()
    check("张紧模式符合设计：t_min 只告警不夹目标",
          abs(p.t_target - 3.0) < 1e-9 and "预紧丢失" in warn,
          f"t_target={p.t_target:g}，告警={warn!r}")

t_use, reason = M.tighten_t_use(3.0, 10.0, 20.0, 0.0, 30.0)
check("一键紧绳按设计硬夹 t_min=10（与连续模式不同）",
      t_use is not None and t_use >= 10.0,
      f"tighten_t_use → t_use={t_use} {reason or ''}")

# ---------------- 3. 一键紧绳回滚是否漏停闭环 ----------------
print("\n=== 3. 一键紧绳失败回滚时是否停掉已启动的闭环 ===")
win.cl_edits["t_tgt"].setText("5")
win.cl_edits["t_min"].setText("0")
win.cl_edits["t_max"].setText("0")
win.cl_edits["f_min"].setText("0")
win.cl_mode_combo.blockSignals(True)
win.cl_mode_combo.setCurrentIndex(0)
win.cl_mode_combo.blockSignals(False)
win._cl_mode = "position"
win.cl_enabled = False

called = {"n": 0}
real_start = win._start_closed_loop


def fake_start_then_raise():
    called["n"] += 1
    win.cl_enabled = True          # 模拟闭环已真正启动
    win._cl_timer.start(10)
    raise RuntimeError("模拟：启动成功后 UI 侧异常")


win._start_closed_loop = fake_start_then_raise
try:
    win._on_tighten_rope()
finally:
    win._start_closed_loop = real_start

status = win.ctrl_status.text()
leaking = win.cl_enabled
timer_running = win._cl_timer.isActive()
win.cl_enabled = False
win._cl_timer.stop()
check("事务真的进到了启动步骤", called["n"] == 1,
      f"状态行={status!r}" if called["n"] != 1 else "")
check("回滚后闭环必须已停止", not leaking,
      f"cl_enabled={leaking}，_cl_timer 仍在跑={timer_running}" if leaking else "")

# ---------------- 4. 一键回零是否真做软限位钳制 ----------------
print("\n=== 4. 一键回零是否真做软限位钳制 ===")
sent = []
win._send_motor_target = lambda motor, tgt: sent.append((motor, int(tgt)))
win._motor_origin = {27: 0, 28: 0, 29: 0}
for m in M.SERVO_TARGETS:
    win.cable_enable_checks[m].setChecked(True)
win._do_goto_zero({"motors": {"27": 5_000_000}, "saved_at": "test"})
note = win.ctrl_status.text()
m27 = [t for m, t in sent if m == 27]
check("回零目标被钳到软限位内", bool(m27) and abs(m27[0]) <= M.MOTOR_SOFT_LIMIT,
      f"M27 实际下发 {m27[0] if m27 else 'N/A'}，软限位 ±{M.MOTOR_SOFT_LIMIT}")
check("状态行的『超软限位已钳制』提示会触发", "钳制" in note,
      f"实际状态行={note!r}（clamped 列表从没被填过 → 这段提示是死代码）")

# ---------------- 汇总 ----------------
print("\n=== 汇总 ===")
fails = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"  {'✅' if ok else '❌'} {name}")
print(f"\n{len(results) - len(fails)}/{len(results)} 通过")
sys.exit(1 if fails else 0)


