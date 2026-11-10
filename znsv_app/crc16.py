"""Modbus CRC16（多项式 0xA001 反射、初值 0xFFFF、低字节在前）。

原样来自最简控制器搭建工程 desktop/tension.py 的 crc16——znsv 协议帧
校验与其同族，搬运时一并带过来，未做任何改动。
2026-10-28 随 znsv.py 搬入 mmhand 工程。
"""


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF
