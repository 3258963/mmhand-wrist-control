"""自动跑位置环对称测试（P + 前馈，无 I/D），参数可用环境变量覆盖。

环境变量（都可选）：
  MMHAND_PORT  COM13
  KP KI KD KFF DEADBAND LIMIT MAXSTEP
  AMP_R AMP_P          阶跃/正弦的幅值（度）
  F1 F2                两档正弦频率（Hz）
  HOLD                 每段阶跃/正弦的时长（s）

动作：连接→使能→起环→静置 5s→阶跃 +A→−A→0→正弦 F1→F2→导出 diag→停环断开。
安全：limit 默认 8（负向机械端约 −12.5）；全程 180s 超时；失败自动停环。
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
KP = os.environ.get("KP", "0.2")
KI = os.environ.get("KI", "0")
KD = os.environ.get("KD", "0")
KFF = os.environ.get("KFF", "0.3")
DEADBAND = os.environ.get("DEADBAND", "0.2")
LIMIT = os.environ.get("LIMIT", "8")
MAXSTEP = os.environ.get("MAXSTEP", "20")
AMP_R = float(os.environ.get("AMP_R", "6"))
AMP_P = float(os.environ.get("AMP_P", "4"))
AXIS = int(os.environ.get("AXIS", "2"))      # 0=ROLL 1=PITCH 2=双轴正弦
F1 = float(os.environ.get("F1", "0.1"))
F2 = float(os.environ.get("F2", "0.2"))
HOLD = float(os.environ.get("HOLD", "8"))
TAG = os.environ.get("TAG", "")
T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[auto {time.monotonic() - T0:6.1f}s] {msg}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()

for key, val in (("kp", KP), ("ki", KI), ("kd", KD), ("k_ff", KFF),
                 ("deadband", DEADBAND), ("limit", LIMIT),
                 ("max_step_f", MAXSTEP)):
    w.cl_edits[key].setText(val)
w.cl_ff_check.setChecked(True)
w.cl_edits["roll_tgt"].setText("0")
w.cl_edits["pitch_tgt"].setText("0")

state = {"phase": 0, "t": time.monotonic(), "done": False, "retried": 0}


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
    state["done"] = True
    QTimer.singleShot(500, app.quit)


def gate_ok() -> bool:
    try:
        reason, _ = w._enable_gate_check()
    except Exception:
        return False
    return reason is None


def set_sweep(amp_r: float, amp_p: float, freq: float) -> None:
    w.sweep_axis.setCurrentIndex(AXIS)
    if AXIS in (0, 1):
        w.sweep_wave_combo.setCurrentIndex(1)   # 单轴必须显式选正弦
    w.sweep_center0.setChecked(True)
    w.sweep_amp.setValue(amp_r)
    w.sweep_amp_p.setValue(max(0.5, amp_p))
    w.sweep_freq.setValue(freq)
    w.cl_edits["roll_tgt"].setText("0")
    w.cl_edits["pitch_tgt"].setText("0")
    w.sweep_check.setChecked(True)


def step(sign: int) -> None:
    w.cl_edits["roll_tgt"].setText(f"{sign * AMP_R:+.1f}")
    w.cl_edits["pitch_tgt"].setText(f"{sign * AMP_P:+.1f}" if AMP_P else "0")


def tick() -> None:
    if state["done"]:
        return
    now = time.monotonic()
    ph = state["phase"]
    if now - T0 > 180:
        abort("总超时")
        return
    if ph == 0:
        log(f"connecting {PORT}")
        w.port_combo.setCurrentText(PORT)
        w._connect()
        state["phase"] = 1
        state["t"] = now
    elif ph == 1:
        if w.connected and gate_ok():
            log(f"connected; gate ok; enable  (params kp={KP} kff={KFF} maxstep={MAXSTEP} limit={LIMIT} amp={AMP_R}/{AMP_P})")
            w._on_enable_direct()
            state["phase"] = 2
            state["t"] = now
        elif w.connected and now - state["t"] > 8:
            abort(f"门禁不过：{w._enable_gate_check()[0]}")
        elif not w.connected and now - state["t"] > 15:
            abort("连接超时")
    elif ph == 2:
        if w.armed:
            log("armed; start closed loop")
            w._start_closed_loop()
            state["phase"] = 3
            state["t"] = now
        elif now - state["t"] > 2:
            if gate_ok() and state["retried"] < 1:
                state["retried"] = 1
                log("enable not confirmed; retry")
                w._on_enable_direct()
                state["t"] = now
            else:
                abort("使能超时")
    elif ph == 3:
        if now - state["t"] > 5:
            step(1)
            log(f"step +{AMP_R}/+{AMP_P}")
            state["phase"] = 4
            state["t"] = now
    elif ph == 4:
        if now - state["t"] > HOLD:
            step(-1)
            log(f"step -{AMP_R}/-{AMP_P}")
            state["phase"] = 5
            state["t"] = now
    elif ph == 5:
        if now - state["t"] > HOLD:
            step(0)
            log("back to 0")
            state["phase"] = 6
            state["t"] = now
    elif ph == 6:
        if now - state["t"] > HOLD:
            log(f"sine {F1} Hz")
            set_sweep(AMP_R, AMP_P, F1)
            state["phase"] = 7
            state["t"] = now
    elif ph == 7:
        if now - state["t"] > 20:
            log(f"sine {F2} Hz")
            set_sweep(AMP_R, AMP_P, F2)
            state["phase"] = 8
            state["t"] = now
    elif ph == 8:
        if now - state["t"] > 20:
            log("export diag")
            w.sweep_check.setChecked(False)
            try:
                w._export_diag_csv()
            except Exception as exc:
                log(f"export failed: {exc!r}")
            state["phase"] = 9
            state["t"] = now
    elif ph == 9:
        if now - state["t"] > 1:
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
            state["done"] = True
            QTimer.singleShot(500, app.quit)


timer = QTimer()
timer.timeout.connect(tick)
timer.start(100)
app.exec()
log("exit")
