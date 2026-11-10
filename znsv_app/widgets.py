"""ZNSV Studio 自绘控件：卡片、通道卡、迷你走势、多通道大图表。"""
import time
from collections import deque

from PySide6 import QtCore, QtGui, QtWidgets as W

from znsv_app.theme import CHANNEL_COLORS, CARD_LINE, MUTED

N_CHANNELS = 8


class Card(W.QFrame):
    """圆角卡片容器；body 是内容布局，title 可选。"""

    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        outer = W.QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)
        if title:
            label = W.QLabel(title)
            label.setObjectName('cardTitle')
            outer.addWidget(label)
        self.body = W.QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)


class StatCard(Card):
    """通道卡：标题行（圆点 + CHn + 数据开关）、大数值、副行、迷你走势。"""

    def __init__(self, channel, parent=None):
        super().__init__(parent)
        header = W.QHBoxLayout()
        dot = W.QLabel(f'<span style="color:{CHANNEL_COLORS[channel - 1]}">●</span> CH{channel}')
        dot.setTextFormat(QtCore.Qt.TextFormat.RichText)
        dot.setObjectName('cardTitle')
        header.addWidget(dot)
        header.addStretch()
        self.raw_label = W.QLabel('—')
        self.raw_label.setObjectName('muted')
        header.addWidget(self.raw_label)
        self.toggle = W.QCheckBox()
        self.toggle.setObjectName('channelToggle')
        self.toggle.setToolTip(f'CH{channel} 数据开关：关闭后不显示数值、不画曲线\n（仍会读取并记入 CSV，重新打开即恢复）')
        header.addWidget(self.toggle)
        self.body.addLayout(header)
        self.value = W.QLabel('—')
        self.value.setObjectName('bigValue')
        self.body.addWidget(self.value)
        self.sub = W.QLabel(' ')
        self.sub.setObjectName('muted')
        self.body.addWidget(self.sub)
        self.spark = Sparkline(CHANNEL_COLORS[channel - 1])
        self.body.addWidget(self.spark)

    def set_row(self, value_text, raw_text, sub_text, spark):
        self.value.setText(value_text)
        self.raw_label.setText(raw_text)
        self.sub.setText(sub_text)
        self.spark.set_data(spark)

    def set_missing(self, missing):
        """恒 0 疑似未接：数值变灰。出现非零后由界面恢复。"""
        if self.property('missing') == missing:
            return
        self.setProperty('missing', missing)
        style = self.value.style()
        style.unpolish(self.value)
        style.polish(self.value)


class Sparkline(W.QWidget):
    """单色迷你走势：折线 + 底部渐隐填充。"""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = color
        self._data = []
        self.setMinimumHeight(42)

    def set_data(self, values):
        self._data = list(values)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.transparent)
        data = self._data[-240:]
        if len(data) < 2:
            painter.setPen(QtGui.QPen(QtGui.QColor(CARD_LINE), 1, QtCore.Qt.PenStyle.DashLine))
            painter.drawLine(4, height // 2, width - 4, height // 2)
            return
        lo, hi = min(data), max(data)
        if lo == hi:
            lo, hi = lo - 1, hi + 1
        top, bottom = 4, height - 4
        span_x, span_y = width - 8, bottom - top

        def point(i, v):
            return QtCore.QPointF(4 + span_x * i / (len(data) - 1),
                                  bottom - span_y * (v - lo) / (hi - lo))

        points = [point(i, v) for i, v in enumerate(data)]
        base = bottom + 3
        polygon = QtGui.QPolygonF(points + [QtCore.QPointF(points[-1].x(), base),
                                            QtCore.QPointF(points[0].x(), base)])
        color = QtGui.QColor(self._color)
        fill = QtGui.QLinearGradient(0, top, 0, base)
        fill.setColorAt(0.0, QtGui.QColor(color.red(), color.green(), color.blue(), 70))
        fill.setColorAt(1.0, QtGui.QColor(color.red(), color.green(), color.blue(), 0))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPolygon(polygon)
        painter.setPen(QtGui.QPen(color, 1.5))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QtGui.QPolygonF(points))


class TrendChart(W.QWidget):
    """八通道大图表：右端为最新；图例可点击开关通道；纵轴自适应。"""

    MARGINS = (16, 40, 20, 66)  # left, top, bottom, right

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None            # window.LiveData
        self.enabled = [True] * N_CHANNELS  # 与 MainWindow.channel_enabled 同一份表
        self.on_toggle = None        # 图例开关回调（索引）
        self.window_s = 30.0
        self.setMinimumHeight(320)
        self._chip_rects = []
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def set_model(self, model):
        self.model = model

    def _visible(self, now):
        """返回 (times, [values...])：窗口内共同下标区间的数据。"""
        t = self.model.t
        if not t or len(t) < 2:
            return [], []
        start = len(t)
        for index in range(len(t) - 1, -1, -1):
            if now - t[index] > self.window_s:
                break
            start = index
        if start >= len(t) - 1:
            return [], []
        times = list(t)[start:]
        values = [list(series)[start:] for series in self.model.ch]
        return times, values

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        for index, rect in enumerate(self._chip_rects):
            if rect.contains(pos):
                self.enabled[index] = not self.enabled[index]
                if self.on_toggle is not None:
                    self.on_toggle(index)
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.transparent)
        left, top, bottom, right = (self.MARGINS[0], self.MARGINS[1],
                                    self.height() - self.MARGINS[2], self.width() - self.MARGINS[3])
        now = time.monotonic()
        times, series = ([], []) if self.model is None else self._visible(now)
        lo = hi = None
        for values, on in zip(series, self.enabled):
            if not on:
                continue
            for v in values:
                lo = v if lo is None else min(lo, v)
                hi = v if hi is None else max(hi, v)
        painter.setPen(QtGui.QColor(MUTED))
        if lo is None:
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter,
                             '等待数据… 连接变送器后开始绘制')
            self._draw_chips(painter, left)
            return
        if lo == hi:
            lo, hi = lo - 1, hi + 1
        else:
            pad = (hi - lo) * 0.08
            lo, hi = lo - pad, hi + pad
        span_x, span_y = right - left, bottom - top
        t0 = times[0]

        def x_at(t):
            return left + span_x * (t - t0) / max(1e-6, times[-1] - t0)

        def y_at(v):
            return bottom - span_y * (v - lo) / (hi - lo)

        grid_color = QtGui.QColor('#1d2532')
        label = QtGui.QColor(MUTED)
        painter.setFont(self.font())
        for i in range(5):
            y = top + span_y * i / 4
            painter.setPen(QtGui.QPen(grid_color))
            painter.drawLine(left, int(y), right, int(y))
            v = hi - (hi - lo) * i / 4
            painter.setPen(label)
            painter.drawText(right + 8, int(y) + 4,
                             f'{v:,.2f}' if abs(v) < 1000 else f'{v:,.0f}')
        for i in range(5):
            ratio = i / 4
            painter.setPen(label)
            seconds = int((1 - ratio) * self.window_s)
            x = int(left + span_x * ratio)
            painter.drawText(x - 12, bottom + 16, f'-{seconds}s' if seconds else '0s')
        if lo < 0 < hi:
            painter.setPen(QtGui.QPen(QtGui.QColor('#39445a'), 1, QtCore.Qt.PenStyle.DashLine))
            zero_y = int(y_at(0))
            painter.drawLine(left, zero_y, right, zero_y)

        for index, (values, on) in enumerate(zip(series, self.enabled)):
            if not on or len(values) < 2:
                continue
            points = QtGui.QPolygonF(
                [QtCore.QPointF(x_at(t), y_at(v)) for t, v in zip(times, values)])
            color = QtGui.QColor(CHANNEL_COLORS[index])
            painter.setPen(QtGui.QPen(color, 1.6))
            painter.drawPolyline(points)
            painter.setBrush(color)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(points.at(points.count() - 1), 3.0, 3.0)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        self._draw_chips(painter, left)

    def _draw_chips(self, painter, left):
        """顶部图例（可点击开关通道），返回时不影响调用方画笔状态。"""
        self._chip_rects = []
        metrics = painter.fontMetrics()
        x = left
        for index in range(N_CHANNELS):
            text = f'CH{index + 1}'
            chip_w = 14 + 10 + 6 + metrics.horizontalAdvance(text) + 12
            rect = QtCore.QRect(x, 8, chip_w, 22)
            self._chip_rects.append(rect)
            color = QtGui.QColor(CHANNEL_COLORS[index])
            painter.setPen(QtGui.QPen(QtGui.QColor('#2a3446'), 1))
            painter.setBrush(QtGui.QColor('#161c25'))
            painter.drawRoundedRect(rect, 11, 11)
            painter.setBrush(color if self.enabled[index] else QtGui.QColor('#3a4456'))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(rect.left() + 9, rect.center().y() - 3, 7, 7)
            painter.setPen(QtGui.QColor('#e8ecf2') if self.enabled[index] else QtGui.QColor(MUTED))
            painter.drawText(rect.left() + 22, rect.center().y() + 5, text)
            x += chip_w + 8
