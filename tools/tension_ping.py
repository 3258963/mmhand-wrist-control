"""张力变送器「到底谁在不在」扫描器 —— 专治 `变送器响应超时（收到 0/37 字节）`。

这个报错的意思是：上位机发了 Modbus-RTU 请求
    01 03 00 00 00 10 44 06          （8 字节：读 8 路重量）
指望回 37 字节
    01 03 20 [32 字节数据] [2 字节 CRC]
但在 timeout 内一个字节都没凑齐。

`收到 0/37` 说明**设备一个字都没发**，所以不是"慢"，是"没回"。
本脚本把可能的四类原因逐一扫一遍，看哪一种组合能把它叫醒：

    波特率   ×   从站地址   ×   RTS/DTR 方向电平

用法（仓库根目录，**先关掉上位机**）：

    .venv\\Scripts\\python.exe tools\\tension_ping.py COM23
    .venv\\Scripts\\python.exe tools\\tension_ping.py COM23 --addrs 1-8,254

判读：
    · 任一组合有回包 → 打印「✅ 命中」，把该波特率/地址/RTS 记下来，
      上位机按这个配置连（RTS 由驱动自动处理，一般不用管）；
    · 全部 0 字节 → **设备侧问题**（供电 / A-B 反向 / 拨码 / 硬件坏），
      与上位机软件无关。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from znsv_app.znsv import build_read  # noqa: E402


def _parse_addrs(text: str):
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [a for a in out if 1 <= a <= 254]


def ping(port_name: str, baud: int, addr: int, rts: bool, dtr: bool,
         tries: int = 2, wait_s: float = 0.08) -> bytes:
    """发一次读重量请求，返回收到的字节（可能为空）。"""
    import serial

    pkt = build_read(addr, 0x0000, 16)
    try:
        port = serial.Serial(port_name, baud, timeout=0.4, write_timeout=0.4)
    except Exception as exc:
        print(f"  !! 打不开 {port_name}@{baud}: {type(exc).__name__}: {exc}")
        return b""
    try:
        try:
            port.rts = rts
            port.dtr = dtr
        except Exception:
            pass
        for _ in range(tries):
            try:
                port.reset_input_buffer()
                port.write(pkt)
                time.sleep(wait_s)
                got = port.read(37)
                if got:
                    return got
            except Exception:
                pass
            time.sleep(0.05)
        return b""
    finally:
        try:
            port.rts = False
            port.dtr = False
        except Exception:
            pass
        port.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="张力变送器扫描器")
    ap.add_argument("port", nargs="?", default="COM23")
    ap.add_argument("--bauds", default="600000,115200,9600")
    ap.add_argument("--addrs", default="1,254",
                    help="从站地址，支持 1-8,254 这种写法")
    ap.add_argument("--only-rts-low", action="store_true",
                    help="只试 RTS=低、DTR=低（正常情况）")
    args = ap.parse_args(argv)

    bauds = [int(b) for b in args.bauds.split(",") if b.strip()]
    addrs = _parse_addrs(args.addrs)
    combos = [(False, False)] if args.only_rts_low else [
        (False, False), (True, False), (False, True), (True, True)]

    print(f"扫描 {args.port}：{len(bauds)} 个波特率 × {len(addrs)} 个地址 "
          f"× {len(combos)} 种方向电平 = {len(bauds)*len(addrs)*len(combos)} 次")
    hits = []
    for baud in bauds:
        for addr in addrs:
            for rts, dtr in combos:
                got = ping(args.port, baud, addr, rts, dtr)
                if got:
                    head = got[:10].hex()
                    print(f"  ✅ 命中 baud={baud} addr={addr} rts={rts} dtr={dtr}"
                          f"  收到 {len(got)} 字节  头 {head}")
                    hits.append((baud, addr, rts, dtr))
    if not hits:
        print("\n❌ 全部组合都是 0 字节 —— **设备侧问题**，与上位机软件无关。按顺序查：")
        print("   1) 变送器供电：量端子电压（与电机共用电源时，电机一动作就可能塌陷）")
        print("   2) RS485 A/B 是否接反 / 松动（反接不会烧，但完全无响应）")
        print("   3) 设备端红色拨码拨到 **8**（=115200）后**重新上电**")
        print("   4) 换一根 USB-485 线 / 换一个 USB 口（别走 Hub）")
        print("   5) 以上都排除 → 变送器硬件故障")
        return 2

    print("\n结论：设备是活的，用命中的那组配置即可。")
    if len(hits) > 1:
        print("（多个组合都命中，正常现象：地址 254 是广播；RTS 电平在自动方向上无影响）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
