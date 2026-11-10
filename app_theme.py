"""全局主题系统 —— 夜间 / 白天 / 赛博朋克 / 自定义，全 app 统一配色（2026-10-28）。

设计约定：
- 语义色槽一处定义；全局 QSS、观测台 QSS 与一切动态着色（状态色/表格
  前景/曲线背景）都读 current()/T()——切主题即时生效。
- 自定义主题：布局 JSON 存覆盖项（"custom_theme"），缺省槽继承夜间预设。
- znsv_app 是搬运来的独立应用，保持自身主题，不经本模块。
- 颜色槽语义：bg 窗口底 / panel 卡片 / panel_line 卡片描边 / input 输入底 /
  input_line 输入描边 / text 正文 / muted 次要 / dim 更弱(旧数据) /
  accent 主强调 / accent2 副强调 / good·warn·bad 三态 / grid 网格 /
  plot_bg·plot_fg 曲线区 / table_alt 表格隔行 / channels C1..C8 分类色。
"""
from __future__ import annotations

MONO_FAMILY = "Consolas"
UI_FAMILY = "'Segoe UI', 'Microsoft YaHei UI'"

_NIGHT = {
    "bg": "#0d1015", "panel": "#161c25", "panel_line": "#232d3c",
    "input": "#0f141c", "input_line": "#263041",
    "text": "#e8ecf2", "muted": "#8b94a3", "dim": "#4d5563",
    "accent": "#3b82f6", "accent2": "#22d3ee",
    "good": "#34d399", "warn": "#fbbf24", "bad": "#f87171",
    "grid": "#1d2532", "plot_bg": "#111417", "plot_fg": "#c8ccd0",
    "table_alt": "#151a24",
    "channels": ("#38bdf8", "#f472b6", "#facc15", "#4ade80",
                 "#a78bfa", "#fb923c", "#2dd4bf", "#f87171"),
}

_DAY = {
    "bg": "#f2f4f8", "panel": "#ffffff", "panel_line": "#d8dee8",
    "input": "#ffffff", "input_line": "#c3ccd9",
    "text": "#1a2330", "muted": "#4a5568", "dim": "#8b95a6",
    "accent": "#2563eb", "accent2": "#0e7490",
    "good": "#059669", "warn": "#b45309", "bad": "#dc2626",
    "grid": "#e3e8ef", "plot_bg": "#ffffff", "plot_fg": "#2a3340",
    "table_alt": "#f3f5f9",
    "channels": ("#0284c7", "#db2777", "#ca8a04", "#16a34a",
                 "#7c3aed", "#ea580c", "#0d9488", "#dc2626"),
}

_CYBER = {
    "bg": "#0a0118", "panel": "#170a2b", "panel_line": "#3b1d5e",
    "input": "#10051f", "input_line": "#4c2a75",
    "text": "#e9f4ff", "muted": "#a183cf", "dim": "#5d4a80",
    "accent": "#ff2ec4", "accent2": "#00f0ff",
    "good": "#00ff9c", "warn": "#ffd400", "bad": "#ff3860",
    "grid": "#2a1440", "plot_bg": "#0d0318", "plot_fg": "#c9b8e8",
    "table_alt": "#140826",
    "channels": ("#00f0ff", "#ff2ec4", "#ffd400", "#00ff9c",
                 "#b967ff", "#ff8a00", "#40ffd0", "#ff5b6e"),
}

# 曲线调色板：夜间/赛博用亮色系（深底），白天换深色系（浅底），按索引一一对应；
# 换主题时把通道色按索引互换（用户自定义过的颜色不动的判断由调用方做）。
CURVE_DARK = ("#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0",
              "#f032e6", "#bcf60c", "#fabebe", "#008080", "#9a6324", "#fffac8",
              "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9")
CURVE_LIGHT = ("#c2185b", "#2e7d32", "#283593", "#bf5700", "#6a1b9a", "#00838f",
               "#ad1457", "#558b2f", "#8d6e63", "#00695c", "#795548", "#9e9d24",
               "#5d1010", "#388e3c", "#556b2f", "#a1887f", "#1a237e", "#546e7a")


def curve_palette() -> tuple:
    """当前主题的曲线色板（白天=深色系，夜间/赛博/自定义=亮色系）。"""
    return CURVE_LIGHT if _current_name == "day" else CURVE_DARK


PRESETS = {"night": _NIGHT, "day": _DAY, "cyber": _CYBER}
DISPLAY_NAMES = {"night": "🎨 夜间", "day": "☀ 白天", "cyber": "🌐 赛博朋克",
                 "custom": "✏ 自定义…"}

# 自定义主题可编辑槽（对话框暴露这些；其余继承夜间）。
EDITABLE_SLOTS = ("bg", "panel", "panel_line", "input", "input_line",
                  "text", "muted", "accent", "accent2", "good", "warn", "bad")
SLOT_LABELS = {
    "bg": "窗口底色", "panel": "卡片底色", "panel_line": "卡片描边",
    "input": "输入底色", "input_line": "输入描边", "text": "正文色",
    "muted": "次要文字", "accent": "主强调色", "accent2": "副强调色",
    "good": "正常/在线", "warn": "警告/松绳", "bad": "错误/过载",
}

_current = dict(_NIGHT)
_current_name = "night"


def set_theme(name: str, custom_overrides: dict | None = None) -> None:
    """切换主题；custom 时 overrides 的槽覆盖夜间预设（无效槽忽略）。"""
    global _current, _current_name
    if name not in PRESETS and name != "custom":
        name = "night"
    base = dict(PRESETS.get(name, _NIGHT))
    if name == "custom" and isinstance(custom_overrides, dict):
        for k, v in custom_overrides.items():
            if k in base and isinstance(v, str) and v.startswith("#"):
                base[k] = v
    _current, _current_name = base, name


def current() -> dict:
    return _current


def current_name() -> str:
    return _current_name


def T(key: str) -> str:
    """取当前主题色槽（channels 返回元组，其余返回 '#rrggbb'）。"""
    return _current[key]


def build_app_qss() -> str:
    c = _current
    return f"""
QWidget {{ background: transparent; color: {c['text']}; font-size: 12px; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QLabel {{ color: {c['text']}; background: transparent; }}
QLabel#muted {{ color: {c['muted']}; font-size: 11px; }}
QLabel#dataLine {{ color: {c['text']}; font-size: 11px; font-family: '{MONO_FAMILY}'; }}
QGroupBox {{
    background: {c['panel']}; border: 1px solid {c['panel_line']};
    border-radius: 10px; margin-top: 12px;
    font-weight: 600; color: {c['muted']};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 4px;
    color: {c['muted']};
}}
QPushButton {{
    background: {c['panel']}; color: {c['text']};
    border: 1px solid {c['panel_line']}; border-radius: 8px;
    padding: 6px 14px; font-size: 13px;
}}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['input']}; }}
QPushButton:disabled {{ color: {c['dim']}; }}
QPushButton#primary {{
    color: #ffffff; border: none; font-weight: 600;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['accent']}, stop:1 {c['accent2']});
    padding: 8px 18px;
}}
QPushButton#danger {{
    color: #ffffff; border: none; font-weight: 600;
    background: {c['bad']}; padding: 8px 16px;
}}
QPushButton#ghost {{
    background: transparent; border: 1px solid {c['panel_line']};
    color: {c['muted']}; border-radius: 6px; padding: 2px 10px; font-size: 11px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {c['input']}; color: {c['text']};
    border: 1px solid {c['input_line']}; border-radius: 8px;
    padding: 5px 8px; min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['accent']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {c['muted']}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {c['panel']}; color: {c['text']};
    border: 1px solid {c['panel_line']};
    selection-background-color: {c['accent']}; selection-color: #ffffff;
}}
QCheckBox {{ color: {c['text']}; background: transparent; spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {c['input_line']};
    border-radius: 4px; background: {c['input']};
}}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QCheckBox:disabled {{ color: {c['dim']}; }}
QRadioButton {{ color: {c['text']}; background: transparent; }}
QTableWidget, QTreeWidget {{
    background: {c['panel']}; alternate-background-color: {c['table_alt']};
    gridline-color: {c['grid']}; color: {c['text']};
    border: 1px solid {c['panel_line']}; border-radius: 8px;
    selection-background-color: {c['accent']}; selection-color: #ffffff;
}}
QHeaderView::section {{
    background: {c['panel']}; color: {c['muted']};
    border: none; border-bottom: 1px solid {c['panel_line']}; padding: 5px 6px;
}}
QPlainTextEdit, QTextEdit {{
    background: {c['input']}; color: {c['text']};
    border: 1px solid {c['panel_line']}; border-radius: 8px; padding: 6px;
}}
QStatusBar {{ background: {c['panel']}; color: {c['muted']}; }}
QLabel#tile {{
    background: {c['panel']}; border: 1px solid {c['panel_line']};
    border-radius: 6px; padding: 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {c['panel_line']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {c['panel_line']}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {c['panel']}; color: {c['text']};
    border: 1px solid {c['accent']}; padding: 4px; }}
QMessageBox {{ background: {c['panel']}; }}
QSplitter::handle {{ background: {c['panel_line']}; }}
"""


def build_dashboard_qss() -> str:
    """张力·R 观测台样式（随主题重建；RTensionWindow 专用选择器）。"""
    c = _current
    return build_app_qss() + f"""
RTensionWindow {{ background: {c['bg']}; }}
QLabel#cardTitle {{ color: {c['muted']}; font-size: 12px; font-weight: 600; }}
QLabel#bigValue {{
    color: {c['text']}; font-family: '{MONO_FAMILY}';
    font-size: 24px; font-weight: 700;
}}
QWidget#card {{
    background: {c['panel']}; border: 1px solid {c['panel_line']};
    border-radius: 12px;
}}
QFrame#sparkHost {{
    background: {c['plot_bg']}; border: 1px solid {c['panel_line']};
    border-radius: 6px;
}}
QTabWidget::pane {{ border: 1px solid {c['panel_line']}; border-radius: 10px; background: {c['bg']}; top: -1px; }}
QTabBar::tab {{
    background: {c['panel']}; color: {c['muted']};
    padding: 5px 16px; margin-right: 4px;
    border: 1px solid {c['panel_line']}; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
}}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
"""
