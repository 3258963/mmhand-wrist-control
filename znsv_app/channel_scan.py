"""通道体检：对变送器采样，判定八路里哪些真的接了传感器。

用法（仓库根目录）：
  .venv\\Scripts\\python znsv_app/channel_scan.py            # 扫描所有串口
  .venv\\Scripts\\python znsv_app/channel_scan.py COM5      # 指定串口
  .venv\\Scripts\\python znsv_app/channel_scan.py COM23 --watch --seconds 40
可选：--baud 115200 --address 1 --seconds 3

判据：恒 0 = 未接（无桥路噪声）；恒非零 = 静态有接；有波动 = 有信号；
|值|>2^30 = 异常（接线/供电问题）。注意模块开启动态跟踪时接了的通道也可能被锁在 0。
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serial.tools import list_ports

from znsv_app.znsv import ZnsvTransmitter


def sample(port, baud=115200, address=1, hz=20, seconds=3.0):
    sensor = ZnsvTransmitter(address=address, hz=hz)
    sensor.connect(port, baud)
    frames, error = [], sensor.error
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        raws = sensor.poll()
        if raws is not None:
            frames.append(raws)
    error = sensor.error
    sensor.disconnect()
    return frames, error


def verdict(values):
    lo, hi = min(values), max(values)
    mean = statistics.fmean(values)
    sigma = statistics.pstdev(values)
    if lo == 0 and hi == 0:
        return False, '恒 0 → 未接传感器'
    if abs(lo) > 2 ** 30 or abs(hi) > 2 ** 30:
        return True, f'异常值 {lo}..{hi} → 检查接线/供电'
    if hi == lo:
        return True, f'恒定 {lo} → 静态（疑似已接，无波动）'
    if hi - lo <= 3 and abs(mean) <= 3:
        return True, f'空载微噪 {lo}..{hi} → 已接传感器（空载）'
    return True, f'有信号 {lo}..{hi}（均值 {mean:.0f}，σ {sigma:.1f}）'


def report(port, frames):
    print(f'\n{port}: {len(frames)} 帧')
    live = 0
    for ch in range(8):
        values = [frame[ch] for frame in frames]
        has_data, text = verdict(values)
        live += has_data
        print(f'  CH{ch + 1}: {text}')
    print(f'结论：{live} / 8 通道有数据')
    return live


def try_port(port, baud, address, seconds):
    try:
        frames, error = sample(port, baud=baud, address=address, seconds=min(seconds, 1.5))
    except Exception as exc:
        print(f'{port}: 打开失败（{exc}）')
        return None
    if not frames:
        print(f'{port}: 无响应{"" if not error else f"（{error}）"}')
        return None
    if seconds > 1.5:  # 探测成功，补足完整时长
        more, _ = sample(port, baud=baud, address=address, seconds=seconds - 1.5)
        frames += more
    return frames


def watch(port, baud, address, seconds, hz=20):
    """每秒打印八路均值；通道发生明显变化（|均值变化|≥3 或秒内极差≥3）时打 *。"""
    sensor = ZnsvTransmitter(address=address, hz=hz)
    sensor.connect(port, baud)
    print(f'{port} 实时观察 {seconds:.0f} s：每秒一行，带 * 的通道正在变化', flush=True)
    window, prev_means, moved = [], None, set()
    end = time.monotonic() + seconds
    next_line = time.monotonic() + 1
    try:
        while time.monotonic() < end:
            raws = sensor.poll()
            if raws is not None:
                window.append(raws)
            if time.monotonic() >= next_line:
                next_line += 1
                if window:
                    means = [statistics.fmean(f[ch] for f in window) for ch in range(8)]
                    spreads = [max(f[ch] for f in window) - min(f[ch] for f in window)
                               for ch in range(8)]
                    flags = ''
                    for ch in range(8):
                        if prev_means is not None and (
                                abs(means[ch] - prev_means[ch]) >= 3 or spreads[ch] >= 3):
                            moved.add(ch)
                            flags += f' CH{ch + 1}*={means[ch]:+.0f}'
                    print(f'{time.strftime("%H:%M:%S")} ' +
                          ' '.join(f'{means[ch]:+.0f}' for ch in range(8)) + ' |' + flags,
                          flush=True)
                    prev_means, window = means, []
    finally:
        sensor.disconnect()
    print('期间变化的通道：' + ('、'.join(f'CH{ch + 1}' for ch in sorted(moved)) or '无'), flush=True)
    return moved


def main():
    parser = argparse.ArgumentParser(description='ZNSV6-F8-485 八通道体检')
    parser.add_argument('port', nargs='?', help='串口，缺省时扫描全部')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--address', type=int, default=1)
    parser.add_argument('--seconds', type=float, default=3.0)
    parser.add_argument('--watch', action='store_true', help='实时观察模式：每秒打印，标记变化通道')
    args = parser.parse_args()

    if args.watch:
        if not args.port:
            print('实时观察需要指定串口，例如：channel_scan.py COM23 --watch')
            return 1
        watch(args.port, args.baud, args.address, max(5.0, args.seconds))
        return 0

    ports = [args.port] if args.port else [p.device for p in list_ports.comports()]
    if not ports:
        print('没有检测到任何串口。')
        return 1
    found = 0
    for port in ports:
        frames = try_port(port, args.baud, args.address, args.seconds)
        if frames is None and args.address != 254:
            # 站地址可能被改过：单机总线可用广播再试一次
            frames = try_port(port, args.baud, 254, args.seconds)
        if frames:
            found += report(port, frames)
    if not found:
        print('\n未找到响应的变送器：确认供电与 485 A/B 接线，或用 --baud/--address 指定参数。')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
