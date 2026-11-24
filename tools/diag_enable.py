"""诊断：连接后连续打印 servo_online 与使能门禁原因，再尝试使能并观察 5 s。

不使能成功也不会动电机（门禁/未起环）；只用于定位“在线掩码有值但门禁说离线”。
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
    print(f"[diag {time.monotonic() - T0:5.1f}s] {m}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()
st = {"ph": 0, "t": time.monotonic(), "n": 0}


def tick() -> None:
    now = time.monotonic()
    ph = st["ph"]
    if now - T0 > 40:
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
            log("connected")
            st["ph"] = 2
            st["t"] = now
    elif ph == 2:
        if now - st["t"] > 0.5:
            mask = w.status_info.get("servo_online", 0)
            try:
                reason, _ = w._enable_gate_check()
            except Exception as exc:
                reason = f"exc {exc!r}"
            log(f"mask=0x{mask:08X} gate={reason!r} state={w.status_info.get('state')} "
                f"scan={w.route_info.get('scan_state')}")
            st["n"] += 1
            st["t"] = now
            if st["n"] >= 4:
                log("call enable")
                w._on_enable_direct()
                st["ph"] = 3
                st["t"] = now
    elif ph == 3:
        if now - st["t"] > 0.5:
            log(f"armed={w.armed} mask=0x{w.status_info.get('servo_online', 0):08X} "
                f"state={w.status_info.get('state')} reject={w.status_info.get('direct_reject')}")
            st["t"] = now
            if now - T0 > 12:
                st["ph"] = 4
    elif ph == 4:
        w._disconnect()
        app.quit()


tm = QTimer()
tm.timeout.connect(tick)
tm.start(100)
app.exec()
