"""混合控制（C1 张力 + 双轴角度）自动测试：连张力串口、使能、起环、保持+阶跃，采位姿与 C1。

env: C1N (目标 N) POSKP POSFF POSSTEP C1KP C1STEP AMP
"""
from __future__ import annotations

import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import mmhand_scope as M

PORT = os.environ.get("MMHAND_PORT", "COM13")
TPORT = os.environ.get("MMHAND_TPORT", "COM23")
TBAUD = os.environ.get("MMHAND_TBAUD", "600000")
C1N = os.environ.get("C1N", "2.0")
POSKP = os.environ.get("POSKP", "0.40")
POSFF = os.environ.get("POSFF", "0.50")
POSSTEP = os.environ.get("POSSTEP", "60")
C1KP = os.environ.get("C1KP", "5")
C1KI = os.environ.get("C1KI", "0")
C1FF = os.environ.get("C1FF", "0")
C1STEP = os.environ.get("C1STEP", "20")
C1ILIM = os.environ.get("C1ILIM", "5")
AMP = float(os.environ.get("AMP", "8"))
T0 = time.monotonic()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "run_data", "scope_exports", "mixed_test.csv")


def log(m: str) -> None:
    print(f"[mix {time.monotonic() - T0:6.1f}s] {m}", flush=True)


app = QApplication(sys.argv)
w = M.ScopeWindow(default_port=PORT)
w.show()
rt = M.RTensionWindow(w)   # 建出张力串口/波特率控件
rt.show()

# 混合模式参数
ed = w._c1_position_edits
for k, v in (("c1_pos_target", C1N), ("c1_pos_max_n", "8"), ("c1_pos_min_n", "0.2"),
             ("pos_kp", POSKP), ("pos_ki", "0"), ("pos_kd", "0"), ("pos_ff", POSFF),
             ("pos_step", POSSTEP), ("pos_deadband", "0.3"), ("pos_limit", "12"),
             ("c1_pos_kp", C1KP), ("c1_pos_ki", C1KI), ("c1_pos_kd", "0"),
             ("c1_pos_ff", C1FF), ("c1_pos_step", C1STEP),
             ("c1_pos_travel", "3000"), ("c1_pos_i_limit", C1ILIM)):
    ed[k].setText(v)
ed["roll_tgt"].setText("")
ed["pitch_tgt"].setText("")

st = {"ph": 0, "t": time.monotonic(), "rows": [], "done": False}


def abort(reason: str) -> None:
    log(f"ABORT: {reason}")
    try:
        if w.cl_enabled:
            w._stop_closed_loop("混合测试中止", popup=False)
    except Exception:
        pass
    try:
        w._tension_disconnect()
    except Exception:
        pass
    try:
        w._disconnect()
    except Exception:
        pass
    st["done"] = True
    QTimer.singleShot(300, app.quit)


def fresh_tension(sec: float = 0.5) -> float | None:
    last = getattr(w, "_tension_last", None)
    if last is None:
        return None
    if time.monotonic() - last[0] > sec:
        return None
    f1 = last[1][0]
    return f1 if f1 == f1 else None


def tick() -> None:
    if st["done"]:
        return
    now = time.monotonic()
    ph = st["ph"]
    if now - T0 > 240:
        abort("总超时")
        return
    if ph == 0:
        log(f"connect tension {TPORT}@{TBAUD}")
        try:
            w.tension_port_combo.setCurrentText(TPORT)
            w.tension_baud_combo.setCurrentText(TBAUD)
            w._toggle_tension_port()
        except Exception as exc:
            abort(f"tension connect exc {exc!r}")
        st["ph"] = 1
        st["t"] = now
    elif ph == 1:
        f1 = fresh_tension()
        if f1 is not None:
            log(f"tension ok f1={f1:+.2f} N; connect P4")
            w.port_combo.setCurrentText(PORT)
            w._connect()
            st["ph"] = 2
            st["t"] = now
        elif now - st["t"] > 12:
            abort("张力无数据（检查 COM23/波特率/供电）")
    elif ph == 2:
        if w.connected:
            log("P4 connected; select c1_position; RESET first")
            idx = w.cl_mode_combo.findData("c1_position")
            if idx < 0:
                abort("no c1_position mode")
                return
            w.cl_mode_combo.setCurrentIndex(idx)
            w._on_reset()
            st["ph"] = 21
            st["t"] = now
        elif now - st["t"] > 15:
            abort("P4 connect timeout")
    elif ph == 21:
        if now - st["t"] > 2.5:
            log("enable after reset")
            w._on_enable_direct()
            st["ph"] = 3
            st["t"] = now
    elif ph == 3:
        if w.armed:
            log("armed; start mixed loop")
            w._start_closed_loop()
            st["ph"] = 4
            st["t"] = now
            st["h0"] = now
        elif now - st["t"] > 3:
            if st.get("retry", 0) < 6:
                st["retry"] = st.get("retry", 0) + 1
                log(f"retry enable #{st['retry']}")
                w._on_enable_direct()
                st["t"] = now
            else:
                abort("使能超时")
    elif ph == 4:
        # 保持 10 s
        if now - st["t"] > 10:
            log(f"step +{AMP}/{AMP}")
            ed["roll_tgt"].setText(f"{AMP:+.1f}")
            ed["pitch_tgt"].setText(f"{AMP:+.1f}")
            st["ph"] = 5
            st["t"] = now
    elif ph == 5:
        if now - st["t"] > 8:
            log(f"step -{AMP}/{AMP}")
            ed["roll_tgt"].setText(f"{-AMP:+.1f}")
            ed["pitch_tgt"].setText(f"{-AMP:+.1f}")
            st["ph"] = 6
            st["t"] = now
    elif ph == 6:
        if now - st["t"] > 8:
            log("back to 0")
            ed["roll_tgt"].setText("0")
            ed["pitch_tgt"].setText("0")
            st["ph"] = 7
            st["t"] = now
    elif ph == 7:
        if now - st["t"] > 8:
            log("stop / save")
            try:
                w._stop_closed_loop("混合测试结束", popup=False)
            except Exception:
                pass
            st["ph"] = 8
            st["t"] = now
    elif ph == 8:
        try:
            with open(OUT, "w", newline="", encoding="utf-8") as f:
                wr = csv.writer(f)
                wr.writerow(["t", "roll", "pitch", "f1_N", "m27", "m28", "m29"])
                wr.writerows(st["rows"])
            log(f"saved {OUT} ({len(st['rows'])} rows)")
        except Exception as exc:
            log(f"save failed {exc!r}")
        try:
            w._tension_disconnect()
        except Exception:
            pass
        try:
            w._disconnect()
        except Exception:
            pass
        st["done"] = True
        QTimer.singleShot(300, app.quit)

    # 采样（100ms 定时器，每 5 拍存一行 = 10 Hz）
    if ph >= 4 and w.cl_enabled:
        pose = w._wrist_pose_now()
        f1 = fresh_tension(0.5)
        if pose is not None and f1 is not None:
            st["rows"].append((round(now - T0, 2), round(pose[0], 3), round(pose[1], 3),
                               round(f1, 3),
                               int(w._motor_pos_now(27)), int(w._motor_pos_now(28)),
                               int(w._motor_pos_now(29))))


tm = QTimer()
tm.timeout.connect(tick)
tm.start(100)
app.exec()
log("exit")
