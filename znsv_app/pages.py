"""ZNSV Studio 四个页面：总览、曲线、通道操作、设置。

页面只读 app（MainWindow）上的状态并展示；连接与采集逻辑在 window.py。
"""
from datetime import datetime
from pathlib import Path

from PySide6 import QtGui, QtWidgets as W
from serial.tools import list_ports

from znsv_app.znsv import BAUD_BY_CODE
from znsv_app.theme import CHANNEL_COLORS, MONO_FAMILY
from znsv_app.widgets import Card, StatCard, TrendChart

REFRESH_HINT = '拨码非全零时实际站地址可能不同；读不到可改 254（广播，总线只能挂这一台）'


class OverviewPage(W.QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName('page')
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        connect_card = Card('连接 · ZNSV6-F8-485 八通道数字称重变送器')
        row = W.QHBoxLayout()
        row.setSpacing(8)
        self.ports = W.QComboBox()
        self.ports.setMinimumWidth(240)
        refresh = W.QPushButton('刷新')
        refresh.clicked.connect(self.refresh_ports)
        self.baud = W.QComboBox()
        self.baud.addItems([str(rate) for rate in BAUD_BY_CODE.values()])
        self.baud.setCurrentText('115200')
        self.address = W.QSpinBox()
        self.address.setRange(1, 254)
        self.address.setValue(1)
        self.address.setToolTip(REFRESH_HINT)
        self.hz = W.QDoubleSpinBox()
        self.hz.setRange(1, 50)
        self.hz.setDecimals(1)
        self.hz.setValue(20)
        self.connect_button = W.QPushButton('连接')
        self.connect_button.setObjectName('primary')
        self.connect_button.clicked.connect(app.toggle_connection)
        self.zero_button = W.QPushButton('设为零位')
        self.zero_button.setToolTip('把最新一帧原始值记为本地零位；此后显示值/曲线/CSV 为相对值，不写传感器')
        self.zero_button.clicked.connect(app.set_zero)
        self.clear_zero_button = W.QPushButton('清除零位')
        self.clear_zero_button.clicked.connect(app.clear_zero)
        for label, widget in (('串口', self.ports), ('波特', self.baud),
                              ('地址', self.address), ('目标 Hz', self.hz)):
            caption = W.QLabel(label)
            caption.setObjectName('muted')
            row.addWidget(caption)
            row.addWidget(widget)
        row.addWidget(refresh)
        row.addSpacing(8)
        row.addWidget(self.connect_button)
        row.addWidget(self.zero_button)
        row.addWidget(self.clear_zero_button)
        row.addStretch()
        connect_card.body.addLayout(row)
        self.zero_label = W.QLabel('零位：未设（显示绝对读数）')
        self.zero_label.setObjectName('muted')
        connect_card.body.addWidget(self.zero_label)
        hint = W.QLabel(REFRESH_HINT)
        hint.setObjectName('muted')
        connect_card.body.addWidget(hint)
        layout.addWidget(connect_card)

        grid = W.QGridLayout()
        grid.setSpacing(12)
        self.cards = [StatCard(i + 1) for i in range(8)]
        for index, card in enumerate(self.cards):
            grid.addWidget(card, index // 4, index % 4)
            card.toggle.toggled.connect(
                lambda on, i=index: app.set_channel_enabled(i, on))
        layout.addLayout(grid, 1)

        bottom = W.QHBoxLayout()
        bottom.setSpacing(12)
        temp_card = Card('温度 / 模块')
        self.temp_label = W.QLabel('—')
        self.temp_label.setObjectName('midValue')
        temp_card.body.addWidget(self.temp_label)
        self.module_label = W.QLabel('尚未读取模块信息')
        self.module_label.setObjectName('muted')
        self.module_label.setWordWrap(True)
        temp_card.body.addWidget(self.module_label)
        bottom.addWidget(temp_card, 1)
        link_card = Card('链路')
        self.link_label = W.QLabel('未连接')
        self.link_label.setObjectName('midValue')
        link_card.body.addWidget(self.link_label)
        self.rate_label = W.QLabel(' ')
        self.rate_label.setObjectName('muted')
        self.rate_label.setWordWrap(True)
        link_card.body.addWidget(self.rate_label)
        bottom.addWidget(link_card, 1)
        layout.addLayout(bottom)
        self.refresh_ports()

    def refresh_ports(self):
        selected = self.ports.currentData()
        self.ports.clear()
        for port in list_ports.comports():
            self.ports.addItem(f'{port.device} — {port.description}', port.device)
        index = self.ports.findData(selected)
        if index >= 0:
            self.ports.setCurrentIndex(index)

    def update_view(self):
        app = self.app
        connected = app.connected
        self.connect_button.setText('断开' if connected else '连接')
        for widget in (self.ports, self.baud, self.address, self.hz):
            widget.setEnabled(not connected)
        self.zero_button.setEnabled(connected)
        self.clear_zero_button.setEnabled(app.zero_raws is not None)
        if app.zero_raws is None:
            self.zero_label.setText('零位：未设（显示绝对读数）')
        else:
            parts = [f'CH{i + 1}={v:+d}' for i, v in enumerate(app.zero_raws) if v != 0]
            self.zero_label.setText('零位：已设 ' + (' '.join(parts) if parts else '全 0')
                                     + ' · 显示相对值')
        decimals = app.decimals.value()
        unit = app.unit.text().strip() or ' '
        spark_window = app.trends.chart.window_s
        for i, card in enumerate(self.cards):
            if card.toggle.isChecked() != app.channel_enabled[i]:
                card.toggle.blockSignals(True)
                card.toggle.setChecked(app.channel_enabled[i])
                card.toggle.blockSignals(False)
            raw = app.last_raws[i] if app.last_raws is not None else None
            series = app.live.ch[i]
            if not app.channel_enabled[i]:
                card.set_row('已关闭', '—', '打开右上开关恢复显示', [])
                card.set_missing(True)
                continue
            if raw is None or not series:
                card.set_row('—', '—', ' ', [])
                card.set_missing(False)
                continue
            display = series[-1]  # 已按零位与 小数位换算
            values = list(series)[-160:] or [display]
            missing = app.live.suspected_missing(i)
            if missing:
                sub = '恒 0 · 疑似未接传感器'
            else:
                lo_hi = app.live.channel_minmax(i, spark_window)
                sub = f'min {lo_hi[0]:.{decimals}f} · max {lo_hi[1]:.{decimals}f}'
            card.set_row(f'{display:+.{decimals}f} {unit}', f'raw {raw:+d}', sub, values)
            card.set_missing(missing)
        temp = app.sensor.temp_c if connected else None
        self.temp_label.setText(f'{temp:.1f} °C' if temp is not None else '—')
        info = app.sensor.info if connected else None
        if info is None:
            self.module_label.setText('尚未读取模块信息（连接后 2 s 一次低速读取）')
        else:
            _, address, baud_code, rate = info
            self.module_label.setText(
                f'地址 {address} · 波特代码 {baud_code}（{BAUD_BY_CODE.get(baud_code, "?")}）· 采样 {rate} Hz')
        health, age_text, rate_hz = app.link_health()
        self.link_label.setText(health)
        if connected:
            s = app.sensor
            self.rate_label.setText(
                f'数据年龄 {age_text} · 近 1 s {rate_hz:.1f} 帧\n'
                f'累计 {s.sequence} 帧 · 超时 {s.timeouts} · 错帧 {s.protocol_errors}')
        else:
            self.rate_label.setText(' ')


class TrendsPage(W.QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName('page')
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        header = W.QHBoxLayout()
        title = W.QLabel('多通道实时曲线')
        title.setObjectName('cardTitle')
        header.addWidget(title)
        header.addStretch()
        header.addWidget(W.QLabel('窗口'))
        self.window_spin = W.QDoubleSpinBox()
        self.window_spin.setRange(5, 180)
        self.window_spin.setDecimals(0)
        self.window_spin.setSuffix(' s')
        self.window_spin.setValue(30)
        self.window_spin.valueChanged.connect(self.set_window)
        self.window_spin.valueChanged.connect(lambda _=0.0: app._save_settings())
        header.addWidget(self.window_spin)
        clear = W.QPushButton('清空曲线')
        clear.clicked.connect(lambda: app.live.clear())
        header.addWidget(clear)
        layout.addLayout(header)
        self.chart = TrendChart()
        self.chart.set_model(app.live)
        layout.addWidget(self.chart, 1)
        tip = W.QLabel('纵轴按可见通道自适应 · 点击图例圆点开关通道 · 右端为最新样本')
        tip.setObjectName('muted')
        layout.addWidget(tip)

    def set_window(self, seconds):
        self.chart.window_s = float(seconds)

    def update_view(self):
        self.chart.update()


class OpsPage(W.QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName('page')
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        table_card = Card('通道数据与操作')
        self.table = W.QTableWidget(8, 5)
        self.table.setHorizontalHeaderLabels(('通道', '原始值 int32', '显示值', '零点校准', '去皮'))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(320)
        font = self.table.font()
        font.setFamily(MONO_FAMILY)
        self._zero_buttons, self._tare_buttons = [], []
        for channel in range(1, 9):
            r = channel - 1
            self.table.setItem(r, 0, W.QTableWidgetItem(f'CH{channel}'))
            self.table.item(r, 0).setForeground(
                QtGui.QColor(CHANNEL_COLORS[r]).lighter(160))
            for col in (1, 2):
                item = W.QTableWidgetItem('—')
                self.table.setItem(r, col, item)
            zero = W.QPushButton('零点校准')
            zero.setToolTip('空载时向本路命令寄存器写 1，覆盖零点标定')
            zero.clicked.connect(lambda checked=False, ch=channel: app.zero_channel(ch))
            tare = W.QPushButton('去皮')
            tare.clicked.connect(lambda checked=False, ch=channel: app.tare_channel(ch))
            self._zero_buttons.append(zero)
            self._tare_buttons.append(tare)
            self.table.setCellWidget(r, 3, zero)
            self.table.setCellWidget(r, 4, tare)
        table_card.body.addWidget(self.table)
        layout.addWidget(table_card)

        buttons = W.QHBoxLayout()
        all_tare = W.QPushButton('全部去皮归零')
        all_tare.setObjectName('danger')
        all_tare.setToolTip('寄存器 0x0026 写 1，八路同时去皮')
        all_tare.clicked.connect(app.all_tare)
        self.all_tare = all_tare
        csv_button = W.QPushButton('记录 CSV')
        csv_button.setObjectName('primary')
        csv_button.clicked.connect(app.toggle_csv)
        self.csv_button = csv_button
        buttons.addWidget(all_tare)
        buttons.addWidget(csv_button)
        self.write_label = W.QLabel('写命令：无')
        self.write_label.setObjectName('muted')
        buttons.addSpacing(16)
        buttons.addWidget(self.write_label)
        buttons.addStretch()
        layout.addLayout(buttons)

        log_card = Card('事件日志')
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        log_card.body.addWidget(self.log)
        layout.addWidget(log_card)
        warning = W.QLabel('零点校准必须空载；会覆盖该路传感器零点标定。'
                           '本界面不提供恢复出厂（说明书 0x0026←9，会清除全部校准参数）。')
        warning.setObjectName('muted')
        warning.setWordWrap(True)
        layout.addWidget(warning)

    def append_log(self, text):
        self.log.appendPlainText(text)

    def update_view(self):
        app = self.app
        connected = app.connected
        self.all_tare.setEnabled(connected)
        off_color = QtGui.QColor('#4d5563')
        on_color = QtGui.QColor('#e8ecf2')
        decimals = app.decimals.value()
        unit = app.unit.text().strip()
        for i in range(8):
            on = app.channel_enabled[i]
            self._zero_buttons[i].setEnabled(connected and on)
            self._tare_buttons[i].setEnabled(connected and on)
            raw = app.last_raws[i] if app.last_raws is not None else None
            if not on or raw is None:
                self.table.item(i, 1).setText('—')
                self.table.item(i, 2).setText('—')
            else:
                offset = app.zero_raws[i] if app.zero_raws is not None else 0
                shown = (raw - offset) / 10 ** decimals * app.factor
                if shown == 0:
                    shown = 0.0
                self.table.item(i, 1).setText(f'{raw:+d}')
                self.table.item(i, 2).setText(f'{shown:+.{decimals}f} {unit}')
            for col in (1, 2):
                self.table.item(i, col).setForeground(off_color if not on else on_color)
        last_write = '写命令：无'
        if connected and app.sensor.last_write is not None:
            label, state, _ = app.sensor.last_write
            last_write = f'写命令：{label} → {state}'
        self.write_label.setText(last_write)
        self.csv_button.setText('停止记录并保存' if app.csv_writer is not None else '记录 CSV')


class SettingsPage(W.QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName('page')
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        display_card = Card('显示')
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel('小数位'))
        self.decimals = W.QSpinBox()
        self.decimals.setRange(0, 3)
        self.decimals.setValue(0)
        self.decimals.setToolTip('寄存器值不含小数点：按标定砝码写法定小数位（100.00 标定填 10000 → 选 2）')
        self.decimals.valueChanged.connect(lambda _=0: app._save_settings())
        row.addWidget(self.decimals)
        row.addWidget(W.QLabel('单位'))
        self.unit = W.QLineEdit('N')
        self.unit.setMaximumWidth(80)
        self.unit.setToolTip('仅显示文字，不参与换算；变送器输出本身不带单位')
        self.unit.editingFinished.connect(app._save_settings)
        row.addWidget(self.unit)
        row.addWidget(W.QLabel('换算系数'))
        self.factor = W.QDoubleSpinBox()
        self.factor.setRange(-1000, 1000)
        self.factor.setDecimals(9)
        self.factor.setValue(1.0)
        self.factor.setSingleStep(0.001)
        self.factor.setToolTip('显示值 =（原始值 − 零位）/ 10^小数位 × 系数\n'
                               '例：受拉时 raw 减小且 1 raw = 1 g，要显示牛顿填 -0.009806650')
        self.factor.valueChanged.connect(lambda _=0.0: app._save_settings())
        row.addWidget(self.factor)
        row.addStretch()
        display_card.body.addLayout(row)
        self.auto_connect = W.QCheckBox('启动时自动连接上次串口')
        self.auto_connect.setToolTip('仅当上次的串口仍在当前串口列表中才连接；失败只记日志不弹窗')
        self.auto_connect.toggled.connect(lambda _=False: app._save_settings())
        display_card.body.addWidget(self.auto_connect)
        note = W.QLabel('显示值 =（原始值 − 零位）/ 10^小数位 × 换算系数。修改立即生效，'
                        '作用于数值、曲线与 CSV 后续行。')
        note.setObjectName('muted')
        note.setWordWrap(True)
        display_card.body.addWidget(note)
        layout.addWidget(display_card)

        proto_card = Card('协议速览（说明书见 docs/）')
        lines = (
            '· RS485 Modbus-RTU，功能码 03/06/0x10；默认 115200 8N1、地址 1、CRC 小端。',
            '· 重量：寄存器 0x0000 起，每路 2 个保持寄存器组成 32 位有符号，低字在低地址（CDAB）。',
            '· 温度：0x001B，范围 0~1800，减 550 后按 0.1 °C 解释（说明书未写单位，实机不符改 znsv.temperature_c）。',
            '· 模块地址 / 波特率代码 / 通讯速率：0x001C / 0x001D / 0x001E。',
            '· 写命令：单路零点=1、去皮=2（0x0028+10×(路-1)）；全部去皮=0x0026←1。',
        )
        for line in lines:
            label = W.QLabel(line)
            label.setObjectName('muted')
            label.setWordWrap(True)
            proto_card.body.addWidget(label)
        layout.addWidget(proto_card)
        layout.addStretch()

    def update_view(self):
        pass  # 设置页无实时数据
