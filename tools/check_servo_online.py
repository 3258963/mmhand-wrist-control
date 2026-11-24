"""只连接 + 发 RESET（0xCE），读 P4 的 servo_online 掩码；不使能、不动电机。

用途：确认舵机离线是不是 P4 锁存/未复位导致；RESET 只清 E-STOP、断扭，不会运动。
"""
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
    print(f"[reset {time.monotonic() - T0:5.1f}s] {m}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()

st = {"ph": 0, "t": time.monotonic()}


def tick() -> None:
    now = time.monotonic()
    ph = st["ph"]
    if now - T0 > 40:
        log("timeout -> quit")
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
            log(f"connected; online mask before = 0x{w.status_info.get('servo_online', 0):02X}")
            w._on_reset()
            log("RESET sent")
            st["ph"] = 2
            st["t"] = now
        elif now - st["t"] > 15:
            log("connect timeout")
            app.quit()
    elif ph == 2:
        if now - st["t"] > 3:
            log(f"online mask after  = 0x{w.status_info.get('servo_online', 0):02X}"
                f"  state={w.status_info.get('state')}  scan={w.route_info.get('scan_state')}")
            st["ph"] = 3
    elif ph == 3:
        if now - st["t"] > 1:
            log("disconnect / quit")
            w._disconnect()
            app.quit()


tm = QTimer()
tm.timeout.connect(tick)
tm.start(100)
app.exec()
