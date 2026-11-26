"""一键自动调参：拉起上位机 → 连张力串口 → 使能 → 自动调参 N 轮 → 退出。

用法（在 `code/mmhand-main` 下）：

    # 只看能不能连上（不使能、不动电机）
    .venv\\Scripts\\python tools\\auto_run.py --dry-run

    # 真跑：连 COM13(电机) + COM23(张力)，自动调参 3 轮（约 6 分钟）
    .venv\\Scripts\\python tools\\auto_run.py --rounds 3

    # 换端口 / 限制总时长
    .venv\\Scripts\\python tools\\auto_run.py --motor-port COM13 \\
        --tension-port COM23 --rounds 3 --max-minutes 15

做的是什么（复用上位机自己的槽，不另写控制逻辑）：
    1. `ScopeWindow(port=...)` 自动连电机总线；
    2. 设张力串口 + 波特率 → `_toggle_tension_port()`；
    3. 切「张力控制」模式、勾「自动调参」、填轮数；
    4. `_on_enable_direct()` 使能（**这一步开始电机带电**）；
    5. `_toggle_closed_loop()` 起环 → 每轮 110 s，程序自己改增益再跑；
    6. 结束后停环、存布局、断开、退出。

安全：
    · 任何异常都会先 `_stop_closed_loop()` 再退出；
    · 有总时长看门狗（默认 15 分钟）；
    · `--dry-run` 到第 3 步就停，**不使能、不起环**；
    · 上位机的过载/传感器异常/病态位姿闸门全部照常生效。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def _pump(app, seconds: float) -> None:
    """跑 Qt 事件循环 seconds 秒（GUI 线程在这里推进）。"""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _wait(app, cond, timeout_s: float, label: str) -> bool:
    """等条件成立；返回是否成功。"""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    print(f"  ✗ 等待超时：{label}（{timeout_s:g}s）")
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="上位机自动调参一键脚本")
    ap.add_argument("--motor-port", default="COM13", help="P4/电机总线的串口")
    ap.add_argument("--tension-port", default="COM23", help="ZNSV 张力变送器串口")
    ap.add_argument("--tension-baud", default="600000", help="张力串口波特率")
    ap.add_argument("--rounds", type=int, default=3, help="自动调参轮数 1~6")
    ap.add_argument("--max-minutes", type=float, default=15.0, help="总时长看门狗")
    ap.add_argument("--dry-run", action="store_true",
                    help="只连电机/张力并检查，不使能、不起环")
    args = ap.parse_args(argv)

    os.environ.setdefault("QT_QPA_PLATFORM", "")
    from PySide6.QtWidgets import QApplication

    import mmhand_scope as ms

    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = None
    rc = 0
    try:
        print(f"[1/6] 启动上位机，电机口 {args.motor_port}")
        win = ms.ScopeWindow(default_port=args.motor_port)
        win.show()
        # ⚠ 直接构造 ScopeWindow **不会**自动连电机：自动连接是 `main()` 里的
        # `QTimer.singleShot(300, win._connect)`，这里必须自己调一次。
        _pump(app, 0.35)
        win._connect()
        if not _wait(app, lambda: win.connected, 25.0, "电机总线连接"):
            print("  → 电机总线没连上，退出")
            return 2
        print("  ✓ 电机总线已连接")

        print(f"[2/6] 连接张力变送器 {args.tension_port} @ {args.tension_baud}")
        # 串口/波特两个下拉框是**观测台 RTensionWindow 建窗口时**挂到 scope 上的；
        # 没打开过观测台时它们不存在。这里塞两个只实现 `currentText()` 的替身，
        # `_toggle_tension_port()` 需要的就这两个方法。
        if getattr(win, "tension_port_combo", None) is None:
            class _Txt:
                def __init__(self, t):
                    self._t = t

                def currentText(self):
                    return self._t

            win.tension_port_combo = _Txt(args.tension_port)
            win.tension_baud_combo = _Txt(str(args.tension_baud))
        else:
            win.tension_port_combo.setCurrentText(args.tension_port)
            win.tension_baud_combo.setCurrentText(str(args.tension_baud))
        win._toggle_tension_port()
        ok = _wait(app, lambda: win._tension_last is not None
                   and (time.monotonic() - win._tension_last[0]) < 0.5,
                   20.0, "张力数据")
        if not ok:
            try:
                st = win.tension_status.text()
            except AttributeError:
                st = "(无 status 控件)"
            print(f"  → 张力没数据。上位机状态：{st}")
            print(f"    sensor={'已建' if getattr(win, '_tension_sensor', None) else '无'}"
                  f"  轮询线程={'在跑' if getattr(win, '_tension_poll', None) else '无'}")
            return 3
        f = win._tension_last[1]
        print(f"  ✓ 张力已到：f=[{f[0]:.2f}, {f[1]:.2f}, {f[2]:.2f}] N")

        print("[3/6] 设模式/自动调参/轮数")
        win.cl_mode_combo.setCurrentIndex(1)          # 张力控制
        win._on_cl_mode_changed()
        win.cl_auto_tune_check.setChecked(True)
        win.cl_edits["auto_rounds"].setText(str(max(1, min(6, args.rounds))))
        _pump(app, 0.4)
        print(f"  ✓ 模式=张力，自动调参=开，轮数={win.cl_edits['auto_rounds'].text()}"
              f"，单轮 {ms.wrist_autotune.total_seconds():g}s")

        if args.dry_run:
            print("[dry-run] 到此为止：不使能、不起环")
            return 0

        print("[4/6] 使能（电机开始带电）")
        if not win.armed:
            win._on_enable_direct()
            if not _wait(app, lambda: win.armed, 30.0, "使能完成"):
                print("  → 使能失败，退出")
                return 4
        print("  ✓ 已使能")

        print("[5/6] 起环 → 自动调参")
        win._toggle_closed_loop()
        if not _wait(app, lambda: win.cl_enabled, 10.0, "闭环启动"):
            print("  → 闭环没起来，退出")
            return 5
        print(f"  ✓ 已起环，等它跑完（最多 {args.max_minutes:g} 分钟）")

        t_end = time.monotonic() + args.max_minutes * 60.0
        while time.monotonic() < t_end:
            app.processEvents()
            if not win.cl_enabled:
                break
            time.sleep(0.05)
        else:
            print("  ⚠ 到总时长上限 → 主动停环")
        print("[6/6] 收尾")
        if win.cl_enabled:
            win._stop_closed_loop("自动脚本：总时长到")
            _pump(app, 1.0)
        print("  ✓ 已停环（数据在 run_data/sine/）")
        return 0
    except Exception as exc:                      # 任何异常都要先停环
        print(f"!! 异常：{exc!r}")
        rc = 9
        try:
            if win is not None and win.cl_enabled:
                win._stop_closed_loop("自动脚本：异常")
                _pump(app, 0.5)
        except Exception:
            pass
        import traceback
        traceback.print_exc()
        return rc
    finally:
        try:
            if win is not None:
                if win.cl_enabled:
                    win._stop_closed_loop("自动脚本：退出")
                win._save_layout()
                _pump(app, 0.2)
                win.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
