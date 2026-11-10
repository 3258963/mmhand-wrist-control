"""针对「用户点窗口右上角 X 关掉观测台」这条路径的泄漏验证。

当前修复只写在 _toggle_rt_window / _toggle_watch_window 里，而 X 关闭走的是
Qt 默认 close()（= hide），既不经过 _toggle_*，也没有 closeEvent 兜底。
本脚本量化这条路径是否仍然每轮泄一个 60Hz 定时器。

用法： .venv\\Scripts\\python.exe tools\\perf\\probe_xclose.py
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
from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
win = M.ScopeWindow(default_port="COM_NONE")


def active_timers():
    return [t for t in win.findChildren(QTimer) if t.isActive()]


def rt_count():
    return len(win.findChildren(M.RTensionWindow))


def wt_count():
    return len(win.findChildren(M.ParameterWatchWindow))


print(f"初始：RT={rt_count()} Watch={wt_count()} 活动定时器={len(active_timers())}")

print("\n--- 路径 A：连点 3 次工具栏按钮（打开→关闭） ---")
for _ in range(3):
    win._toggle_rt_window()
    win._toggle_rt_window()
    app.processEvents()
print(f"存活 RT={rt_count()}  活动定时器={len(active_timers())}  "
      f"（引用越界实例={sum(1 for w in win.findChildren(M.RTensionWindow) if w._timer.isActive())}）")

print("\n--- 路径 B：打开后用 X 关掉（close），再来 3 轮 ---")
for i in range(3):
    win._toggle_rt_window()          # 打开
    win.rt_window.close()            # 用户点 X：Qt 只 hide，不经过 _toggle_*
    app.processEvents()
    hidden_running = [w for w in win.findChildren(M.RTensionWindow)
                      if not w.isVisible() and w._timer.isActive()]
    print(f"  第 {i + 1} 轮：存活 RT={rt_count()}  "
          f"隐藏但定时器仍在跑={len(hidden_running)}  活动定时器={len(active_timers())}")

print("\n--- 路径 C：参数窗同样用 X 关 3 轮 ---")
for i in range(3):
    win._toggle_watch_window()
    win.watch_window.close()
    app.processEvents()
print(f"  存活 Watch={wt_count()}  隐藏但仍在刷={sum(1 for w in win.findChildren(M.ParameterWatchWindow) if not w.isVisible() and w._timer.isActive())}"
      f"  活动定时器={len(active_timers())}")

# X 关掉后 self.rt_window 还是旧对象：再点按钮会 new 一个新的，旧的无人引用但父对象是主窗 → 永久存活
print(f"\n重新打开一次后：self.rt_window 是否指向可见窗 = "
      f"{win.rt_window is not None and win.rt_window.isVisible()}，"
      f"存活 RT={rt_count()}（旧窗已成孤儿但没销毁）")

# 泄漏代价：每个隐藏窗仍在 60Hz 刷新
hidden = [w for w in win.findChildren(M.RTensionWindow) if not w.isVisible() and w._timer.isActive()]
if hidden:
    w = hidden[0]
    t = time.perf_counter()
    for _ in range(20):
        w._refresh()
    per = (time.perf_counter() - t) / 20 * 1000
    print(f"\n隐藏观测台刷新一次 {per:.2f} ms；{len(hidden)} 个 × 60Hz ≈ "
          f"{per * len(hidden) * 60:.0f} ms/s 直接吃掉 GUI 线程")


def loop_hz(ms=1500):
    st = {"n": 0, "gap": 0.0, "last": time.perf_counter()}

    def tick():
        now = time.perf_counter()
        st["gap"] = max(st["gap"], (now - st["last"]) * 1000)
        st["last"] = now
        st["n"] += 1

    t = QTimer()
    t.setTimerType(Qt.PreciseTimer)
    t.timeout.connect(tick)
    t.start(16)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < ms / 1000:
        app.processEvents()
        time.sleep(0.001)
    t.stop()
    return st["n"] / (time.perf_counter() - t0), st["gap"]


hz, gap = loop_hz()
print(f"GUI 节拍（仍带着这些 X 关掉的窗口）：{hz:5.1f} Hz，最大卡顿 {gap:5.1f} ms")
for w in win.findChildren(M.RTensionWindow) + win.findChildren(M.ParameterWatchWindow):
    if hasattr(w, "_timer"):
        w._timer.stop()
hz2, gap2 = loop_hz()
print(f"GUI 节拍（全部停表后）              ：{hz2:5.1f} Hz，最大卡顿 {gap2:5.1f} ms")
