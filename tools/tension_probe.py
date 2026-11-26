"""ZNSV 张力变送器 **裸串口测速**（脱离上位机 GUI）。

目的：分辨「张力数据只有 ~15 Hz」到底是
  (A) 上位机 GUI 线程拖慢（张力轮询跑在 GUI 事件循环里）
  (B) 硬件/驱动/波特率本身就只能这么快

用法（仓库根目录）：
    .venv\\Scripts\\python.exe tools\\tension_probe.py                # 默认 COM23 @600000，6 秒
    .venv\\Scripts\\python.exe tools\\tension_probe.py COM23 600000 10
    .venv\\Scripts\\python.exe tools\\tension_probe.py COM23 115200

输出：
  · 帧数 / 实测帧率 / 帧间隔分布（中位、p95、最大）
  · 超时次数、协议错误次数
  · 8 路 raw 的 min/max/均值（哪几路真的接了传感器）
  · 结论：是「GUI 拖慢」还是「硬件上限」

⚠ COM23 同一时刻只能被一个程序打开。若上位机/ZNSV Studio 正在连，
   会报「拒绝访问」——先把它们断开。
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from znsv_app.znsv import ZnsvTransmitter  # noqa: E402


def probe(port: str, baud: int, seconds: float, address: int = 1) -> int:
    sensor = ZnsvTransmitter(address=address, hz=250.0)
    try:
        sensor.connect(port, baud)
    except Exception as exc:                      # 端口占用 / 不存在
        print(f"[×] 打开 {port} @{baud} 失败：{exc}")
        print("    最常见原因：上位机或 ZNSV Studio 正占用该串口。先把它们断开再试。")
        return 2

    print(f"[i] 已连接 {port} @{baud}, 从站 {address}, 目标 250 Hz, 采样 {seconds:g} s ...")
    stamps = []
    raws = []
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        sample = sensor.poll()
        if sample is not None:
            stamps.append(time.perf_counter())
            raws.append(sample)
        else:
            # 按驱动自己的排程睡，避免空转烧 CPU
            d = sensor.next_poll_delay()
            if d > 0:
                time.sleep(min(d, 0.002))

    timeouts, perr, seq = sensor.timeouts, sensor.protocol_errors, sensor.sequence
    error = sensor.error
    sensor.disconnect()

    n = len(stamps)
    print()
    print(f"[=] 收到 {n} 帧，驱动累计 sequence={seq}，超时 {timeouts}，错帧 {perr}")
    if error:
        print(f"    最后一条错误：{error}")
    if n < 2:
        print("[×] 没收到有效帧 —— 检查供电、485 A/B 接线、波特率、从站地址。")
        return 3

    span = stamps[-1] - stamps[0]
    rate = (n - 1) / span if span > 0 else 0.0
    gaps = [(stamps[i + 1] - stamps[i]) * 1000.0 for i in range(n - 1)]
    gaps_sorted = sorted(gaps)
    p95 = gaps_sorted[min(len(gaps_sorted) - 1, int(0.95 * len(gaps_sorted)))]
    print()
    print(f"[=] 实测帧率 = {rate:.1f} Hz   （标称 250 Hz，达成 {100*rate/250:.0f}%）")
    print(f"[=] 帧间隔: 中位 {statistics.median(gaps):.1f} ms  "
          f"p95 {p95:.1f} ms  最大 {max(gaps):.1f} ms  最小 {min(gaps):.1f} ms")
    print(f"[=] 单帧理论耗时（37B 请求 + 37B 响应 = 74B @ {baud}）："
          f"{74*10/baud*1000:.2f} ms  → 该带宽的理论上限 ≈ {baud/(74*10):.0f} Hz")

    print()
    print("[=] 8 路 raw（1 raw = 1 g；受拉为负 → 张力 N = raw x -0.00980665）")
    print("      CH    最小     最大     均值   峰峰   判定")
    live = 0
    for ch in range(8):
        vals = [r[ch] for r in raws]
        lo, hi = min(vals), max(vals)
        mean = statistics.fmean(vals)
        pp = hi - lo
        if lo == 0 and hi == 0:
            verdict = "恒 0 → 未接"
        elif pp >= 3:
            verdict = "有信号 ✓"
            live += 1
        elif abs(mean) > 3:
            verdict = "有偏置（已接，静止）"
            live += 1
        else:
            verdict = "空载微噪（已接）"
            live += 1
        print(f"      CH{ch+1:<2d} {lo:8d} {hi:8d} {mean:8.1f} {pp:6d}   {verdict}")
    print(f"      → {live}/8 路有数据")

    print()
    if rate >= 150:
        print("[结论] 裸串口能跑到 150 Hz 以上 → **上位机 GUI 拖慢**。"
              "把张力轮询搬出 GUI 线程即可。")
    elif rate >= 80:
        print(f"[结论] 裸串口约 {rate:.0f} Hz（未到 250）→ 检查 FTDI LatencyTimer 是否为 1，"
              f"波特率是否 600000。")
    else:
        print(f"[结论] 裸串口只有 {rate:.0f} Hz → **硬件/驱动上限**，不是 GUI 的锅。"
              "先查 LatencyTimer、波特率、以及变送器自身的采样/刷新设置。")
    return 0


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM23"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 600000
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
    return probe(port, baud, seconds)


if __name__ == "__main__":
    sys.exit(main())
