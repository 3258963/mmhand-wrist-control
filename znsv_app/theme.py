"""ZNSV Studio 主题：深色现代风调色板与全局 QSS。

只依赖 PySide6；所有颜色集中在这里，改主题不动业务代码。
"""

BG = '#0d1015'        # 窗口底
SIDEBAR = '#11151d'   # 侧栏
CARD = '#161c25'      # 卡片
CARD_LINE = '#232d3c'  # 卡片描边
INPUT = '#0f141c'     # 输入控件底
LINE = '#263041'      # 输入描边
TEXT = '#e8ecf2'
MUTED = '#8b94a3'
ACCENT = '#3b82f6'
ACCENT2 = '#22d3ee'
GOOD = '#34d399'
WARN = '#fbbf24'
BAD = '#f87171'

# 八通道分类色（曲线、卡片圆点、图例共用）
CHANNEL_COLORS = ('#38bdf8', '#f472b6', '#facc15', '#4ade80',
                  '#a78bfa', '#fb923c', '#2dd4bf', '#f87171')

MONO_FAMILY = 'Consolas'

QSS = f"""
* {{ font-family: 'Segoe UI', 'Microsoft YaHei UI'; }}

QMainWindow, QFrame#page {{ background: {BG}; }}
QFrame#shell {{ background: {BG}; }}
QFrame#sidebar {{
    background: {SIDEBAR};
    border-right: 1px solid #1d2430;
}}
QFrame#card {{
    background: {CARD};
    border: 1px solid {CARD_LINE};
    border-radius: 12px;
}}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#brand {{ color: #f5f8ff; font-size: 17px; font-weight: 700; }}
QLabel#brandSub {{ color: {MUTED}; font-size: 11px; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 12px; font-weight: 600; }}
QLabel#bigValue {{
    color: #f5f8ff; font-family: '{MONO_FAMILY}';
    font-size: 26px; font-weight: 700;
}}
QLabel#bigValue[missing="true"] {{ color: #4d5563; }}
QLabel#midValue {{
    color: #f5f8ff; font-family: '{MONO_FAMILY}';
    font-size: 20px; font-weight: 700;
}}
QLabel#pill {{ font-size: 12px; font-weight: 600; }}

QCheckBox#channelToggle {{ background: transparent; spacing: 0; }}
QCheckBox#channelToggle::indicator {{
    width: 34px; height: 18px; border-radius: 9px;
    background: #2a3242; border: 1px solid #3a4560;
}}
QCheckBox#channelToggle::indicator:hover {{ border: 1px solid #4a5878; }}
QCheckBox#channelToggle::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2563eb, stop:1 #06b6d4);
    border: 1px solid #3b82f6;
}}

QPushButton {{
    background: #1c2431; color: {TEXT};
    border: 1px solid {LINE}; border-radius: 8px;
    padding: 8px 16px; font-size: 13px;
}}
QPushButton:hover {{ background: #232d3d; border-color: #33405a; }}
QPushButton:pressed {{ background: #18202c; }}
QPushButton:disabled {{ color: #5b6472; background: #151b24; }}

QPushButton#primary {{
    color: #ffffff; border: none; font-weight: 600;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #2563eb, stop:1 #06b6d4);
    padding: 9px 22px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #22d3ee);
}}
QPushButton#primary:pressed {{ background: #1d4ed8; }}
QPushButton#primary:disabled {{ color: #9aa7bb; background: #24304a; }}

QPushButton#danger {{
    color: #ffffff; border: none; font-weight: 600; background: #b4232f;
    padding: 8px 16px;
}}
QPushButton#danger:hover {{ background: #d32736; }}
QPushButton#danger:disabled {{ color: #d8a0a5; background: #4a2229; }}

QPushButton#ghost {{
    background: transparent; border: 1px solid {LINE}; color: {MUTED};
    padding: 6px 12px;
}}
QPushButton#ghost:hover {{ color: {TEXT}; border-color: #3a4560; }}

QPushButton#nav {{
    background: transparent; border: none; border-radius: 8px;
    color: {MUTED}; text-align: left; padding: 11px 14px; font-size: 13.5px;
}}
QPushButton#nav:hover {{ background: #1a212c; color: {TEXT}; }}
QPushButton#nav:checked {{ background: #1f2a3b; color: #ffffff; font-weight: 600; }}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {INPUT}; color: {TEXT};
    border: 1px solid {LINE}; border-radius: 8px;
    padding: 6px 10px; min-height: 20px; font-size: 13px;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {MUTED}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: #141923; color: {TEXT};
    border: 1px solid {LINE}; selection-background-color: #24405e;
    border-radius: 8px; outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: #1c2431; border: none; width: 18px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #28334a; }}

QTableWidget {{
    background: #12161e; alternate-background-color: #151a24;
    gridline-color: #212a38; color: {TEXT};
    border: 1px solid {CARD_LINE}; border-radius: 10px;
    selection-background-color: #24405e; selection-color: #ffffff;
    font-size: 13px;
}}
QTableWidget::item {{ padding: 6px; }}
QHeaderView::section {{
    background: {CARD}; color: {MUTED};
    border: none; border-bottom: 1px solid {CARD_LINE};
    padding: 8px 6px; font-size: 12px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {CARD}; border: none; }}

QPlainTextEdit {{
    background: #10141b; color: #c6cedb;
    border: 1px solid {CARD_LINE}; border-radius: 10px;
    padding: 8px; font-family: '{MONO_FAMILY}'; font-size: 12px;
}}

QStatusBar {{ background: {SIDEBAR}; color: {MUTED}; border-top: 1px solid #1d2430; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #2a3242; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3a4560; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: #2a3242; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{ background: #1c2431; color: {TEXT}; border: 1px solid {LINE}; padding: 4px; }}

QMessageBox {{ background: {CARD}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 13px; }}
"""
