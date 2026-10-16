"""无边框窗口基类：自由拖动、八向缩放、最大化/还原、透明度、圆角。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

MARGIN = 7          # 可拖拽缩放边框宽度
MIN_W, MIN_H = 860, 560

_EDGE_CURSOR = {
    0b0001: Qt.SizeHorCursor,
    0b0010: Qt.SizeHorCursor,
    0b0100: Qt.SizeVerCursor,
    0b1000: Qt.SizeVerCursor,
    0b0101: Qt.SizeFDiagCursor,
    0b1010: Qt.SizeFDiagCursor,
    0b0110: Qt.SizeBDiagCursor,
    0b1001: Qt.SizeBDiagCursor,
}


class TitleBar(QWidget):
    """自绘标题栏：拖动移动窗口、双击最大化。"""

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(44)
        self._drag_offset: QPoint | None = None
        self._press_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(10)

        self.icon = QLabel("📚")
        self.icon.setStyleSheet("font-size:15px;")
        lay.addWidget(self.icon)

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("AppTitle")
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setObjectName("AppSub")
        box.addWidget(self.lbl_title)
        box.addWidget(self.lbl_sub)
        lay.addLayout(box)
        lay.addStretch(1)

        self.btn_min = self._mk("—", "TitleBtn", "最小化")
        self.btn_max = self._mk("□", "TitleBtn", "最大化 / 还原")
        self.btn_cam = self._mk("伪装", "TitleBtn", "桌面伪装（热键可切换）", 44)
        self.btn_hide = self._mk("隐藏", "TitleBtn", "隐藏窗口（热键可切换）", 44)
        self.btn_close = self._mk("✕", "TitleBtn", "关闭")
        for b in (self.btn_cam, self.btn_hide, self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

        self.btn_min.clicked.connect(self.minimize_clicked)
        self.btn_max.clicked.connect(self.maximize_clicked)
        self.btn_close.clicked.connect(self.close_clicked)

    def _mk(self, text: str, obj: str, tip: str, w: int = 34) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("CloseBtn" if "CloseBtn" in obj else obj.split()[0])
        b.setFixedSize(w, 28)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        if w > 34:
            b.setStyleSheet("font-size:11px;")
        return b

    def set_meta(self, title: str | None = None, subtitle: str | None = None):
        if title is not None:
            self.lbl_title.setText(title)
        if subtitle is not None:
            self.lbl_sub.setText(subtitle)

    def set_maximized(self, is_max: bool):
        self.btn_max.setText("❐" if is_max else "□")

    # ---------- 拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            win = self.window()
            if getattr(win, "is_maximized", False):
                self.maximize_clicked.emit()
                self._drag_offset = None
                return
            self._press_pos = e.globalPosition().toPoint()
            self._drag_offset = self._press_pos - win.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            win = self.window()
            if getattr(win, "is_maximized", False):
                return
            win.move(e.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self.btn_max.isEnabled():
            self.maximize_clicked.emit()
        super().mouseDoubleClickEvent(e)


class FramelessWindow(QWidget):
    """自定义无边框窗口。"""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_W, MIN_H)

        self.is_maximized = False
        self._edge = 0
        self._resize_geo0 = QRect()
        self._resize_pos0 = QPoint()
        self._normal_geo = None
        self._opacity = 1.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        outer.setSpacing(0)

        self.root = QFrame()
        self.root.setObjectName("Root")
        outer.addWidget(self.root)

        self.body = QVBoxLayout(self.root)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)

        self.title_bar = TitleBar(title, subtitle)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self.toggle_maximize)
        self.title_bar.close_clicked.connect(self.close)
        self.body.addWidget(self.title_bar)

        self.content = QWidget()
        self.content.setObjectName("Content")
        self.body.addWidget(self.content, 1)

    # ---------- 圆角 ----------
    def set_radius(self, r: int):
        self.root.setStyleSheet(f"#Root {{ border-radius: {r}px; }}")

    # ---------- 缩放 ----------
    def _edge_at(self, pos: QPoint) -> int:
        m = MARGIN + 1
        r = self.rect()
        if self.is_maximized:
            return 0
        left, right = pos.x() <= m, pos.x() >= r.width() - m
        top, bottom = pos.y() <= m, pos.y() >= r.height() - m
        return (1 if left else 2 if right else 0) | (4 if top else 8 if bottom else 0)

    def mouseMoveEvent(self, e):
        if self._edge:
            return
        if not (e.buttons() & Qt.LeftButton):
            code = self._edge_at(e.position().toPoint())
            self.setCursor(QCursor(_EDGE_CURSOR.get(code, Qt.ArrowCursor)))
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.is_maximized:
            code = self._edge_at(e.position().toPoint())
            if code:
                self._edge = code
                self._resize_geo0 = self.geometry()
                self._resize_pos0 = e.globalPosition().toPoint()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._edge:
            self._edge = 0
            self.setCursor(QCursor(Qt.ArrowCursor))
            self._emit_geometry_changed()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def event(self, ev):
        # 在窗口自身范围内拦截移动事件做缩放（子控件不占用边框区域）
        if ev.type() == QEvent.MouseMove and self._edge:
            g = self._resize_geo0
            d = ev.globalPosition().toPoint() - self._resize_pos0
            x, y, w, h = g.x(), g.y(), g.width(), g.height()
            if self._edge & 1:      # 左
                nw = max(MIN_W, w - d.x())
                x = g.x() + (w - nw)
                w = nw
            if self._edge & 2:      # 右
                w = max(MIN_W, w + d.x())
            if self._edge & 4:      # 上
                nh = max(MIN_H, h - d.y())
                y = g.y() + (h - nh)
                h = nh
            if self._edge & 8:      # 下
                h = max(MIN_H, h + d.y())
            self.setGeometry(x, y, w, h)
            return True
        if ev.type() == QEvent.Leave and not self._edge:
            self.setCursor(QCursor(Qt.ArrowCursor))
        return super().event(ev)

    def _emit_geometry_changed(self):
        pass

    # ---------- 最大化 ----------
    def toggle_maximize(self):
        if self.is_maximized:
            self.restore_window()
        else:
            self.maximize_window()

    def maximize_window(self):
        if self.is_maximized:
            return
        self._normal_geo = self.geometry()
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr:
            self.setGeometry(scr)
        self.is_maximized = True
        self.set_radius(0)
        self.title_bar.set_maximized(True)

    def restore_window(self):
        if not self.is_maximized:
            return
        self.is_maximized = False
        if self._normal_geo:
            self.setGeometry(self._normal_geo)
        self.set_radius(10)
        self.title_bar.set_maximized(False)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F11:
            self.toggle_maximize()
        elif e.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        super().keyPressEvent(e)

    # ---------- 透明度 ----------
    def set_window_opacity(self, v: float):
        self._opacity = max(0.4, min(1.0, float(v)))
        self.setWindowOpacity(self._opacity)

    # ---------- 几何持久化 ----------
    def geo_dict(self) -> dict:
        g = self._normal_geo or self.geometry()
        return {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}

    def restore_geometry(self, cfg: dict):
        try:
            w = max(MIN_W, int(cfg.get("w") or 1200))
            h = max(MIN_H, int(cfg.get("h") or 780))
            self.resize(w, h)
            x, y = cfg.get("x"), cfg.get("y")
            if x is None or y is None:
                if self.screen():
                    a = self.screen().availableGeometry()
                    self.move(a.center().x() - w // 2, max(a.top(), a.center().y() - h // 2))
            else:
                # 防止出现在屏幕外
                ok = False
                for s in self.screen().virtualSiblings() if self.screen() else []:
                    if s.availableGeometry().intersects(QRect(int(x), int(y), w, h)):
                        ok = True
                        break
                self.move(int(x), int(y)) if ok else self.move(120, 90)
        except Exception:
            pass


def vline() -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setStyleSheet("background:#E3E6EA;")
    return f


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    f = QFont()
    f.setPointSize(9)
    lbl.setFont(f)
    lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    return lbl
