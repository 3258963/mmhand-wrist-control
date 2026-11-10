"""门禁拒绝弹窗形式的视觉预览（纯离线渲染，不弹真窗、不碰串口）。

输出三张 PNG 到本目录：
    preview_reject_toast.png    方案A：非模态 toast（右下角浮动、不遮罩、不抢焦点）
    preview_reject_modal.png    方案B：模态 QMessageBox（全窗遮罩、必须点确定）
    preview_reject_centered.png 方案C：居中置顶弹窗、必须手动关、不锁主窗
                                 + 弹窗内急停按钮 + 重复拒绝合并计数

共用同一个"模拟主窗"背景（左列直控按钮 + 右侧曲线区 + 右下角曲线），
差异只在拒绝时刻发生什么：A/C 里急停依然可以直接点（C 还多一个弹窗内
急停）；B 里整窗被罩住。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

import app_theme as AT

W, H = 640, 460
REASON = ("t=3N 不在当前位姿可行域 [3.78, 40]N\n"
          "（fmin_eff/min(n̂)=3.78：f_min=1 顶高了地板，"
          "解法 f_min 回 0.5 或 t≥3.8）")


# ---------------------------------------------------------------- 模拟主窗
def _plot_pixmap(w: int, h: int) -> QPixmap:
    """右侧曲线区：网格 + 两条淡曲线（τ 双向 / 张紧 t 的示意）。"""
    pm = QPixmap(w, h)
    pm.fill(QColor(AT.T("plot_bg")))
    p = QPainter(pm)
    grid, fg = QColor(AT.T("grid")), QColor(AT.T("plot_fg"))
    p.setPen(grid)
    for x in range(0, w, 44):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, 36):
        p.drawLine(0, y, w, y)
    import math
    for amp, base, color in ((34, h * 0.42, AT.T("accent")),
                             (22, h * 0.66, AT.T("good"))):
        p.setPen(QColor(color))
        p.setRenderHint(QPainter.Antialiasing)
        pts = [(x, base + amp * math.sin(x / 58.0) * math.exp(-x / 900.0))
               for x in range(0, w, 4)]
        for i in range(len(pts) - 1):
            p.drawLine(int(pts[i][0]), int(pts[i][1]),
                       int(pts[i + 1][0]), int(pts[i + 1][1]))
    p.end()
    return pm


def build_mock_window(parent: QWidget) -> dict:
    """模拟主窗：左列按钮（含急停）+ 右侧曲线区。返回控件引用供摆位。"""
    lay = QHBoxLayout(parent)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(12)

    left = QWidget()
    lv = QVBoxLayout(left)
    lv.setContentsMargins(0, 0, 0, 0)
    lv.setSpacing(8)

    def _btn(text: str, kind: str = "normal") -> QPushButton:
        b = QPushButton(text)
        if kind == "bad":
            b.setStyleSheet(
                f"color:white; background:{AT.T('bad')}; font-weight:700; "
                f"border:1px solid {AT.T('bad')}; border-radius:5px; padding:7px;")
        else:
            b.setStyleSheet(
                f"color:{AT.T('text')}; background:{AT.T('input')}; "
                f"border:1px solid {AT.T('input_line')}; border-radius:5px; padding:7px;")
        return b

    estop = _btn("⛔ 急停 STOP", "bad")
    estop.setMinimumWidth(196)
    lv.addWidget(_btn("使能直控（自动归零+保持）"))
    lv.addWidget(_btn("💾 存储零位"))
    lv.addWidget(_btn("🎯 回到零位"))
    tighten = _btn("🪢 一键紧绳")
    tighten.setStyleSheet(
        f"color:{AT.T('text')}; background:{AT.T('input')}; border:2px solid "
        f"{AT.T('accent')}; border-radius:5px; padding:6px;")
    lv.addWidget(tighten)
    lv.addWidget(_btn("🪢 一键松绳"))
    lv.addWidget(estop)
    lv.addStretch(1)
    lay.addWidget(left, 0)

    plot = QLabel()
    plot.setPixmap(_plot_pixmap(W - 260, H - 24))
    lay.addWidget(plot, 1)
    return {"estop": estop, "tighten": tighten, "plot": plot}


# ---------------------------------------------------------------- 方案A toast
class RejectToast(QWidget):
    """与 PLAN 中 _RejectToast 同款样式的静态预览。"""

    def __init__(self, gate: str, reason: str, merge: int = 1):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        merge_txt = "" if merge <= 1 else f"（{merge}s 内第 {merge} 次，已合并）"
        self.setStyleSheet(
            f"background:{AT.T('panel')}; border:2px solid {AT.T('bad')};"
            f"border-radius:8px;")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)
        title = QLabel(f"⛔ {gate} 被拒{merge_txt}")
        title.setStyleSheet(
            f"color:{AT.T('bad')}; font-weight:700; font-size:13px;"
            f"border:none; background:transparent;")
        body = QLabel(reason)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color:{AT.T('text')}; font-size:12px; border:none;"
            f"background:transparent;")
        foot = QLabel("点击关闭 · 4s 自动消失 · 不拦截任何操作")
        foot.setStyleSheet(
            f"color:{AT.T('muted')}; font-size:11px; border:none;"
            f"background:transparent;")
        v.addWidget(title)
        v.addWidget(body)
        v.addWidget(foot)
        self.setFixedWidth(340)
        self.adjustSize()


def render_toast() -> None:
    host = QWidget()
    host.setStyleSheet(f"background:{AT.T('bg')};")
    host.setFixedSize(W, H)
    build_mock_window(host)
    t1 = RejectToast("🪢 一键紧绳", REASON)
    t1.setParent(host)
    t1.move(W - t1.width() - 18, H - t1.height() - 16)
    t2 = RejectToast("⚠ 张力控制", "张力数据过期 → 冻结（电机保持）", merge=2)
    t2.setParent(host)
    t2.move(W - t2.width() - 18, H - t1.height() - t2.height() - 28)
    host.grab().save(str(Path(__file__).parent / "preview_reject_toast.png"))


# ---------------------------------------------------------------- 方案B 模态
def render_modal() -> None:
    host = QWidget()
    host.setStyleSheet(f"background:{AT.T('bg')};")
    host.setFixedSize(W, H)
    mock = build_mock_window(host)

    # 模态语义：整窗被半透明遮罩罩住（QMessageBox.exec 期间主窗不可点）
    dim = QWidget(host)
    dim.setGeometry(0, 0, W, H)
    dim.setStyleSheet("background:rgba(0,0,0,135);")

    box = QMessageBox(host)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("一键紧绳 被拒")
    box.setText(REASON)
    box.setInformativeText(
        "模态对话框：关闭它之前，主窗所有控件（含 ⛔ 急停）都无法点击。")
    box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
    box.setStyleSheet(
        f"QMessageBox{{background:{AT.T('panel')}; color:{AT.T('text')};}}"
        f"QPushButton{{padding:5px 18px;}}")
    box.adjustSize()
    box.move((W - box.width()) // 2, (H - box.height()) // 2)
    box.raise_()
    mock["estop"].lower()
    host.grab().save(str(Path(__file__).parent / "preview_reject_modal.png"))


# ------------------------------------------------- 方案C 居中置顶·手动关闭
class RejectDialog(QWidget):
    """居中置顶、不自动消失、必须手动关；弹窗内含急停；重复拒绝合并。"""

    def __init__(self, gate: str, reason: str, count: int = 1):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background:{AT.T('panel')}; border:1px solid {AT.T('bad')};")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        # 标题栏（模拟：左标题 + 右 ✕）
        bar = QWidget()
        bar.setStyleSheet(
            f"background:{AT.T('bad')}; border:none;")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(12, 6, 8, 6)
        cnt = "" if count <= 1 else f"（{count} 次，已合并）"
        t = QLabel(f"⛔ {gate} 被拒{cnt}")
        t.setStyleSheet(f"color:white; font-weight:700; font-size:13px;"
                        f"border:none; background:transparent;")
        x = QLabel("✕")
        x.setStyleSheet(f"color:white; font-weight:700; border:none;"
                        f"background:transparent;")
        bh.addWidget(t, 1)
        bh.addWidget(x)
        v.addWidget(bar)
        # 正文
        body = QWidget()
        body.setStyleSheet("border:none;")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(14, 10, 14, 10)
        bv.setSpacing(8)
        lab = QLabel(reason)
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color:{AT.T('text')}; font-size:12.5px;"
                          f"border:none; background:transparent;")
        lab.setFixedWidth(360)
        bv.addWidget(lab)
        note = QLabel("此弹窗不会自动消失；期间主窗仍可操作（急停/复位不受影响）。\n"
                      "该拒绝已同时写入「控制操作日志」与 safety 取证日志。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{AT.T('muted')}; font-size:11px;"
                           f"border:none; background:transparent;")
        bv.addWidget(note)
        # 按钮行：急停（左，红） + 知道了（右）
        btns = QWidget()
        btns.setStyleSheet("border:none;")
        bh2 = QHBoxLayout(btns)
        bh2.setContentsMargins(14, 0, 14, 12)
        bh2.setSpacing(10)
        estop = QPushButton("⛔ 急停")
        estop.setStyleSheet(
            f"color:white; background:{AT.T('bad')}; font-weight:700;"
            f"border:none; border-radius:5px; padding:7px 16px;")
        know = QPushButton("知道了")
        know.setStyleSheet(
            f"color:{AT.T('text')}; background:{AT.T('input')}; font-weight:600;"
            f"border:1px solid {AT.T('input_line')}; border-radius:5px;"
            f"padding:7px 22px;")
        bh2.addWidget(estop)
        bh2.addStretch(1)
        bh2.addWidget(know)
        bv.addWidget(btns)
        v.addWidget(body)
        self.adjustSize()


def render_centered() -> None:
    host = QWidget()
    host.setStyleSheet(f"background:{AT.T('bg')};")
    host.setFixedSize(W, H)
    build_mock_window(host)   # 无遮罩：主窗按钮保持可点
    dlg = RejectDialog("🪢 一键紧绳", REASON + "\n⚠ 3 秒内第 2 次触发：张力控制 无新鲜张力数据",
                       count=2)
    dlg.setParent(host)
    dlg.move((W - dlg.width()) // 2, (H - dlg.height()) // 2 - 20)
    dlg.raise_()
    host.grab().save(str(Path(__file__).parent / "preview_reject_centered.png"))


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(app.font())
    render_toast()
    render_modal()
    render_centered()


if __name__ == "__main__":
    main()
