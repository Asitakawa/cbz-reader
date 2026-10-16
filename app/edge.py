"""屏幕边缘小窗（贴边面板）：收起贴边、碰边滑出、常驻置顶、伪装时自动隐身。"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QPoint,
                            QPropertyAnimation, QRect, Qt, QTimer, Signal)
from PySide6.QtGui import QCursor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from .cbr import book_key
from .store import COVER_DIR, STORE
from .theme import ACCENT

GRIP_W = 8          # 贴边细缝宽度
STRIP_W = 56        # 封面条宽度
BODY_W = 208        # 展开详情宽度
CARD_W = GRIP_W + STRIP_W + BODY_W
PANEL_H = 430
COVER_W, COVER_H = 44, 62
VBAR_H = 168
BAR_W = 184


class _ClickStrip(QWidget):
    """封面条（可点击）。"""

    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class EdgePanel(QWidget):
    """边缘小窗：右侧/左侧贴边，鼠标靠近滑出。"""

    open_book = Signal(str, str, str)
    show_main = Signal()
    state_changed = Signal(bool)        # 启用状态变化

    def __init__(self, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("EdgePanel")

        self.side = STORE.cfg("edge.side", "right")          # right | left
        self.shape = STORE.cfg("edge.shape", "strip")        # strip | sliver
        self.auto_peek = bool(STORE.cfg("edge.auto_peek", True))
        self.expanded = False
        self.suspended = False
        self._book: dict | None = None
        self._order: QHBoxLayout | None = None
        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setDuration(190)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        # ---------------- 卡片 ----------------
        self.card = QFrame(self)
        self.card.setObjectName("EdgeCard")
        self.card.setFixedSize(CARD_W, PANEL_H)

        self.grip = QFrame(self.card)
        self.grip.setObjectName("EdgeGrip")
        self.grip.setFixedWidth(GRIP_W)

        self.strip = _ClickStrip(self.card)
        self.strip.setFixedWidth(STRIP_W)
        self.strip.setCursor(Qt.PointingHandCursor)
        self.strip.setToolTip("点击继续阅读")
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(0, 10, 0, 10)
        sl.setSpacing(8)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#E9ECF0;border-radius:6px;color:#9AA2AC;font-size:10px;")
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.v_track = QFrame()
        self.v_track.setFixedSize(5, VBAR_H)
        self.v_track.setStyleSheet("background:#E3E6EA;border-radius:2px;")
        self.v_track.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.v_fill = QFrame(self.v_track)
        self.v_fill.setGeometry(0, VBAR_H, 5, 0)
        self.v_fill.setStyleSheet(f"background:{ACCENT};border-radius:2px;")
        sl.addWidget(self.cover, 0, Qt.AlignHCenter)
        sl.addWidget(self.v_track, 0, Qt.AlignHCenter)
        sl.addStretch(1)

        self.body = QWidget(self.card)
        self.body.setFixedWidth(BODY_W)
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(2, 12, 14, 12)
        bl.setSpacing(7)

        self.lbl_name = QLabel("还没有阅读记录")
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setFixedHeight(34)
        self.lbl_name.setStyleSheet("color:#1B1E23;font-size:12px;font-weight:700;")
        self.lbl_page = QLabel("未开始阅读")
        self.lbl_page.setStyleSheet("color:#71787F;font-size:11px;")
        self.track = QFrame()
        self.track.setFixedSize(BAR_W, 4)
        self.track.setStyleSheet("background:#E3E6EA;border-radius:2px;")
        self.fill = QFrame(self.track)
        self.fill.setGeometry(0, 0, 0, 4)
        self.fill.setStyleSheet(f"background:{ACCENT};border-radius:2px;")

        self.btn_resume = QPushButton("继续阅读")
        self.btn_resume.setObjectName("Primary")
        self.btn_shelf = QPushButton("打开书架")
        self.btn_shelf.setObjectName("Ghost")
        self.btn_fold = QPushButton("收起")
        self.btn_fold.setObjectName("Ghost")
        for b in (self.btn_resume, self.btn_shelf, self.btn_fold):
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(28)
        self.lbl_hint = QLabel("鼠标离开自动收起")
        self.lbl_hint.setStyleSheet("color:#A2A9B2;font-size:10px;")

        self.lbl_recent = QLabel("最近在读")
        self.lbl_recent.setStyleSheet("color:#8B93A1;font-size:10px;")
        self.recent_box = QWidget()
        self.recent_lay = QVBoxLayout(self.recent_box)
        self.recent_lay.setContentsMargins(0, 0, 0, 0)
        self.recent_lay.setSpacing(1)

        bl.addWidget(self.lbl_name)
        bl.addWidget(self.lbl_page)
        bl.addWidget(self.track)
        bl.addSpacing(2)
        bl.addWidget(self.btn_resume)
        bl.addWidget(self.btn_shelf)
        bl.addWidget(self.btn_fold)
        bl.addSpacing(6)
        bl.addWidget(self.lbl_recent)
        bl.addWidget(self.recent_box)
        bl.addWidget(self.lbl_hint)
        bl.addStretch(1)

        self._apply_side()

        self.btn_resume.clicked.connect(self._resume)
        self.btn_shelf.clicked.connect(self.show_main)
        self.btn_fold.clicked.connect(self.collapse)
        self.strip.clicked.connect(self._strip_click)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setDuration(190)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        self._poll = QTimer(self)
        self._poll.setInterval(130)
        self._poll.timeout.connect(self._tick)
        self._fold_timer = QTimer(self)
        self._fold_timer.setSingleShot(True)
        self._fold_timer.setInterval(950)
        self._fold_timer.timeout.connect(self.collapse)

    # ================= 布局 / 样式 =================
    def _apply_side(self):
        self.anim_stop()
        if self._order is None:
            self._order = QHBoxLayout(self.card)
            self._order.setContentsMargins(0, 0, 0, 0)
            self._order.setSpacing(0)
        while self._order.count():          # 只摘除，不销毁控件
            self._order.takeAt(0)
        seq = (self.grip, self.strip, self.body) if self.side == "right" \
            else (self.body, self.strip, self.grip)
        for wdg in seq:
            self._order.addWidget(wdg)

        outer = "left" if self.side == "right" else "right"
        self.card.setStyleSheet(
            "#EdgeCard{background:rgba(255,255,255,248);border:1px solid #E3E6EA;"
            "border-radius:14px;}"
            f"#EdgeGrip{{background:{ACCENT};border-top-{outer}-radius:6px;"
            f"border-bottom-{outer}-radius:6px;}}")
        self.expanded = False
        self.strip.setVisible(self.shape == "strip")
        self.resize(self.collapsed_w(), PANEL_H)
        self._place()

    def collapsed_w(self) -> int:
        return STRIP_W if self.shape == "strip" else GRIP_W

    def resizeEvent(self, e):
        self._place()
        super().resizeEvent(e)

    def _place(self):
        w = self.width()
        self.card.move(0 if self.side == "right" else w - CARD_W, 0)

    # ================= 屏幕定位 =================
    def _screen(self):
        scr = QGuiApplication.screenAt(self.frameGeometry().center()) \
            or QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def _geo_for(self, width: int) -> QRect:
        scr = self._screen()
        y = scr.y() + max(0, (scr.height() - PANEL_H) // 2)
        x = scr.x() + scr.width() - width if self.side == "right" else scr.x()
        return QRect(x, y, width, PANEL_H)

    # ================= 显示 / 挂起 =================
    def start(self):
        if self.suspended:
            return
        self.anim_stop()          # 关键：停掉未完成的动画，否则它会覆盖新几何
        self.strip.setVisible(self.shape == "strip")
        self.expanded = False
        self._place()
        self.setGeometry(self._geo_for(self.collapsed_w()))
        self.show()
        self._poll.start()

    def suspend(self, on: bool):
        """伪装 / 全屏时挂起：彻底隐藏，避免穿帮。"""
        self.suspended = on
        if on:
            self._poll.stop()
            self._fold_timer.stop()
            self.hide()
        else:
            self.start()

    def shutdown(self):
        self._poll.stop()
        self._fold_timer.stop()
        self.hide()
        self.close()

    # ================= 展开 / 收起 =================
    def expand(self):
        if self.suspended or self.expanded:
            return
        self.strip.setVisible(True)
        self.expanded = True
        self._animate(self._geo_for(CARD_W))

    def collapse(self):
        if not self.expanded:
            return
        self.expanded = False
        self._fold_timer.stop()
        if self.shape == "sliver":
            self.strip.setVisible(False)
        self._animate(self._geo_for(self.collapsed_w()))

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    def _animate(self, target: QRect):
        self.anim.stop()
        self.anim.setStartValue(self.geometry())
        self.anim.setEndValue(target)
        self.anim.start()

    def anim_stop(self):
        """立即结束动画并把几何落定到动画目标值。"""
        if self.anim.state() == QAbstractAnimation.State.Running:
            to = self.anim.endValue()
            self.anim.stop()
            if to:
                self.setGeometry(to)
        else:
            self.anim.stop()

    def set_shape(self, shape: str):
        self.shape = shape
        STORE.set_cfg("edge.shape", shape)
        self.strip.setVisible(True)
        self.expanded = True
        self.collapse()

    def set_side(self, side: str):
        self.side = side
        STORE.set_cfg("edge.side", side)
        self._apply_side()
        if self.isVisible():
            self.start()

    def set_auto_peek(self, on: bool):
        self.auto_peek = bool(on)
        STORE.set_cfg("edge.auto_peek", self.auto_peek)

    # ================= 数据同步 =================
    def set_book(self, path: str, name: str, key: str = ""):
        key = key or book_key(path)
        self._book = {"path": path, "name": name, "key": key}
        self.lbl_name.setText(name)
        self.lbl_name.setToolTip(path)
        self.btn_resume.setText("继续阅读")
        self._load_cover(key, path)
        self.set_progress(0, 0)

    def set_progress(self, page: int, total: int):
        ratio = 0.0 if not total else min(1.0, (page + 1) / total)
        self.v_fill.setGeometry(0, int(VBAR_H * (1 - ratio)), 5, max(0, int(VBAR_H * ratio)))
        self.fill.setFixedWidth(int(BAR_W * ratio) if total else 0)
        self.fill.setGeometry(0, 0, int(BAR_W * ratio) if total else 0, 4)
        self.lbl_page.setText(f"第 {page + 1} / {total} 页" if total else "未开始阅读")

    def set_recent(self, h: dict | None):
        if not h:
            self._book = None
            self.lbl_name.setText("还没有阅读记录")
            self.lbl_page.setText("把 .cbz 拖进窗口即可导入")
            self.btn_resume.setText("打开书架")
            self.v_fill.setGeometry(0, VBAR_H, 5, 0)
            self.fill.setGeometry(0, 0, 0, 4)
            self.cover.setPixmap(QPixmap())
            self.cover.setText("空")
            return
        self.set_book(h.get("path", ""), h.get("name", ""), h.get("key", ""))
        self.set_progress(int(h.get("page", 0) or 0), int(h.get("total", 0) or 0))

    def set_recent_list(self, items: list[dict]):
        """最近在读快捷列表（最多 3 条）。"""
        while self.recent_lay.count():
            it = self.recent_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        rows = [h for h in (items or []) if h.get("path")][:3]
        self.lbl_recent.setVisible(bool(rows))
        self.recent_box.setVisible(bool(rows))
        for h in rows:
            total = h.get("total", 0) or 0
            pos = f"{int(h.get('page', 0) or 0) + 1}/{total}" if total else "未读"
            name = h.get("name", "")
            b = QPushButton(f"{name[:16]}   {pos}")
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(22)
            b.setToolTip(h.get("path", ""))
            b.setStyleSheet(
                "QPushButton{background:transparent;border:none;color:#3A4149;"
                "font-size:11px;text-align:left;padding:0 2px;}"
                f"QPushButton:hover{{color:{ACCENT};background:#F0F4FD;border-radius:4px;}}")
            b.clicked.connect(lambda _=False, p=h.get("path", ""), n=name,
                              k=h.get("key", ""): self.open_book.emit(p, n, k))
            self.recent_lay.addWidget(b)

    def recent_count(self) -> int:
        return self.recent_lay.count()

    def _load_cover(self, key: str, path: str):
        c = COVER_DIR / f"{key}_420.jpg"
        pm = QPixmap(str(c)) if c.exists() else QPixmap()
        if pm.isNull():
            self.cover.setPixmap(QPixmap())
            self.cover.setText("载入")
            from .tasks import ASYNC
            ASYNC.cover(path)
        else:
            self.apply_cover_pixmap(pm)

    def apply_cover(self, key: str, cover_path: str):
        if self._book and self._book.get("key") == key:
            self.apply_cover_pixmap(QPixmap(cover_path))

    def apply_cover_pixmap(self, pm: QPixmap):
        if pm.isNull():
            return
        self.cover.setText("")
        self.cover.setPixmap(pm.scaled(COVER_W, COVER_H, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))

    # ================= 交互 =================
    def _strip_click(self):
        self._resume()

    def _resume(self):
        if self._book and self._book.get("path"):
            self.open_book.emit(self._book["path"], self._book["name"], self._book["key"])
            self.collapse()
        else:
            self.show_main.emit()

    def _menu(self, pos: QPoint):
        m = QMenu(self)
        a_fold = m.addAction("收起")
        a_side = m.addAction("停靠到左侧" if self.side == "right" else "停靠到右侧")
        a_shape = m.addAction("改为细缝贴边" if self.shape == "strip" else "改为封面条")
        a_peek = m.addAction("边缘感应：开" if self.auto_peek else "边缘感应：关")
        m.addSeparator()
        a_close = m.addAction("关闭边缘小窗")
        chosen = m.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == a_fold:
            self.collapse()
        elif chosen == a_side:
            self.set_side("left" if self.side == "right" else "right")
        elif chosen == a_shape:
            self.set_shape("sliver" if self.shape == "strip" else "strip")
        elif chosen == a_peek:
            self.set_auto_peek(not self.auto_peek)
        elif chosen == a_close:
            STORE.set_cfg("edge.enabled", False)
            STORE.save_config()
            self.suspend(True)
            self.state_changed.emit(False)

    # ================= 边缘感应 =================
    def _tick(self):
        if self.suspended or not self.isVisible():
            return
        scr = self._screen()
        g = self.geometry()
        cur = QCursor.pos()
        band = 4
        on_edge = (cur.x() >= scr.x() + scr.width() - band if self.side == "right"
                   else cur.x() <= scr.x() + band)
        in_range = g.y() - 6 <= cur.y() <= g.y() + g.height() + 6
        inside = g.adjusted(-10, -10, 10, 10).contains(cur)

        if not self.expanded:
            if inside or (self.auto_peek and on_edge and in_range):
                self.expand()
            return
        if inside:
            self._fold_timer.stop()
        elif not self._fold_timer.isActive():
            self._fold_timer.start()
