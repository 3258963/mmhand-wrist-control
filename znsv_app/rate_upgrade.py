"""张力链提速实验：通讯速率→1280Hz、波特率→600000，并实测可达数据率。

依据《ZNSV6-F8-485 八通道数字称重变送器使用说明书》：
  通讯速率寄存器 0x001E（R/W）可选 10/40/640/1280Hz，出厂默认 40Hz（§3.2、寄存器表、§6.4）；
  波特率寄存器 0x001D（R/W）代码 15=600000（§6.3、§5.7 拨码表）。
COM23 的 USB-485 是 FTDI FT232：VCP 驱动每次 open 按注册表 LatencyTimer（本机 16ms）
重置芯片延迟定时器，37 字节响应攒满 16ms 才上送 → 轮询上限 ≈60Hz。
因此写寄存器走 VCP，高速基准测试走 D2XX 直连（open 后再把延迟定时器压到 1ms，无人重置）。

用法（仓库根目录）：
  .venv\\Scripts\\python znsv_app/rate_upgrade.py COM23            # 全流程
  .venv\\Scripts\\python znsv_app/rate_upgrade.py COM23 --dry-run  # 只诊断不动寄存器
可选：--address 1 --baud 115200 --target-baud 600000 --comm-rate 1280 --seconds 3.0

失败兜底：设备端红色拨码拨到 8（=115200）重新上电即恢复通讯；
不要长按复位键（恢复出厂会清掉校准参数）。
"""
import argparse
import ctypes
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import serial
from serial import Serial

from znsv_app.znsv import (BAUD_BY_CODE, WEIGHT_FRAME_LEN, build_read,
                           build_write, crc16, parse_weights)

# 说明书 §6.1/6.3/6.4 的示例帧：先自检 CRC 与帧构造，不通过绝不碰硬件
_SELF_TESTS = (
    ('FC03 读重量（手册 6.1）', build_read(1, 0x0000, 2), '010300000002C40B'),
    ('FC06 写通讯速率=1280（手册 6.4）', build_write(1, 0x001E, 1280), '0106001E0500EA9C'),
    ('FC06 写波特率=500000（手册 6.3）', build_write(1, 0x001D, 13), '0106001D000DD809'),
)
_REG_INFO_START, _REG_INFO_COUNT = 0x001B, 4     # 温度/地址/波特率代码/通讯速率
_REG_CH1_PARAMS_START, _REG_CH1_PARAMS_COUNT = 0x002D, 5  # 滤波/蠕变/动态跟踪/中值/刷新频次


def _self_test():
    ok = True
    for label, frame, expect in _SELF_TESTS:
        good = frame == bytes.fromhex(expect)
        ok &= good
        print(f'  自检 {label}: {"通过" if good else f"不符，算出 {frame.hex(' ').upper()} 期望 {expect}"}')
    good = crc16(bytes.fromhex('01030400B80000')) == 0x167A  # 手册 6.1 响应示例
    ok &= good
    print(f'  自检 响应示例 CRC（手册 6.1）: {"通过" if good else "不符"}')
    return ok


class FtNode(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_ulong), ('type', ctypes.c_ulong),
                ('id', ctypes.c_ulong), ('locId', ctypes.c_ulong),
                ('serial', ctypes.c_char * 16), ('desc', ctypes.c_char * 64),
                ('handle', ctypes.c_void_p)]


def _d2xx_find(vid, pid):
    """返回 (dll, 设备序号)；ID 高字为 VID、低字为 PID。"""
    ft = ctypes.WinDLL('ftd2xx.dll')
    count = ctypes.c_ulong()
    if ft.FT_CreateDeviceInfoList(ctypes.byref(count)) != 0 or count.value == 0:
        raise RuntimeError('D2XX 找不到 FTDI 设备')
    nodes = (FtNode * count.value)()
    if ft.FT_GetDeviceInfoList(nodes, ctypes.byref(ctypes.c_ulong(count.value))) != 0:
        raise RuntimeError('D2XX 枚举失败')
    ids = ' '.join(f'{n.id:08X}' for n in nodes)
    for i, n in enumerate(nodes):
        if (n.id >> 16) == vid and (n.id & 0xFFFF) == pid:
            return ft, i
    raise RuntimeError(f'D2XX 列表里没有 {vid:04X}:{pid:04X}（发现 {ids}）')


def d2xx_set_latency(vid=0x0403, pid=0x6001, latency_ms=1):
    """端口关闭时把 FTDI 延迟定时器压到 1ms；VCP open 会重置回注册表值，仅供诊断对照。"""
    try:
        ft, index = _d2xx_find(vid, pid)
    except RuntimeError as exc:
        return None, str(exc)
    handle = ctypes.c_void_p()
    if ft.FT_Open(index, ctypes.byref(handle)) != 0:
        return None, 'D2XX 打开失败（VCP 端口未关干净？）'
    try:
        value = ctypes.c_ubyte(latency_ms)
        if ft.FT_SetLatencyTimer(handle, value) != 0:
            value = ctypes.c_ubyte(2)
            if ft.FT_SetLatencyTimer(handle, value) != 0:
                return None, 'FT_SetLatencyTimer 失败'
        got = ctypes.c_ubyte()
        ft.FT_GetLatencyTimer(handle, ctypes.byref(got))
        return got.value, None
    finally:
        ft.FT_Close(handle)


class D2xxLink:
    """FTDI D2XX 直连收发；开完口再设 1ms 延迟定时器，不被 VCP open 重置。"""

    def __init__(self, vid=0x0403, pid=0x6001, baud=600000, latency_ms=1):
        ft, index = _d2xx_find(vid, pid)
        self.ft = ft
        self.handle = ctypes.c_void_p()
        if ft.FT_Open(index, ctypes.byref(self.handle)) != 0:
            raise RuntimeError('D2XX 打开失败（VCP 端口未关干净？）')
        checks = (ft.FT_SetBaudRate(self.handle, baud),
                  ft.FT_SetDataCharacteristics(self.handle, 8, 0, 0),
                  ft.FT_SetFlowControl(self.handle, 0, 0, 0),
                  ft.FT_SetTimeouts(self.handle, 10, 100),
                  ft.FT_SetLatencyTimer(self.handle, latency_ms))
        if any(checks):
            self.close()
            raise RuntimeError(f'D2XX 配置失败（{checks}）')
        got = ctypes.c_ubyte()
        ft.FT_GetLatencyTimer(self.handle, ctypes.byref(got))
        self.latency = got.value
        self._txbuf = ctypes.create_string_buffer(64)
        self._rxbuf = ctypes.create_string_buffer(64)
        self._n = ctypes.c_ulong()
        self.purge()

    def purge(self):
        self.ft.FT_Purge(self.handle, 3)  # RX|TX，丢弃上次超时的残留字节

    def write(self, data):
        self._txbuf.raw = bytes(data)
        n = ctypes.c_ulong()
        if self.ft.FT_Write(self.handle, self._txbuf, len(data), ctypes.byref(n)) != 0:
            raise IOError('D2XX 写失败')
        return n.value

    def read(self, size):
        n = ctypes.c_ulong()
        if self.ft.FT_Read(self.handle, self._rxbuf, size, ctypes.byref(n)) != 0:
            raise IOError('D2XX 读失败')
        return self._rxbuf.raw[:n.value]

    def close(self):
        if self.handle:
            self.ft.FT_Close(self.handle)
            self.handle = None


class Transactor:
    """一次请求一次响应的直连收发，transport 为 Serial 或 D2xxLink。"""

    def __init__(self, transport, address):
        self.transport, self.address = transport, address
        self.request_weights = build_read(address, 0x0000, 16)
        self._dirty = False  # 上次事务残留了半截响应时才需要 purge（purge 是 USB 控制传输，很贵）

    def _flush_before_write(self):
        t = self.transport
        if self._dirty:
            if hasattr(t, 'purge'):
                t.purge()
            elif t.in_waiting:
                t.reset_input_buffer()
            self._dirty = False

    def _recv(self, size):
        frame = b''
        while len(frame) < size:
            chunk = self.transport.read(size - len(frame))
            if not chunk:
                self._dirty = True
                break
            frame += chunk
        return frame

    def read_regs(self, start, count):
        self._flush_before_write()
        self.transport.write(build_read(self.address, start, count))
        frame = self._recv(5 + 2 * count)
        if len(frame) != 5 + 2 * count:
            raise TimeoutError(f'读寄存器响应不完整 {len(frame)}/{5 + 2 * count}')
        if crc16(frame[:-2]) != int.from_bytes(frame[-2:], 'little'):
            raise ValueError('读寄存器 CRC 错误')
        return [int.from_bytes(frame[3 + 2 * i:5 + 2 * i], 'big') for i in range(count)]

    def write_reg(self, reg, value, check_echo=True):
        self._flush_before_write()
        request = build_write(self.address, reg, value)
        self.transport.write(request)
        # 写掉电保持寄存器要等设备 flash 编程，回显可能 >50ms，放宽到 200ms
        t = self.transport
        old = getattr(t, 'timeout', None)
        if old is not None:
            t.timeout = 0.2
        else:
            t.ft.FT_SetTimeouts(t.handle, 200, 100)
        try:
            if not check_echo:
                self._recv(8)  # 波特率切换瞬间回显可能已按新速率发出，读不齐就丢弃
                return
            echo = self._recv(8)
            if echo != request:
                raise TimeoutError(f'写回显不符 {echo.hex()}')
        finally:
            if old is not None:
                t.timeout = old
            else:
                t.ft.FT_SetTimeouts(t.handle, 10, 100)

    def weight(self):
        self._flush_before_write()
        t0 = time.perf_counter()
        self.transport.write(self.request_weights)
        frame = self._recv(WEIGHT_FRAME_LEN)
        if len(frame) != WEIGHT_FRAME_LEN:
            raise TimeoutError(f'重量响应不完整 {len(frame)}/{WEIGHT_FRAME_LEN}')
        return parse_weights(frame, self.address), time.perf_counter() - t0


def open_port(port, baud):
    try:
        return Serial(port=port, baudrate=baud, timeout=0.05, write_timeout=0.1)
    except (serial.SerialException, OSError) as exc:
        raise SystemExit(f'打开 {port} 失败（{exc}）：COM23 被占用时先关闭观测台/ZNSV Studio')


def rtt_probe(tx, n=25):
    ts = []
    for _ in range(n):
        ts.append(tx.weight()[1])
    return min(ts), statistics.median(ts), max(ts)


def show_rtt(label, ts):
    lo, mid, hi = ts
    print(f'  {label}: 单次往返 min/中位/max = {lo * 1000:.2f} / {mid * 1000:.2f} / {hi * 1000:.2f} ms')


def bench_max(tx, seconds):
    """不限节奏的紧轮询：测总线+驱动极限。"""
    count = dups = errors = 0
    last = None
    t0 = time.perf_counter()
    end = t0 + seconds
    while time.perf_counter() < end:
        try:
            values = tx.weight()[0]
            count += 1
            dups += values == last
            last = values
        except TimeoutError:
            errors += 1
    elapsed = time.perf_counter() - t0
    return count / elapsed, count, dups, errors, elapsed


def bench_paced(tx, seconds, hz):
    """定速轮询：测目标频率能不能稳住，统计迟到与超时。"""
    period = 1e9 / hz
    ok = late = errors = 0
    next_t = time.perf_counter_ns()
    t0 = time.perf_counter()
    end = t0 + seconds
    while time.perf_counter() < end:
        next_t += period
        if time.perf_counter_ns() > next_t:
            late += 1
        else:
            while time.perf_counter_ns() < next_t:
                pass
        try:
            tx.weight()
            ok += 1
        except TimeoutError:
            errors += 1
    elapsed = time.perf_counter() - t0
    return ok / elapsed, ok, late, errors, elapsed


def show_bench(label, result, hz=None):
    rate, count, dups, errors, elapsed = result
    extra = f'（目标 {hz:.0f}Hz）' if hz else ''
    print(f'  {label}{extra}: 达成 {rate:.0f} Hz — {count} 帧/{elapsed:.1f}s，'
          f'超时 {errors}，与前帧相同 {dups}')


def main():
    parser = argparse.ArgumentParser(description='ZNSV6-F8-485 张力链提速实验')
    parser.add_argument('port')
    parser.add_argument('--address', type=int, default=1)
    parser.add_argument('--baud', type=int, default=115200, help='当前波特率（默认出厂 115200）')
    parser.add_argument('--target-baud', type=int, default=600000)
    parser.add_argument('--comm-rate', type=int, default=1280)
    parser.add_argument('--seconds', type=float, default=3.0)
    parser.add_argument('--dry-run', action='store_true', help='只诊断，不写任何寄存器')
    args = parser.parse_args()

    print('帧构造/CRC 自检（对照说明书示例）：')
    if not _self_test():
        return 1

    port, tx, found_baud = None, None, None
    print('\n探测变送器波特率…')
    for baud in dict.fromkeys([args.baud, *sorted(BAUD_BY_CODE.values(), reverse=True)]):
        p = open_port(args.port, baud)
        p.timeout = 0.25  # 探测期放宽：FTDI 攒包要 16ms 才上送
        try:
            time.sleep(0.05)
            tx = Transactor(p, args.address)
            tx.read_regs(_REG_INFO_START, _REG_INFO_COUNT)
            port, found_baud = p, baud
            break
        except Exception:
            p.close()
            time.sleep(0.1)
    if port is None:
        print('各波特率下都无响应：确认供电与 A/B 接线；红色拨码拨到 8 可强制 115200。')
        return 2
    if found_baud != args.baud:
        print(f'  设备当前波特率 = {found_baud}（掉电保持生效中，非默认 {args.baud}）')
    try:
        regs = tx.read_regs(_REG_INFO_START, _REG_INFO_COUNT)
        print(f'\n当前状态：波特率代码 {regs[2]}（={BAUD_BY_CODE.get(regs[2], "?")}）'
              f'  通讯速率 {regs[3]}Hz  温度原始值 {regs[0]}')
        params = tx.read_regs(_REG_CH1_PARAMS_START, _REG_CH1_PARAMS_COUNT)
        print(f'CH1 参数：滤波深度 {params[0]}  蠕变跟踪 {params[1]}  动态跟踪 {params[2]}'
              f'  中值滤波 {params[3]}  动态跟踪刷新频次 {params[4]}')

        show_rtt(f'{found_baud} 波特率（VCP）单次往返', rtt_probe(tx))

        if args.dry_run:
            print('\n--dry-run：到此为止，未写任何寄存器。')
            return 0

        # 1) 通讯速率 → 目标值
        if regs[3] != args.comm_rate:
            tx.write_reg(0x001E, args.comm_rate)
            back = tx.read_regs(0x001E, 1)[0]
            print(f'\n通讯速率 {regs[3]}→{args.comm_rate}Hz 已写入，读回确认 = {back}Hz'
                  + ('' if back == args.comm_rate else '  ← 与目标不符！'))

        # 2) 波特率 → 目标值；切换后旧连接作废，按新速率重连验证
        target_code = next((c for c, b in BAUD_BY_CODE.items() if b == args.target_baud), None)
        if target_code is None:
            print(f'目标波特率 {args.target_baud} 不在说明书代码表里')
            return 1
        if regs[2] != target_code:
            tx.write_reg(0x001D, target_code, check_echo=False)
            port.close()
            time.sleep(0.3)
            port = open_port(args.port, args.target_baud)
            tx = Transactor(port, args.address)
            for _ in range(3):
                try:
                    regs = tx.read_regs(_REG_INFO_START, _REG_INFO_COUNT)
                    break
                except Exception:
                    time.sleep(0.2)
            else:
                print(f'\n{args.target_baud} 波特率下变送器无响应。恢复办法：'
                      f'设备端红色拨码拨到 8（=115200）重新上电；切勿长按复位键（会清校准）。')
                return 2
            print(f'波特率已切到 {args.target_baud}，读回确认代码 = {regs[2]}'
                  f'（={BAUD_BY_CODE.get(regs[2], "?")}）')

        # 3) 高速基准测试：D2XX 直连（VCP open 会把延迟定时器重置回注册表的 16ms）
        show_rtt(f'{args.target_baud} 波特率（VCP）单次往返', rtt_probe(tx))
        link = None
        try:
            port.close()
            link = D2xxLink(baud=args.target_baud, latency_ms=1)
            print(f'基准测试走 D2XX 直连，延迟定时器 = {link.latency}ms')
            tx = Transactor(link, args.address)
        except Exception as exc:
            print(f'D2XX 不可用（{exc}），退回 VCP 测试（会被 16ms 延迟定时器压住）')
            if not port.is_open:
                port = open_port(args.port, args.target_baud)
                tx = Transactor(port, args.address)
        try:
            show_rtt(f'{args.target_baud} 波特率（D2XX@{tx.transport.__class__.__name__}）单次往返',
                     rtt_probe(tx))
            show_bench('极限轮询', bench_max(tx, args.seconds))
            show_bench('定速轮询', bench_paced(tx, args.seconds, 1000), hz=1000)
        finally:
            if link is not None:
                link.close()
        return 0
    finally:
        port.close()


if __name__ == '__main__':
    sys.exit(main())
