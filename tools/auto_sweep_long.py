"""长时/大幅位置环自动测试（P + 前馈）。

env:
  KP KI KD KFF DEADBAND LIMIT MAXSTEP
  AMP_R AMP_P            阶跃与正弦幅值
  AXIS                   0=ROLL 1=PITCH 2=双轴
  STEP_SEC               每个阶跃保持时长
  FREQS                  逗号分隔的正弦频率列表，如 "0.05,0.1,0.2"
  SINE_SEC               每个频率时长
  MMHAND_PORT

流程：连接→使能→起环→静置5s→阶跃 +A→−A→0→逐频率正弦→导出→停环断开。
超时 600s；任何使能失败自动停环退出。
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
KP = os.environ.get("KP", "0.25")
KI = os.environ.get("KI", "0")
KD = os.environ.get("KD", "0")
KFF = os.environ.get("KFF", "0.35")
DEADBAND = os.environ.get("DEADBAND", "0.2")
LIMIT = os.environ.get("LIMIT", "12")
MAXSTEP = os.environ.get("MAXSTEP", "60")
MS_R = os.environ.get("MS_R", "0")
MS_P = os.environ.get("MS_P", "0")
AMP_R = float(os.environ.get("AMP_R", "10"))
AMP_P = float(os.environ.get("AMP_P", "8"))
AXIS = int(os.environ.get("AXIS", "2"))
STEP_SEC = float(os.environ.get("STEP_SEC", "10"))
SINE_SEC = float(os.environ.get("SINE_SEC", "45"))
FREQS = [float(x) for x in os.environ.get("FREQS", "0.05,0.1,0.2").split(",") if x.strip()]
T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[long {time.monotonic() - T0:7.1f}s] {msg}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()

for key, val in (("kp", KP), ("ki", KI), ("kd", KD), ("k_ff", KFF),
                 ("deadband", DEADBAND), ("limit", LIMIT),
                 ("max_step_f", MAXSTEP), ("max_step_r", MS_R), ("max_step_p", MS_P)):
    w.cl_edits[key].setText(val)
w.cl_ff_check.setChecked(True)
w.cl_edits["roll_tgt"].setText("0")
w.cl_edits["pitch_tgt"].setText("0")

st = {"ph": 0, "t": time.monotonic(), "fi": 0, "retried": 0, "done": False}


def abort(reason: str) -> None:
    log(f"ABORT: {reason}")
    try:
        w.sweep_check.setChecked(False)
    except Exception:
        pass
    try:
        if w.cl_enabled:
            w._stop_closed_loop("自动测试中止", popup=False)
    except Exception:
        pass
    try:
        w._disconnect()
    except Exception:
        pass
    st["done"] = True
    QTimer.singleShot(500, app.quit)


def gate_ok() -> bool:
    try:
        return w._enable_gate_check()[0] is None
    except Exception:
        return False


def set_target(roll: float, pitch: float) -> None:
    w.cl_edits["roll_tgt"].setText(f"{roll:+.1f}")
    w.cl_edits["pitch_tgt"].setText(f"{pitch:+.1f}")


def set_sweep(freq: float) -> None:
    w.sweep_axis.setCurrentIndex(AXIS)
    if AXIS in (0, 1):
        w.sweep_wave_combo.setCurrentIndex(1)
    w.sweep_center0.setChecked(True)
    w.sweep_amp.setValue(AMP_R)
    w.sweep_amp_p.setValue(max(0.5, AMP_P))
    w.sweep_freq.setValue(freq)
    set_target(0, 0)
    w.sweep_check.setChecked(True)


def tick() -> None:
    if st["done"]:
        return
    now = time.monotonic()
    ph = st["ph"]
    if now - T0 > 600:
        abort("总超时")
        return
    if ph == 0:
        log(f"connecting {PORT}")
        w.port_combo.setCurrentText(PORT)
        w._connect()
        st["ph"] = 1
        st["t"] = now
    elif ph == 1:
        if w.connected and gate_ok():
            log(f"enable  (kp={KP} kff={KFF} maxstep={MAXSTEP} limit={LIMIT} amp={AMP_R}/{AMP_P})")
            w._on_enable_direct()
            st["ph"] = 2
            st["t"] = now
        elif w.connected and now - st["t"] > 8:
            abort(f"门禁不过：{w._enable_gate_check()[0]}")
        elif not w.connected and now - st["t"] > 15:
            abort("连接超时")
    elif ph == 2:
        if w.armed:
            log("armed; start loop")
            w._start_closed_loop()
            st["ph"] = 3
            st["t"] = now
        elif now - st["t"] > 3:
            if st["retried"] < 6:
                st["retried"] += 1
                unk = w.status_info.get("multiturn_unknown", 0)
                log(f"retry enable #{st['retried']} (multiturn_unknown=0x{unk:X})")
                w._on_enable_direct()
                st["t"] = now
            else:
                abort("使能超时（多圈未就绪/门禁弹窗）")
    elif ph == 3:                            # settle
        if now - st["t"] > 5:
            set_target(AMP_R, AMP_P)
            log(f"step +{AMP_R}/+{AMP_P}")
            st["ph"] = 4
            st["t"] = now
    elif ph == 4:
        if now - st["t"] > STEP_SEC:
            set_target(-AMP_R, -AMP_P)
            log(f"step -{AMP_R}/-{AMP_P}")
            st["ph"] = 5
            st["t"] = now
    elif ph == 5:
        if now - st["t"] > STEP_SEC:
            set_target(0, 0)
            log("back to 0")
            st["ph"] = 6
            st["t"] = now
    elif ph == 6:
        if now - st["t"] > STEP_SEC:
            if st["fi"] >= len(FREQS):
                log("all sine done; export")
                w.sweep_check.setChecked(False)
                try:
                    w._export_diag_csv()
                except Exception as exc:
                    log(f"export failed: {exc!r}")
                st["ph"] = 9
                st["t"] = now
            else:
                f = FREQS[st["fi"]]
                log(f"sine {f} Hz for {SINE_SEC}s")
                set_sweep(f)
                st["ph"] = 7
                st["t"] = now
    elif ph == 7:
        if now - st["t"] > SINE_SEC:
            st["fi"] += 1
            st["ph"] = 6
            st["t"] = now
    elif ph == 9:
        if now - st["t"] > 1:
            log("stop loop / disconnect / quit")
            try:
                if w.cl_enabled:
                    w._stop_closed_loop("自动测试结束", popup=False)
            except Exception:
                pass
            try:
                w._disconnect()
            except Exception:
                pass
            st["done"] = True
            QTimer.singleShot(500, app.quit)


tm = QTimer()
tm.timeout.connect(tick)
tm.start(100)
app.exec()
log("exit")
