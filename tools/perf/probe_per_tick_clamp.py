"""位置模式「每拍限幅」必须与力控三模式共用同一个 max_step_f。

用户要求（2026-11-03）：位置模式和力控是"一个限制"，不是各有一套、也不是不限。

· 力控：`_incr_step(..., max_step=max_step_f)` 每拍增量 ≤ max_step_f
· 位置：绝对目标经 `_clamp_per_tick()` 换算成 每拍变化 ≤ max_step_f
· 🛡 关闭时两者都不限（裸闭环）

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_per_tick_clamp.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mmhand_scope as M  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

rows: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  → {detail}" if detail else ""))


app = QApplication([])
M.load_layout_json = lambda: {}
win = M.ScopeWindow(default_port="COM_NONE")
win.safety_check.setChecked(True)
win.cl_edits["max_step_f"].setText("20")
win.targets = {27: 1000, 28: 1000, 29: 1000}

print("=== 1. 位置模式：目标跳 4000 counts，单拍只许走 max_step_f=20 ===")
outs = win._clamp_per_tick({27: 5000, 28: 5000, 29: 5000})
check("三台都被限到 +20", outs == {27: 1020, 28: 1020, 29: 1020}, f"{outs}")

print("=== 2. 负向同样限幅 ===")
outs = win._clamp_per_tick({27: -3000, 28: -3000, 29: -3000})
check("三台都被限到 −20", outs == {27: 980, 28: 980, 29: 980}, f"{outs}")

print("=== 3. 小位移原样放行（不制造抖动） ===")
outs = win._clamp_per_tick({27: 1005, 28: 1000, 29: 1010})
check("+5 原样、+0 被抑制、+10 原样",
      outs == {27: 1005, 29: 1010}, f"{outs}")

print("=== 4. 与力控同一个参数：改 max_step_f 两边一起变 ===")
win.cl_edits["max_step_f"].setText("100")
outs = win._clamp_per_tick({27: 5000, 28: 5000, 29: 5000})
check("max_step_f=100 → 每拍 100", outs == {27: 1100, 28: 1100, 29: 1100}, f"{outs}")
prm = win._force_params_v2(0.0, 0.0)
check("力控参数读到的是同一个值", prm is None or prm.max_step == 100.0,
      f"max_step={None if prm is None else prm.max_step}")

print("=== 5. 🛡 关闭 → 位置模式不再限速 ===")
win.safety_check.setChecked(False)
outs = win._clamp_per_tick({27: 5000, 28: 5000, 29: 5000})
check("安全关闭时原样下发", outs == {27: 5000, 28: 5000, 29: 5000}, f"{outs}")
win.safety_check.setChecked(True)

print("\n=== 汇总 ===")
fails = [r for r in rows if not r[1]]
print(f"{len(rows) - len(fails)}/{len(rows)} 通过")
sys.exit(1 if fails else 0)
