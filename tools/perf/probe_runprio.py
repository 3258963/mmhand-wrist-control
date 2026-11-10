"""验证「🔒运行优先」降档是否真的落到各 GUI 定时器。

修前：只有 _plot_tick 的 3:1 门生效，table_timer 恒 33ms、观测台恒 16ms。
修后：跑环 → 表格 66ms / 观测台 66ms / 主图 3:1；停环 → 33 / 50 / 全速。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_runprio.py
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

app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")


def show(tag):
    rt = win.rt_window._timer.interval() if win.rt_window is not None else None
    wt = win.watch_window._timer.interval() if win.watch_window is not None else None
    print(f"{tag:<28} 表格 {win.table_timer.interval():>3} ms | "
          f"主图 {win.plot_timer.interval():>3} ms | 观测台 {rt} | 参数窗 {wt} | "
          f"跑环={win.cl_enabled} 降档={win._run_prio()}")


show("初始（未跑环）")

win._toggle_rt_window()
win._toggle_watch_window()
show("打开两个窗（未跑环）")

# 模拟启动闭环：只翻状态位再调降档（真启动要先使能电机，离屏做不了）
win.cl_enabled = True
win._apply_run_prio()
show("跑环中")

# 跑环中开窗：应直接按 15Hz 档起
win.rt_window.close()
win._toggle_rt_window()
show("跑环中重开观测台")

# 停环
win.cl_enabled = False
win._apply_run_prio()
show("停环后")

# 取消勾选运行优先也要恢复全速（勾选状态改动即生效）
win.runprio_check.setChecked(False)
win.cl_enabled = True
win._apply_run_prio()
show("跑环但取消勾选")

# 主图 3:1 门计数
calls = {"n": 0}
_orig = win._update_plot
win._update_plot = lambda: (calls.__setitem__("n", calls["n"] + 1), _orig())[1]
win.runprio_check.setChecked(True)
win._apply_run_prio()
for _ in range(30):
    win._plot_dirty = True
    win._plot_tick()
print(f"\n跑环 30 拍实际重绘 {calls['n']} 帧 → 有效 {33 * calls['n'] / 30:.0f} FPS")
win._update_plot = _orig

# 关窗后引用是否清干净（消费点靠 None 守卫）
win.rt_window.close()
win.watch_window.close()
print(f"关窗后：rt_window={win.rt_window} watch_window={win.watch_window} "
      f"tension_btn={win.tension_btn} tension_status={win.tension_status}")
print(f"张力状态刷新容错：", end="")
win._tension_status_refresh()
print("OK（无 AttributeError）")
