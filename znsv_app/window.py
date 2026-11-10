"""ZNSV Studio 主窗口：侧栏导航、连接与采集中枢、CSV 与事件日志。

采集驱动复用 znsv_app/znsv.py；界面与其他上位机完全独立。
本地零位只记在电脑内存：显示、曲线、CSV 的"显示值"=（原始值 − 零位）/ 10^小数位，
原始值列始终为变送器绝对读数；不写传感器寄存器，重启应用后零位清除。

2026-10-28 自最简控制器搭建工程 desktop/znsv_app/window.py 原样搬运
（仅改包内导入 desktop.* → znsv_app.*）。
"""
import csv
import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as W

from znsv_app.znsv import ZnsvTransmitter
from znsv_app.pages import OpsPage, OverviewPage, SettingsPage, TrendsPage
from znsv_app.theme import BAD, GOOD, MUTED, WARN, QSS

SETTINGS_PATH = Path(__file__).resolve().parent / 'settings.json'

PILL_STYLES = {  # 状态圆点颜色
    'off': MUTED, 'wait': WARN, 'on': GOOD, 'stale': WARN, 'error': BAD,
}


class LiveData:
    """共享数据模型：时间戳与八通道显示值（已按小数位缩放）。"""

    def __init__(self, maxlen=9000):  # 50 Hz × 180 s 上限
        self.t = deque(maxlen=maxlen)
        self.ch = [deque(maxlen=maxlen) for _ in range(8)]
        self.last_raws = None
        self.active = [False] * 8  # 出现过非零样本即视为可能已接

    def push(self, now, raws, decimals, zero=None, factor=1.0):
        scale = 10 ** decimals
        self.t.append(now)
        for i, (series, raw) in enumerate(zip(self.ch, raws)):
            if raw != 0:
                self.active[i] = True  # 未接检测看原始值，与零位/换算无关
            offset = zero[i] if zero is not None else 0
            value = (raw - offset) / scale * factor
            series.append(0.0 if value == 0 else value)  # 归一化负零
        self.last_raws = tuple(raws)

    def clear(self):
        self.t.clear()
        for series in self.ch:
            series.clear()
        self.last_raws = None
        self.active = [False] * 8

    def suspected_missing(self, index, min_samples=40):
        """采样足够多仍恒 0 → 疑似未接；一旦出现非零即不再判缺。"""
        return not self.active[index] and len(self.t) >= min_samples

    def channel_minmax(self, index, window_s, now=None):
        """窗口内该通道 min/max；无数据返回 (0, 0)。t 与各通道同拍入队，下标对齐。"""
        now = time.monotonic() if now is None else now
        series = self.ch[index]
        lo = hi = None
        for i in range(len(series) - 1, -1, -1):
            if now - self.t[i] > window_s:
                break
            v = series[i]
            lo = v if lo is None else min(lo, v)
            hi = v if hi is None else max(hi, v)
        return (lo, hi) if lo is not None else (0, 0)


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ZNSV Studio — 八通道称重变送器上位机')
        self.resize(1280, 820)
        self.sensor = None
        self.port_name = None
        self.live = LiveData()
        self.frames = deque(maxlen=400)
        self.zero_raws = None  # 本地零位：None=未设；tuple=八路原始零点
        self.channel_enabled = [True] * 8  # 通道开关：卡片/曲线/表格共用一份状态
        self.csv_file, self.csv_writer, self.csv_rows = None, None, 0
        self._build_ui()
        self.auto_port = None
        self._want_auto_connect = False
        self._load_settings()
        if self._want_auto_connect and self.auto_port:
            # 等 300 ms 界面先显示；自动连接失败不弹窗，只记日志
            QtCore.QTimer.singleShot(300, lambda: self.connect_sensor(auto=True))
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(5)
        self.display_timer = QtCore.QTimer(self)
        self.display_timer.timeout.connect(self.refresh_views)
        self.display_timer.start(100)
        self.log('ZNSV Studio 就绪。先在总览页选择串口并连接。')

    # ---------- 界面骨架 ----------

    def _build_ui(self):
        shell = W.QFrame()
        shell.setObjectName('shell')
        layout = W.QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(shell)

        sidebar = W.QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(212)
        side = W.QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 16)
        side.setSpacing(6)
        brand = W.QLabel('ZNSV Studio')
        brand.setObjectName('brand')
        side.addWidget(brand)
        sub = W.QLabel('八通道称重变送器 · 485')
        sub.setObjectName('brandSub')
        side.addWidget(sub)
        side.addSpacing(14)

        self.stack = W.QStackedWidget()
        nav_labels = ('◉  总览', '∿  曲线', '☰  通道操作', '⚙  设置')
        self.nav_buttons = []
        for index, text in enumerate(nav_labels):
            button = W.QPushButton(text)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.goto(i))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addStretch()
        self.pill = W.QLabel('● 未连接')
        self.pill.setObjectName('pill')
        side.addWidget(self.pill)
        version = W.QLabel('v1.0 · PySide6 · Modbus-RTU')
        version.setObjectName('muted')
        side.addWidget(version)
        layout.addWidget(sidebar)

        self._build_pages()
        layout.addWidget(self.stack, 1)
        self.goto(0)
        self.statusBar().showMessage('未连接')

    def _build_pages(self):
        self.overview = OverviewPage(self)
        self.trends = TrendsPage(self)
        self.ops = OpsPage(self)
        self.settings = SettingsPage(self)
        self.stack.addWidget(self.overview)
        self.stack.addWidget(self.trends)
        self.stack.addWidget(self.ops)
        self.stack.addWidget(self.settings)
        self._pages = (self.overview, self.trends, self.ops, self.settings)
        # 图例开关与卡片开关共用同一份通道状态表
        self.trends.chart.enabled = self.channel_enabled
        self.trends.chart.on_toggle = self._chart_channel_toggled

    def set_channel_enabled(self, index, on):
        """通道开关唯一入口：改状态、存习惯、刷新界面。"""
        on = bool(on)
        if self.channel_enabled[index] == on:
            return
        self.channel_enabled[index] = on
        self._save_settings()
        self.log(f'CH{index + 1} 已{"打开" if on else "关闭"}')
        self.refresh_views()

    def _chart_channel_toggled(self, index):
        self._save_settings()
        self.refresh_views()

    def goto(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    # ---------- 属性：设置页控件在页面里，这里给出快捷访问 ----------

    @property
    def decimals(self):
        return self.settings.decimals

    @property
    def unit(self):
        return self.settings.unit

    @property
    def factor(self):
        return self.settings.factor.value()

    @property
    def last_raws(self):
        return self.live.last_raws

    @property
    def connected(self):
        return self.sensor is not None and self.sensor.connected

    # ---------- 设置记忆 ----------

    def _load_settings(self):
        """只恢复上次的选择项；不自动连接，不恢复零位。"""
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        index = self.overview.ports.findData(data.get('port'))
        if index >= 0:
            self.overview.ports.setCurrentIndex(index)
        if str(data.get('baud')) in [self.overview.baud.itemText(i)
                                     for i in range(self.overview.baud.count())]:
            self.overview.baud.setCurrentText(str(data['baud']))
        for key, spin in (('address', self.overview.address), ('hz', self.overview.hz),
                          ('decimals', self.settings.decimals)):
            value = data.get(key)
            if value is not None:
                spin.setValue(value)
        if data.get('unit'):
            self.settings.unit.setText(str(data['unit']))
        window_s = data.get('window_s')
        if window_s:
            self.trends.window_spin.setValue(int(window_s))
        factor = data.get('factor')
        if factor is not None:
            self.settings.factor.setValue(float(factor))
        if data.get('auto_connect'):
            self.settings.auto_connect.setChecked(True)
            self._want_auto_connect = True
        self.auto_port = data.get('port')
        channels = data.get('channels')
        if isinstance(channels, list) and len(channels) == 8:
            for i, on in enumerate(channels):
                with QtCore.QSignalBlocker(self.overview.cards[i].toggle):
                    self.overview.cards[i].toggle.setChecked(bool(on))
                self.channel_enabled[i] = bool(on)

    def _save_settings(self):
        data = {'port': self.overview.ports.currentData(),
                'baud': self.overview.baud.currentText(),
                'address': self.overview.address.value(),
                'hz': self.overview.hz.value(),
                'decimals': self.settings.decimals.value(),
                'unit': self.settings.unit.text(),
                'factor': self.settings.factor.value(),
                'auto_connect': self.settings.auto_connect.isChecked(),
                'window_s': self.trends.window_spin.value(),
                'channels': list(self.channel_enabled)}
        try:
            temp = SETTINGS_PATH.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, SETTINGS_PATH)
        except OSError as exc:
            self.log(f'设置保存失败：{exc}', 'error')

    # ---------- 连接 ----------

    def toggle_connection(self):
        if self.connected:
            self.disconnect_sensor()
        else:
            self.connect_sensor()

    def connect_sensor(self, auto=False):
        try:
            port = self.overview.ports.currentData()
            if not port:
                raise ValueError('未检测到串口；接入 USB/RS485 后点「刷新」。')
            if auto and port != self.auto_port:
                raise ValueError(f'自动连接：上次的 {self.auto_port} 不在当前串口列表，跳过。')
            self.sensor = ZnsvTransmitter(address=self.overview.address.value(),
                                          hz=self.overview.hz.value())
            self.sensor.connect(port, int(self.overview.baud.currentText()))
            self.port_name = port
            self.live.clear()
            self.frames.clear()
            self._save_settings()
            self.log(f'已打开 {port} @ {self.overview.baud.currentText()}，'
                     f'地址 {self.overview.address.value()}，等待首帧。')
        except Exception as exc:
            self.sensor = None
            self.log(f'{"自动连接" if auto else "连接"}失败：{exc}', 'error')
            if not auto:
                W.QMessageBox.warning(self, '连接失败', str(exc))
        self.refresh_views()

    def disconnect_sensor(self):
        self.stop_csv(quiet=True)
        if self.sensor is not None:
            self.sensor.disconnect()
        self.sensor = None
        self.live.clear()
        self.frames.clear()
        self.log('已断开。')
        self.refresh_views()

    # ---------- 采集 ----------

    def poll(self):
        if not self.connected:
            return
        try:
            raws = self.sensor.poll()
            if raws is None:
                return
            now = time.monotonic()
            self.live.push(now, raws, self.decimals.value(), self.zero_raws, self.factor)
            self.frames.append(now)
            self._append_csv(raws, now)
        except Exception as exc:
            self.log(f'采集异常，连接已关闭：{exc}', 'error')
            self.sensor = None

    # ---------- 状态与刷新 ----------

    def link_health(self):
        if not self.connected:
            return '未连接', '—', 0.0
        now = time.monotonic()
        while self.frames and now - self.frames[0] > 1:
            self.frames.popleft()
        span = self.frames[-1] - self.frames[0] if len(self.frames) > 1 else 0.0
        rate = (len(self.frames) - 1) / span if span > 0 else 0.0
        if not self.live.t:
            return '等待首帧', '—', rate
        age = now - self.live.t[-1]
        age_text = f'{age * 1000:.0f} ms'
        if age > 3 * self.sensor.timeout_s:
            return '数据过期', age_text, rate
        return '在线', age_text, rate

    def refresh_views(self):
        health, age_text, rate = self.link_health()
        state = ('off' if not self.connected else
                 'wait' if health == '等待首帧' else
                 'stale' if health == '数据过期' else 'on')
        color = PILL_STYLES[state]
        self.pill.setText(f'<span style="color:{color}">●</span> '
                          f'{"未连接" if state == "off" else health}')
        self.pill.setTextFormat(QtCore.Qt.TextFormat.RichText)
        if self.connected:
            s = self.sensor
            temp = s.temp_c
            zero_text = ' | 零位已设（显示为相对值）' if self.zero_raws is not None else ''
            self.statusBar().showMessage(
                f'{self.port_name} · {self.overview.baud.currentText()} · 地址 {s.address} | '
                f'数据年龄 {age_text} · 近 1 s {rate:.1f} 帧 | 累计 {s.sequence} 帧 · '
                f'超时 {s.timeouts} · 错帧 {s.protocol_errors}'
                + (f' | 温度 {temp:.1f} °C' if temp is not None else '') + zero_text)
        else:
            self.statusBar().showMessage('未连接')
        for page in self._pages:
            page.update_view()

    # ---------- 写命令 ----------

    def _submit(self, action, label):
        if not self.connected:
            self.statusBar().showMessage('请先连接变送器', 3000)
            return
        action()
        self.log(f'已排队：{label}（将在重量帧间隙发送）')

    def zero_channel(self, channel):
        if W.QMessageBox.question(self, '零点校准',
                f'CH{channel} 已空载（无负载）吗？\n校准会覆盖该路传感器零点标定。',
                W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No,
                W.QMessageBox.StandardButton.No) != W.QMessageBox.StandardButton.Yes:
            return
        self._submit(lambda: self.sensor.submit_channel_command(channel, 1, f'CH{channel} 零点校准'),
                     f'CH{channel} 零点校准')

    def tare_channel(self, channel):
        self._submit(lambda: self.sensor.submit_channel_command(channel, 2, f'CH{channel} 去皮'),
                     f'CH{channel} 去皮')

    def all_tare(self):
        if W.QMessageBox.question(self, '全部去皮归零',
                '对八路同时去皮归零（0x0026 写 1）吗？',
                W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No,
                W.QMessageBox.StandardButton.No) != W.QMessageBox.StandardButton.Yes:
            return
        self._submit(self.sensor.submit_all_tare, '全部去皮归零')

    # ---------- 本地零位 ----------

    def set_zero(self):
        """把最新一帧原始值记为零位；之后显示值/曲线/CSV 均为相对值。"""
        if not self.connected:
            self.statusBar().showMessage('请先连接变送器', 3000)
            return
        if self.live.last_raws is None or not self.live.t:
            self.statusBar().showMessage('还没有收到数据，无法设零位', 3000)
            return
        if time.monotonic() - self.live.t[-1] > 1.0:
            self.statusBar().showMessage('最新一帧已过期，等待新数据后再设零位', 3000)
            return
        self.zero_raws = self.live.last_raws
        self.live.clear()  # 曲线从新基线重新开始，避免绝对/相对混画
        self.log('本地零位已设置：' + ' '.join(f'CH{i+1}={v:+d}' for i, v in enumerate(self.zero_raws)))
        self.refresh_views()

    def clear_zero(self):
        if self.zero_raws is None:
            return
        self.zero_raws = None
        self.live.clear()
        self.log('本地零位已清除，恢复绝对读数。')
        self.refresh_views()

    # ---------- CSV ----------

    def toggle_csv(self):
        if self.csv_writer is not None:
            self.stop_csv()
            return
        if not self.connected:
            self.statusBar().showMessage('请先连接变送器再记录 CSV', 3000)
            return
        default = Path.cwd() / f'znsv_{datetime.now():%Y%m%d_%H%M%S}.csv'
        filename, _ = W.QFileDialog.getSaveFileName(
            self, '记录 CSV', str(default), 'CSV (*.csv)',
            options=W.QFileDialog.Option.DontConfirmOverwrite | W.QFileDialog.Option.DontUseNativeDialog)
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != '.csv':
            path = Path(str(path) + '.csv')
        new_file = not path.exists()
        self.csv_file = open(path, 'a', newline='', encoding='utf-8')
        self.csv_writer = csv.writer(self.csv_file)
        if new_file:
            self.csv_writer.writerow(['time', 'sequence']
                                     + [f'ch{i}_raw' for i in range(1, 9)]
                                     + [f'ch{i}' for i in range(1, 9)] + ['temp_c'])
        self.csv_rows = 0
        self.log(f'CSV 记录中：{path}')
        self.refresh_views()

    def _append_csv(self, raws, now):
        if self.csv_writer is None:
            return
        scale = 10 ** self.decimals.value()
        factor = self.factor
        temp = self.sensor.temp_c
        values = []
        for i, v in enumerate(raws):
            offset = self.zero_raws[i] if self.zero_raws is not None else 0
            shown = (v - offset) / scale * factor
            values.append(0.0 if shown == 0 else shown)
        self.csv_writer.writerow([datetime.now().isoformat(timespec='milliseconds'),
                                  self.sensor.sequence, *raws, *values,
                                  '' if temp is None else f'{temp:.1f}'])
        self.csv_rows += 1
        if self.csv_rows % 16 == 0:
            self.csv_file.flush()

    def stop_csv(self, quiet=False):
        if self.csv_file is not None:
            try:
                self.csv_file.flush()
                self.csv_file.close()
                if not quiet:
                    self.log(f'CSV 已保存（{self.csv_rows} 行）。')
            finally:
                self.csv_file, self.csv_writer = None, None

    # ---------- 日志 ----------

    def log(self, message, level='info'):
        prefix = {'info': '', 'error': '[错误] '}.get(level, '')
        line = f'{datetime.now():%H:%M:%S}  {prefix}{message}'
        if hasattr(self, 'ops'):
            self.ops.append_log(line)

    def closeEvent(self, event):
        self.poll_timer.stop()
        self.display_timer.stop()
        self.stop_csv(quiet=True)
        if self.sensor is not None:
            self.sensor.disconnect()
        event.accept()


def run():
    import sys
    from pathlib import Path
    if sys.platform == 'win32':
        # 让任务栏按应用分组并显示自己的图标，而不是挂在 pythonw 下
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('znsv.studio.1.0')
    app = W.QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(QSS)
    icon = QtGui.QIcon(str(Path(__file__).resolve().parent / 'appicon.ico'))
    if not icon.isNull():
        app.setWindowIcon(icon)  # 窗口标题栏 + Alt-Tab + 任务栏
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec()
