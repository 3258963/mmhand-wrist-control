"""阻抗模式重力补偿测试：K/D/τff 可配，跑 SEC 秒并每 0.5 s 打印位姿。

env: K (N·m/rad) D TFF_R TFF_P (N·m@90°) TAU_MAX SEC MMHAND_PORT
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
K = os.environ.get("K", "1.0")
D = os.environ.get("D", "0.0")
TFF_R = os.environ.get("TFF_R", "0.0")
TFF_P = os.environ.get("TFF_P", "0.0")
TAU_MAX = os.environ.get("TAU_MAX", "1.0")
TGT_R = os.environ.get("TGT_R", "0.0")
TGT_P = os.environ.get("TGT_P", "0.0")
SEC = float(os.environ.get("SEC", "12"))
T0 = time.monotonic()


def log(m: str) -> None:
    print(f"[imp {time.monotonic() - T0:6.1f}s] {m}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()

for key, val in (("k_roll", K), ("k_pitch", K), ("d_roll", D), ("d_pitch", D),
                 ("tau_ff_r", TFF_R), ("tau_ff_p", TFF_P),
                 ("tau_r_max", TAU_MAX), ("tau_p_max", TAU_MAX),
                 ("deadband", "0.3")):
    if key in w.cl_edits:
        w.cl_edits[key].setText(val)
    else:
        log(f"WARN: no UI field {key}")
w.cl_edits["roll_tgt"].setText(TGT_R)
w.cl_edits["pitch_tgt"].setText(TGT_P)

st = {"ph": 0, "t": time.monotonic(), "n": 0, "done": False}


def abort(reason: str) -> None:
    log(f"ABORT: {reason}")
    try:
        if w.cl_enabled:
            w._stop_closed_loop("重力测试中止", popup=False)
    except Exception:
        pass
    try:
        w._disconnect()
    except Exception:
        pass
    st["done"] = True
    QTimer.singleShot(300, app.quit)


def gate_ok() -> bool:
    try:
        return w._enable_gate_check()[0] is None
    except Exception:
        return False


def tick() -> None:
    if st["done"]:
        return
    now = time.monotonic()
    ph = st["ph"]
    if now - T0 > SEC + 40:
        abort("总超时")
        return
    if ph == 0:
        log(f"connect {PORT}")
        w.port_combo.setCurrentText(PORT)
        w._connect()
        st["ph"] = 1
        st["t"] = now
    elif ph == 1:
        if w.connected and gate_ok():
            # 切到阻抗模式（切模式会先停环）
            idx = w.cl_mode_combo.findData("impedance")
            if idx < 0:
                abort("找不到阻抗模式")
                return
            w.cl_mode_combo.setCurrentIndex(idx)
            log(f"mode=impedance  K={K} D={D} tau_ff={TFF_R}/{TFF_P} tau_max={TAU_MAX}")
            w._on_enable_direct()
            st["ph"] = 2
            st["t"] = now
        elif w.connected and now - st["t"] > 8:
            abort(f"门禁不过：{w._enable_gate_check()[0]}")
        elif not w.connected and now - st["t"] > 15:
            abort("连接超时")
    elif ph == 2:
        if w.armed:
            log("armed; start impedance loop")
            w._start_closed_loop()
            st["ph"] = 3
            st["t"] = now
            st["run0"] = now
        elif now - st["t"] > 10:
            abort("使能超时")
    elif ph == 3:
        el = now - st.get("run0", now)
        if now - st["t"] > 1.0:
            pose = w._wrist_pose_now()
            if pose is not None and st["n"] % 2 == 0:
                log(f"t={el:5.1f}s  roll={pose[0]:+7.2f}  pitch={pose[1]:+7.2f}")
            st["n"] += 1
            st["t"] = now
        if el > SEC:
            log("done; stop")
            try:
                w._stop_closed_loop("重力测试结束", popup=False)
            except Exception:
                pass
            st["ph"] = 4
    elif ph == 4:
        w._disconnect()
        st["done"] = True
        QTimer.singleShot(300, app.quit)


tm = QTimer()
tm.timeout.connect(tick)
tm.start(100)
app.exec()
log("exit")
