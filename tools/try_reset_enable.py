"""尝试 RESET 后再使能，打印 P4 状态；不启动闭环、不动电机。"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import mmhand_scope as M

PORT = os.environ.get("MMHAND_PORT", "COM13")
T0 = time.monotonic()


def log(m: str) -> None:
    print(f"[fix {time.monotonic() - T0:5.1f}s] {m}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()
st = {"ph": 0, "t": time.monotonic()}


def tick() -> None:
    now = time.monotonic()
    ph = st["ph"]
    if now - T0 > 45:
        log("timeout")
        w._disconnect()
        app.quit()
        return
    if ph == 0:
        w.port_combo.setCurrentText(PORT)
        w._connect()
        st["ph"] = 1
        st["t"] = now
    elif ph == 1:
        if w.connected:
            log(f"connected state={w.status_info.get('state')} "
                f"control={w.status_info.get('control_enabled')} "
                f"mode={w.status_info.get('control_mode')} reject={w.status_info.get('direct_reject')}")
            w._on_reset()
            log("RESET sent")
            st["ph"] = 2
            st["t"] = now
    elif ph == 2:
        if now - st["t"] > 2.5:
            log(f"after reset state={w.status_info.get('state')} "
                f"control={w.status_info.get('control_enabled')} faults={w.status_info.get('faults')}")
            w._on_enable_direct()
            log("enable requested")
            st["ph"] = 3
            st["t"] = now
    elif ph == 3:
        if w.armed:
            log(f"ARMED ok state={w.status_info.get('state')} mode={w.status_info.get('control_mode')}")
            st["ph"] = 4
            st["t"] = now
        elif now - st["t"] > 8:
            log(f"NOT armed state={w.status_info.get('state')} reject={w.status_info.get('direct_reject')} "
                f"faults={w.status_info.get('faults')} control={w.status_info.get('control_enabled')}")
            st["ph"] = 4
            st["t"] = now
    elif ph == 4:
        if now - st["t"] > 0.5:
            try:
                w._stop_closed_loop("复位测试结束", popup=False)
            except Exception:
                pass
            w._disconnect()
            app.quit()


tm = QTimer()
tm.timeout.connect(tick)
tm.start(100)
app.exec()
