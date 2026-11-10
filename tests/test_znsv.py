"""znsv_app/znsv.py 自检；黄金数据来自说明书第 6 章示例报文。

运行：.venv/Scripts/python tests/test_znsv.py（在仓库根目录）。
2026-10-28 自最简控制器搭建工程 tests/test_znsv.py 搬运（仅改导入路径）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from znsv_app.crc16 import crc16
from znsv_app.znsv import (ZnsvTransmitter, build_read, build_write, channel_command_reg,
                           parse_weights, temperature_c)

DOC_WRITE_ADDRESS = bytes.fromhex('01 06 00 1C 00 02 C9 CD')
DOC_READ_CH1 = bytes.fromhex('01 03 00 00 00 02 C4 0B')
DOC_CH1_ZERO = bytes.fromhex('01 06 00 28 00 01 C8 02')
DOC_CH1_TARE = bytes.fromhex('01 06 00 28 00 02 88 03')


class FakeClock:
    def __init__(self, step=0.001):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


class FakeSerial:
    """按请求生成响应；chunk 控制每次 read 交付的字节数以覆盖半帧路径。"""

    def __init__(self, responder, chunk=7):
        self.responder, self.chunk = responder, chunk
        self.is_open, self.in_waiting = True, 0
        self.tx, self._rx = [], bytearray()

    def write(self, packet):
        self.tx.append(bytes(packet))
        self._rx.extend(self.responder(bytes(packet)))
        self.in_waiting = len(self._rx)
        return len(packet)

    def read(self, n):
        take = self._rx[:max(1, min(n, self.chunk))]
        del self._rx[:len(take)]
        self.in_waiting = len(self._rx)
        return bytes(take)

    def reset_input_buffer(self):
        self._rx.clear()
        self.in_waiting = 0

    def close(self):
        self.is_open = False


def simulator(weights, info=(620, 1, 8, 40), fail_first=0):
    """返回 request→response 的设备模拟器；fail_first 表示前 N 个请求不回复。"""
    counter = [0]

    def respond(request):
        counter[0] += 1
        if counter[0] <= fail_first:
            return b''
        if request[1] == 3:
            start = int.from_bytes(request[2:4], 'big')
            count = int.from_bytes(request[4:6], 'big')
            if start == 0:
                regs = []
                for value in weights:
                    regs += [value & 0xFFFF, (value >> 16) & 0xFFFF]
            else:
                regs = list(info)
            regs = regs[:count]
            data = b''.join(reg.to_bytes(2, 'big') for reg in regs)
            payload = bytes((request[0], 3, len(data))) + data
            return payload + crc16(payload).to_bytes(2, 'little')
        return request  # FC06 回显
    return respond


def drive(sensor, rounds=4000):
    for _ in range(rounds):
        result = sensor.poll()
        if result is not None:
            return result
    raise AssertionError('未在限定轮数内收到重量帧')


def test_doc_examples():
    assert build_write(1, 0x001C, 2) == DOC_WRITE_ADDRESS
    assert build_read(1, 0, 2) == DOC_READ_CH1
    assert build_write(1, *channel_command_reg(1, 1)) == DOC_CH1_ZERO
    assert build_write(1, *channel_command_reg(1, 2)) == DOC_CH1_TARE
    assert channel_command_reg(2, 1) == (0x0032, 1)
    assert channel_command_reg(8, 2) == (0x006E, 2)
    for bad in (0, 255, 256):
        try:
            build_read(bad, 0, 1)
            raise AssertionError(f'地址 {bad} 应被拒绝')
        except ValueError:
            pass
    assert build_read(254, 0, 1)[0] == 254  # 广播地址允许
    print('doc examples ok')


def test_weights_and_info():
    weights = (184, 89674, -28, 0, -2147483648, 2147483647, 1, -1)
    sensor = ZnsvTransmitter(address=1, hz=20, serial_factory=lambda **kw: FakeSerial(simulator(weights)),
                             clock=FakeClock())
    sensor.connect('FAKE', 115200)
    assert drive(sensor) == weights
    assert sensor.sequence == 1 and sensor.error == ''
    for _ in range(200):  # 间隙里应发出信息读
        sensor.poll()
        if sensor.info is not None:
            break
    assert sensor.info == (620, 1, 8, 40), sensor.info
    assert abs(sensor.temp_c - 7.0) < 1e-9
    assert abs(temperature_c(0) - (-55.0)) < 1e-9 and abs(temperature_c(1800) - 125.0) < 1e-9
    print('weights/info ok')


def test_write_queue_and_echo():
    sensor = ZnsvTransmitter(address=1, hz=20, serial_factory=lambda **kw: FakeSerial(simulator((0,) * 8)),
                             clock=FakeClock())
    sensor.connect('FAKE', 115200)
    sensor.submit_channel_command(1, 1, 'CH1 零点校准')
    sensor.submit_all_tare()
    for _ in range(6000):
        sensor.poll()
        if DOC_CH1_ZERO in sensor._port.tx and build_write(1, 0x0026, 1) in sensor._port.tx:
            break
    port_tx = sensor._port.tx
    assert DOC_CH1_ZERO in port_tx, port_tx
    assert build_write(1, 0x0026, 1) in port_tx, port_tx
    assert sensor.last_write is not None
    print('write queue ok')


def test_timeout_recovery():
    sensor = ZnsvTransmitter(address=1, hz=50, serial_factory=lambda **kw: FakeSerial(simulator((5,) * 8, fail_first=1)),
                             clock=FakeClock())
    sensor.connect('FAKE', 115200)
    for _ in range(3000):
        sensor.poll()
        if sensor.timeouts >= 1:
            break
    assert sensor.timeouts == 1, sensor.timeouts
    assert drive(sensor) == (5,) * 8  # 超时后可恢复
    assert sensor.error == ''         # 新帧清除错误
    print('timeout recovery ok')


def test_exception_response():
    def responder(request):
        payload = bytes((1, 0x83, 0x02))
        return payload + crc16(payload).to_bytes(2, 'little')

    sensor = ZnsvTransmitter(address=1, serial_factory=lambda **kw: FakeSerial(responder), clock=FakeClock())
    sensor.connect('FAKE', 115200)
    for _ in range(600):
        sensor.poll()
    assert sensor.protocol_errors >= 1 and '异常' in sensor.error
    print('exception response ok')


def test_disconnect_clears_writes():
    sensor = ZnsvTransmitter(address=1, serial_factory=lambda **kw: FakeSerial(simulator((0,) * 8)),
                             clock=FakeClock())
    sensor.connect('FAKE', 115200)
    sensor.submit_all_tare()
    assert len(sensor._writes) == 1
    sensor.disconnect()
    assert len(sensor._writes) == 0 and not sensor.connected
    print('disconnect clears writes ok')


if __name__ == '__main__':
    test_doc_examples()
    test_weights_and_info()
    test_write_queue_and_echo()
    test_timeout_recovery()
    test_exception_response()
    test_disconnect_clears_writes()
    print('all znsv checks passed')
