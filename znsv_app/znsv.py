"""ZNSV6-F8-485 八通道变送器的 Modbus-RTU 驱动；单线程非阻塞轮询。

协议来源：《ZNSV6-F8-485 八通道数字称重变送器使用说明书》。
FC03 读保持寄存器、FC06 写单寄存器；重量 32 位有符号、低字在低地址（CDAB 字序）。
读重量帧布局与旧张力协议一致，CRC 为同一份 Modbus 实现（znsv_app.crc16）。
温度寄存器说明书只给范围 0~1800、减 550；按 0.1 °C 解释（-55.0~125.0 °C）。
写命令只封装零点校准/去皮；恢复出厂（0x0026←9）会清除校准，驱动不提供。

2026-10-28 自最简控制器搭建工程 desktop/znsv.py 原样搬运（仅改 crc16 导入）。
"""
import collections
import math
import operator
import time

from znsv_app.crc16 import crc16

# 寄存器地址（内部地址，PLC 地址 = 内部 + 40001）
WEIGHT_START = 0x0000   # 8 路 × 2 寄存器，32 位有符号
INFO_START = 0x001B     # 温度 / 模块地址 / 波特率代码 / 通讯速率，共 4 寄存器
CMD_ALL_TARE = 0x0026   # 写 1 = 全部去皮归零
CHANNEL_CMD_BASE = 0x0028  # 每路 10 个寄存器，首寄存器写 1=零点校准 2=去皮

# 说明书 3.4/7 节的波特率代码表（1~15）
BAUD_BY_CODE = {1: 2400, 2: 4800, 3: 9600, 4: 19200, 5: 28800, 6: 38400,
                7: 57600, 8: 115200, 9: 128000, 10: 230400, 11: 256000,
                12: 460800, 13: 500000, 14: 512000, 15: 600000}

WEIGHT_FRAME_LEN = 37  # 地址+功能码+字节数+32 数据+CRC
INFO_FRAME_LEN = 13    # 地址+功能码+字节数+8 数据+CRC
WRITE_ECHO_LEN = 8     # FC06 响应为请求原样回显


def _check_address(address):
    address = operator.index(address)
    if not 1 <= address <= 254:
        raise ValueError('从站地址必须为 1..254（254 为广播，总线只能有这一台）')
    return address


def build_read(address, start, count):
    payload = bytes((_check_address(address), 3)) + start.to_bytes(2, 'big') + count.to_bytes(2, 'big')
    return payload + crc16(payload).to_bytes(2, 'little')


def build_write(address, reg, value):
    payload = (bytes((_check_address(address), 6)) + operator.index(reg).to_bytes(2, 'big')
               + operator.index(value).to_bytes(2, 'big'))
    return payload + crc16(payload).to_bytes(2, 'little')


def channel_command_reg(channel, command):
    """channel 为 1..8；command 1=零点校准 2=去皮。"""
    if channel not in range(1, 9):
        raise ValueError('通道必须为 1..8')
    if command not in (1, 2):
        raise ValueError('单路命令只支持 1=零点校准 2=去皮')
    return CHANNEL_CMD_BASE + 10 * (channel - 1), command


def _check_response(frame, address, function, byte_count):
    if len(frame) < 5 or crc16(frame[:-2]) != int.from_bytes(frame[-2:], 'little'):
        raise ValueError('变送器响应不完整或 CRC 错误')
    if frame[0] != address:
        raise ValueError('变送器响应从站不匹配')
    if frame[1] == function | 0x80:
        raise ValueError(f'变送器 Modbus 异常 {frame[2]}')
    if frame[1] != function or len(frame) != byte_count or frame[2] != byte_count - 5:
        raise ValueError('变送器功能码、长度或字节数错误')


def parse_weights(frame, address):
    """返回 8 个有符号 int32；四字节 CDAB：高字为地址+1 的寄存器。"""
    _check_response(frame, address, 3, WEIGHT_FRAME_LEN)
    values = []
    for i in range(8):
        b = frame[3 + 4*i:7 + 4*i]
        value = (int.from_bytes(b[2:], 'big') << 16) | int.from_bytes(b[:2], 'big')
        values.append(value - (1 << 32) if value & 0x80000000 else value)
    return tuple(values)


def parse_info(frame, address):
    """返回 (温度原始值, 模块地址, 波特率代码, 通讯速率)。"""
    _check_response(frame, address, 3, INFO_FRAME_LEN)
    regs = [int.from_bytes(frame[3 + 2*i:5 + 2*i], 'big') for i in range(4)]
    return tuple(regs)


def temperature_c(temp_raw):
    """范围 0~1800，减 550 后按 0.1 °C 解释。"""
    return (temp_raw - 550) / 10


class ZnsvTransmitter:
    """一次 weight 请求返回 8 通道新样本；信息读与写命令插在重量帧间隙发送。"""

    def __init__(self, address=1, hz=20, info_period_s=2.0, serial_factory=None, clock=time.perf_counter):
        # clock 用 perf_counter：Windows 的 time.monotonic 是 GetTickCount64，15.6ms 粒度，
        # 会把 >64Hz 的轮询节奏全部量化到 15.6ms（2026-10-31 提速实验实测）。
        address = _check_address(address)
        if not math.isfinite(hz) or hz <= 0:
            raise ValueError('轮询频率必须有限且为正')
        self.address, self.period = address, 1/hz
        self.info_period = float(info_period_s)
        self.request_weights = build_read(address, WEIGHT_START, 16)
        self.request_info = build_read(address, INFO_START, 4)
        self._clock = clock
        self._factory, self._port = serial_factory, None
        # 超时随**波特率**自适应（2026-11-25）。
        # 一帧事务 = 8B 请求 + 37B 回复 = 45B × 10 bit：
        #   600000 → 0.75 ms ； 9600 → **46.9 ms**
        # 现场 `0x001D` 若还是出厂 9600（波特率代码 3），固定 60 ms 超时只有
        # 1.3 倍余量 → 稍一抖动就超时；固定 30 ms 更是必超。
        # 这里按 `2×(TX+RX) + 20 ms` 给，9600 → 114 ms，600000 → 30 ms（下限）。
        self.timeout_s = 0.06
        self._recalc_timeout(600000)
        self._gap_s = 0.001     # 一次收发结束后的总线间隔（600000 波特率下 45B 事务仅 ~0.8ms，1ms 远大于 3.5 字符静默要求）
        self._writes = collections.deque(maxlen=64)
        self._clear()

    def _clear(self):
        if hasattr(self, '_writes'):
            self._writes.clear()  # 断开丢弃未发送的写命令，不发到新连接
        self.raw = None
        self.received_at = None
        self.info = None        # (temp_raw, address, baud_code, sample_rate)
        self.info_at = None
        self.sequence = 0
        self.timeouts = 0
        self.protocol_errors = 0
        self.last_write = None  # (label, 状态文本, 时间)
        self.error = ''
        self._buffer = bytearray()
        self._phase = None      # None | 'weights' | 'info' | ('write', packet, label)
        self._expected = 0
        self._deadline = None
        self._next_weights = 0.0
        self._next_info = 0.0
        self._next_send_at = 0.0
        self._tx_started = 0.0

    def _recalc_timeout(self, baud: int) -> float:
        """按波特率算合理超时（见 `__init__` 注释）。"""
        try:
            baud = int(baud)
        except (TypeError, ValueError):
            baud = 9600
        if baud <= 0:
            baud = 9600
        per_byte_s = 10.0 / baud
        frame_s = (8 + WEIGHT_FRAME_LEN) * per_byte_s      # 请求 + 回复
        self.timeout_s = max(0.03, 2.0 * frame_s + 0.02)
        return self.timeout_s

    def connect(self, port, baudrate=115200):
        self.disconnect()
        if self._factory is None:
            from serial import Serial
            self._factory = Serial
        self._port = self._factory(port=port, baudrate=baudrate, timeout=0, write_timeout=0.1)
        try:
            # 打开时先放掉方向线（继承上一次状态会把总线占住）
            self._port.rts = False
            self._port.dtr = False
        except Exception:
            pass
        # write_timeout 20 → 100 ms（2026-11-25）：电机一动，USB 调度延迟
        # 轻松超过 20 ms，写超时会抛 SerialTimeoutException —— 旧代码把它当
        # "串口异常" 直接退出轮询线程 → 张力永久断流 → 力控冻结（现场"卡死"）。
        # 8 字节在 600000 下只需 0.13 ms，100 ms 只是容忍调度抖动，不影响时序。
        # 超时按真实波特率重算（9600 → 114 ms，600000 → 30 ms）
        self._recalc_timeout(baudrate)
        self._dirty = True     # 新连接先冲一次缓冲

    @property
    def connected(self):
        port = self._port
        return port is not None and port.is_open

    def disconnect(self):
        port, self._port = self._port, None
        # 2026-11-25：关端口前把 RTS/DTR 拉低（释放 485 方向线）。
        # 现象：上位机断开后变送器"对所有程序都不回话"，要断电重启才恢复 ——
        # 典型的适配器方向线被 last-open 状态卡在"发送"，把整条总线占住。
        if port is not None:
            try:
                port.rts = False
                port.dtr = False
            except Exception:
                pass
        self._clear()  # 新连接不能复用旧样本、零碎缓冲与写队列状态
        if port is not None:
            port.close()

    @property
    def temp_c(self):
        info = self.info
        return None if info is None else temperature_c(info[0])

    def submit_write(self, reg, value, label):
        """写命令排队，在两次重量读之间发送；不与读请求同帧竞争总线。"""
        packet = build_write(self.address, reg, value)
        if len(self._writes) >= self._writes.maxlen:
            raise ValueError('写命令队列已满，请等待完成后再操作')
        self._writes.append((packet, label))

    def submit_channel_command(self, channel, command, label):
        reg, value = channel_command_reg(channel, command)
        self.submit_write(reg, value, label)

    def submit_all_tare(self):
        self.submit_write(CMD_ALL_TARE, 1, '全部去皮归零')

    def next_poll_delay(self):
        """距离下一次必须调用 poll() 还有多少秒（0=立刻）。

        供上层按需排程：传输中返回 0（尽快读字节），空闲时返回距离下一个
        请求时隙的时间。这样 250Hz 采样不需要 1ms 硬轮询——空闲期不再空转，
        采样率与轮询间隔解耦（2ms 间隔会因完成检测量化掉到 167Hz）。
        """
        if not self.connected:
            return 0.02
        now = self._clock()
        if self._phase is not None:
            return 0.0
        request_due = now if self._writes else min(self._next_weights, self._next_info)
        due = max(request_due, self._next_send_at)
        return max(0.0, due - now)

    def poll(self):
        """收到一份新的 8 通道样本才返回 8 元组；其余情况返回 None。"""
        if not self.connected:
            return None
        now = self._clock()
        try:
            if self._phase is None:
                if now < self._next_send_at:
                    return None
                if self._writes:
                    packet, label = self._writes.popleft()
                    self._begin(packet, ('write', packet, label))
                elif now >= self._next_weights:
                    self._begin(self.request_weights, ('weights',))
                elif now >= self._next_info:
                    self._begin(self.request_info, ('info',))
                else:
                    return None
                return None
            waiting = self._port.in_waiting
            if waiting:
                self._buffer.extend(self._port.read(min(waiting, self._expected - len(self._buffer))))
            if len(self._buffer) >= 2 and self._buffer[1] & 0x80:
                self._expected = 5  # 异常响应只有 5 字节
            if len(self._buffer) < self._expected:
                if now < self._deadline:
                    return None
                self.error = f'变送器响应超时（收到 {len(self._buffer)}/{self._expected} 字节）'
                self.timeouts += 1
                self._dirty = True          # 缓冲里可能有半帧 → 下一轮先冲干净
                self._end()
                return None
            frame, phase = bytes(self._buffer), self._phase
            self._end()
            try:
                if phase[0] == 'weights':
                    raw = parse_weights(frame, self.address)
                elif phase[0] == 'info':
                    self.info, self.info_at = parse_info(frame, self.address), now
                    return None
                else:
                    if frame != phase[1]:
                        raise ValueError('写响应与请求回显不一致')
                    self.last_write = (phase[2], '已确认', now)
                    return None
            except ValueError as exc:
                self._dirty = True  # 错位帧可能在串口缓冲区留有尾字节
                self.error, self.protocol_errors = str(exc), self.protocol_errors + 1
                if phase[0] == 'write':
                    self.last_write = (phase[2], f'失败：{exc}', now)
                return None
            self.raw, self.received_at, self.sequence = raw, now, self.sequence + 1
            self.error = ''
            return raw
        except Exception as exc:
            try:
                self.disconnect()
            finally:
                self.error = str(exc)
            raise

    def _begin(self, packet, phase):
        self._tx_started = self._clock()  # 轮询节奏锚定请求起点：周期不被响应耗时拉长
        # 2026-11-25：**不再每轮都 reset_input_buffer()**。
        # 那是一次主动"扔缓冲"：FTDI 默认 latency 16 ms，37 字节回复可能还在
        # 芯片缓冲里，下一轮的 reset 直接把它冲掉 → 丢帧 → 白等一个 timeout。
        # 只在上一轮**不干净**（超时/错帧/写失败）时才清，正常路径不清。
        if getattr(self, "_dirty", True):
            self._port.reset_input_buffer()
            self._dirty = False
        if self._port.write(packet) != len(packet):
            raise IOError('变送器请求未完整写入')
        self._buffer.clear()
        self._phase = phase
        self._expected = {'write': WRITE_ECHO_LEN, 'weights': WEIGHT_FRAME_LEN,
                          'info': INFO_FRAME_LEN}[phase[0]]
        self._deadline = self._clock() + self.timeout_s

    def _end(self):
        now = self._clock()
        kind = self._phase[0]
        if kind == 'weights':
            self._next_weights = self._tx_started + self.period  # 不突发追赶漏掉的轮询
            self._next_info = min(self._next_info, now + self.info_period)
        elif kind == 'info':
            self._next_info = now + self.info_period
        else:
            self._next_info = min(self._next_info, now + 0.2)  # 写命令后尽快补读
        self._phase, self._deadline = None, None
        self._next_send_at = now + self._gap_s
