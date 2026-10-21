"""屏幕边缘隐蔽式迷你阅读器。

收起时是一条 6px 细缝（或 40px 小封面条），鼠标碰到屏幕边缘/细缝即滑出一个小阅读窗：
直接渲染当前这一话的页面，滚轮或点击两侧翻页，鼠标离开自动缩回。
"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QPoint,
                            QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QVBoxLayout,
                               QWidget)

from .store import STORE
from .tasks import ASYNC
from . import theme

SLIVER_W = 6         # 细缝（最隐蔽）
STRIP_W = 40         # 小封面条
PEEK_W = 420         # 滑出后的阅读窗宽度
PEEK_MAX_H = 860
RADIUS = 12
CACHE_MAX = 6
BAR_H = 58


class _Canvas(QWidget):
    """绘制漫画页（等比适应窗口），并响应滚轮/点击/双击。"""

    wheeled = Signal(int)          # +1 下一页 / -1 上一页
    zoomed = Signal(int)           # Ctrl+滚轮：+1 放大 / -1 缩小
    tapped = Signal(int)           # -1 左 / 0 中 / +1 右
    dbl = Signal()

    def __init__(self, panel: "EdgePanel"):
        super().__init__()
        self.panel = panel
        self._pm: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._hint = ""
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)

    def set_pixmap(self, pm: QPixmap | None):
        self._pm = pm
        self._rescale()
        self.update()

    def set_hint(self, text: str):
        self._hint = text
        self.update()

    def _rescale(self):
        if self._pm is None or self._pm.isNull():
            self._scaled = None
            return
        # 按物理像素缩放，避免高 DPI 屏上再被放大一次导致发虚
        dpr = self.devicePixelRatioF() or 1.0
        target = QSize(int(self.width() * dpr), int(self.height() * dpr))
        pm = self._pm.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self._scaled = pm

    def resizeEvent(self, e):
        self._rescale()
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.c("overlay")))
        if self._scaled is not None and not self._scaled.isNull():
            dpr = self._scaled.devicePixelRatio() or 1.0
            lw, lh = self._scaled.width() / dpr, self._scaled.height() / dpr
            p.drawPixmap(int((self.width() - lw) / 2), int((self.height() - lh) / 2),
                         self._scaled)
        elif self._hint:
            p.setPen(QColor(theme.c("overlay_sub")))
            f = p.font()
            f.setPointSize(10)
            p.setFont(f)
            p.drawText(self.rect().adjusted(24, 24, -24, -24),
                       Qt.AlignCenter | Qt.TextWordWrap, self._hint)
        p.end()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:      # Ctrl+滚轮 = 调整阅读窗宽度
            self.zoomed.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.ShiftModifier or abs(e.angleDelta().x()) > abs(dy):
            step = -1 if e.angleDelta().x() > 0 else 1
        else:
            step = 1 if dy < 0 else -1
        self.wheeled.emit(step)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            x = e.position().x()
            third = self.width() / 3
            self.tapped.emit(-1 if x < third else (1 if x > 2 * third else 0))
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self.dbl.emit()
        e.accept()


def _picker_qss() -> str:
    """话数弹窗的深色浮层样式：文字/描边显式写死，避免被浅色主题的全局规则污染。"""
    return (
        "#PickerCard{background:%(bg)s;border:1px solid %(line)s;"
        "border-radius:%(r)s;}"
        "#PickerTitle{color:%(sub)s;font-size:%(f10)s;}"
        "#PickerList{background:transparent;border:none;outline:none;"
        "color:%(text)s;font-size:%(f12)s;}"
        "#PickerList::item{color:%(text)s;background:transparent;border:none;"
        "padding:5px 7px;border-radius:%(r1)s;}"
        "#PickerList::item:selected{background:%(soft)s;color:%(text)s;border:none;}"
        "#PickerList::item:hover{background:%(hover)s;color:%(text)s;border:none;}"
        "#PickerList QScrollBar:vertical{background:%(bg)s;width:8px;"
        "margin:2px 0 2px 2px;border-radius:4px;}"
        "#PickerList QScrollBar::handle:vertical{background:%(line)s;"
        "border-radius:4px;min-height:24px;}"
        "#PickerList QScrollBar::handle:vertical:hover{background:%(sub)s;}"
        "#PickerList QScrollBar::add-line,#PickerList QScrollBar::sub-line{height:0;}"
        "#PickerList QScrollBar::add-page,#PickerList QScrollBar::sub-page{"
        "background:transparent;}"
    ) % {
        "bg": theme.c("overlay"), "line": theme.c("overlay_line"),
        "sub": theme.c("overlay_sub"), "text": theme.c("overlay_text"),
        "soft": theme.mix(theme.c("overlay"), theme.c("accent"), 0.30),
        "hover": theme.c("overlay2"), "r": theme.c("r3"),
        "r1": theme.c("r1"), "f10": theme.px(10), "f12": theme.px(12),
    }


class _ChapterPicker(QWidget):
    """选择话数的弹出列表（贴在迷你阅读器内部）。"""

    picked = Signal(str)

    def __init__(self, chapters: list[dict], current: str, width: int):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(width)
        h = min(400, 46 + max(1, len(chapters)) * 26)
        self.setFixedHeight(h)

        card = QFrame(self)
        card.setObjectName("PickerCard")
        card.setGeometry(0, 0, width, h)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        t = QLabel(f"共 {len(chapters)} 话")
        t.setObjectName("PickerTitle")
        lay.addWidget(t)
        self.list = QListWidget()
        self.list.setObjectName("PickerList")
        self.list.setFrameShape(QFrame.NoFrame)
        for i, ch in enumerate(chapters, 1):
            it = QListWidgetItem(f"{i}. {ch.get('name', '')}")
            it.setData(Qt.UserRole, ch.get("id", ""))
            # 显式设前景色：全局 QSS 的 QListWidget::item 是浅色主题的深色文字，
            # 不显式覆盖的话在深色弹窗里会「看不见字」。
            it.setForeground(QColor("#E8EBF0"))
            self.list.addItem(it)
            if ch.get("id") == current:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it)
        lay.addWidget(self.list, 1)
        self.list.itemClicked.connect(self._pick)
        self.list.itemActivated.connect(self._pick)
        self.setStyleSheet(_picker_qss())
        self._apply_item_colors()

    def _apply_item_colors(self):
        # 显式设前景色：全局 QSS 的 QListWidget::item 是浅色主题的深色文字，
        # 不覆盖的话在深色弹窗里会「看不见字」。
        for i in range(self.list.count()):
            self.list.item(i).setForeground(QColor(theme.c("overlay_text")))

    def _pick(self, item):
        self.picked.emit(item.data(Qt.UserRole))
        self.close()


class EdgePanel(QWidget):
    """贴边迷你阅读器。"""

    show_main = Signal()
    open_in_main = Signal()                      # 在主窗口打开当前页
    open_chapter = Signal(str, str, str)         # 空态最近列表：path, name, cid
    progress_changed = Signal(str, int, int)     # cid, page, total
    state_changed = Signal(bool)                 # 启用状态变化

    def __init__(self, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("EdgePanel")

        self.side = STORE.cfg("edge.side", "right")
        self.shape = STORE.cfg("edge.shape", "sliver")
        self.auto_peek = bool(STORE.cfg("edge.auto_peek", True))
        self.expanded = False
        self.suspended = False
        self.pinned = False          # 钉住：不自动缩回（截图/调试用）

        self.width_target = int(STORE.cfg("edge.width", PEEK_W) or PEEK_W)
        self._page_h = 0            # 面板高度跟随当前页比例
        self._chapters: list[dict] = []
        self._cid = ""
        self._path = ""
        self._name = ""
        self._book = ""
        self._page = 0
        self._total = 0
        self._cache: dict[int, QPixmap] = {}
        self._pending: set[int] = set()
        self._job_key = ""

        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self._on_anim_done)

        # ---------------- 卡片 ----------------
        self.card = QFrame(self)
        self.card.setObjectName("MiniCard")
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.canvas = _Canvas(self)
        lay.addWidget(self.canvas, 1)

        # 底部信息条（悬停时出现，自动隐藏）
        self.bar = QFrame(self)
        self.bar.setObjectName("MiniBar")
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(9, 6, 9, 6)
        bl.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.lbl_title = QLabel("")
        theme.style(self.lbl_title,
                    "color:$overlay_text;font-size:$f11;font-weight:600;")
        self.lbl_page = QLabel("0 / 0")
        theme.style(self.lbl_page, "color:$overlay_sub;font-size:$f11;")
        self.btn_chapters = QPushButton("话数")
        self.btn_next_ch = QPushButton("下一话")
        self.btn_help = QPushButton("?")
        self.btn_prev = QPushButton("‹")
        self.btn_next = QPushButton("›")
        self.btn_open = QPushButton("打开")
        self.btn_fold = QPushButton("收起")
        for b in (self.btn_chapters, self.btn_next_ch, self.btn_prev, self.btn_next,
                  self.btn_help, self.btn_open, self.btn_fold):
            b.setObjectName("MiniBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(22)
        self.btn_prev.setFixedWidth(24)
        self.btn_next.setFixedWidth(24)
        self.btn_next_ch.setFixedWidth(56)
        self.btn_next_ch.hide()
        self.btn_help.setFixedWidth(22)
        self.btn_help.setToolTip("操作提示")
        top.addWidget(self.lbl_title, 1)
        bottom.addWidget(self.btn_chapters)
        bottom.addWidget(self.btn_next_ch)
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.lbl_page)
        bottom.addWidget(self.btn_next)
        bottom.addWidget(self.btn_help)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_open)
        bottom.addWidget(self.btn_fold)
        bl.addLayout(top)
        bl.addLayout(bottom)
        self.bar.hide()

        # 操作提示卡：第一次滑出时出现，之后可从「?」或右键再次查看
        self.coach = QFrame(self)
        self.coach.setObjectName("MiniCoach")
        cl = QVBoxLayout(self.coach)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(6)
        ct = QLabel("这样操作")
        ct.setObjectName("CoachTitle")
        ctext = QLabel("滚轮 / 点页面左右两侧：翻页\n"
                       "双击页面：回主窗口接着看\n"
                       "「话数」切话 · 「下一话」跳下一话 · 右键更多")
        ctext.setObjectName("CoachText")
        ctext.setWordWrap(True)
        cbtn = QPushButton("知道了")
        cbtn.setObjectName("MiniBtn")
        cbtn.setFixedHeight(24)
        cbtn.clicked.connect(self._hide_coach)
        cl.addWidget(ct)
        cl.addWidget(ctext)
        cl.addWidget(cbtn, 0, Qt.AlignRight)
        self.coach.hide()

        # 空态：最近在读列表
        self.empty = QWidget(self)
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(16, 16, 16, 16)
        el.setSpacing(6)
        t = QLabel("还没有正在读的漫画")
        theme.style(t, "color:$overlay_text;font-size:$f12;font-weight:600;")
        el.addWidget(t)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        el.addLayout(self.recent_box)
        el.addStretch(1)
        self.empty.hide()

        self.btn_chapters.clicked.connect(self._choose_chapter)
        self.btn_next_ch.clicked.connect(self._go_next_chapter)
        self.btn_help.clicked.connect(lambda: self._show_coach(manual=True))
        self.btn_chapters.hide()
        self.btn_prev.clicked.connect(lambda: self.turn(-1))
        self.btn_next.clicked.connect(lambda: self.turn(1))
        self.btn_open.clicked.connect(self.open_in_main)
        self.btn_fold.clicked.connect(self.collapse)
        self.canvas.wheeled.connect(self.turn)
        self.canvas.zoomed.connect(self.resize_step)
        self.canvas.tapped.connect(lambda d: self.turn(d) if d else None)
        self.canvas.dbl.connect(self.open_in_main)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        ASYNC.sig.page.connect(self._on_page)

        self._poll = QTimer(self)
        self._poll.setInterval(120)
        self._poll.timeout.connect(self._tick)
        self._coach_timer = QTimer(self)
        self._coach_timer.setSingleShot(True)
        self._coach_timer.setInterval(9000)
        self._coach_timer.timeout.connect(self._hide_coach)

        self._apply_style()
        theme.bus.changed.connect(self._apply_style)
        self.resize(self.collapsed_w(), self.peek_h())

    # ================= 宽度 / 几何 =================
    def collapsed_w(self) -> int:
        return STRIP_W if self.shape == "strip" else SLIVER_W

    def _clamp_w(self, w: int) -> int:
        scr = self._screen()
        return max(280, min(int(w), min(760, scr.width() - 80), ))

    def peek_w(self) -> int:
        self.width_target = self._clamp_w(self.width_target)
        return self.width_target

    def resize_step(self, step: int):
        """Ctrl+滚轮调整滑出后的阅读窗宽度。"""
        target = self._clamp_w(self.width_target + step * 40)
        if target == self.width_target:
            return
        self.width_target = target
        STORE.set_cfg("edge.width", target)
        STORE.save_config()
        self._cache.clear()
        self._pending.clear()
        if self.expanded:
            self._page_h = 0
            self._animate(self._geo_for(target))
            self._load_page(self._page, force=True)
        self._layout_children()

    def peek_h(self) -> int:
        scr = self._screen()
        return int(min(PEEK_MAX_H, scr.height() * 0.86))

    def _screen(self) -> QRect:
        scr = (QGuiApplication.screenAt(self.frameGeometry().center())
               or QGuiApplication.screenAt(QCursor.pos())
               or QGuiApplication.primaryScreen())
        return scr.availableGeometry()

    def _geo_for(self, width: int) -> QRect:
        scr = self._screen()
        h = self._page_h or self.peek_h()
        y = scr.y() + max(0, (scr.height() - h) // 2)
        x = scr.x() + scr.width() - width if self.side == "right" else scr.x()
        return QRect(x, y, width, h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_children()
        self._fit_title()

    def _layout_children(self):
        w, h = self.width(), self.height()
        self.card.setGeometry(0, 0, w, h)
        self.bar.setGeometry(8, h - BAR_H - 8, w - 16, BAR_H)
        coach_h = int(104 * theme.current()["scale"])
        self.coach.setGeometry(12, max(12, h - BAR_H - 18 - coach_h), w - 24, coach_h)
        self.empty.setGeometry(0, 0, w, h)

    def paintEvent(self, e):
        """收起状态：贴边一条窄条（中间一段强调色，提示可滑出）。"""
        if self.expanded:
            return
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.c("overlay")))
        edge_x = w - 3 if self.side == "right" else 0
        p.fillRect(QRect(edge_x, 0, 3, h), QColor(theme.c("overlay_line")))
        mid = h // 2
        p.fillRect(QRect(edge_x, mid - 34, 3, 68), QColor(theme.c("accent")))
        if self.shape == "strip":
            # 窄条形态：画一条竖向进度
            ratio = (self._page + 1) / self._total if self._total else 0
            bh = int((h - 40) * min(1.0, ratio))
            p.fillRect(QRect(edge_x, h - 20 - bh, 3, bh), QColor(theme.c("ok")))
        p.end()

    def _apply_style(self):
        r = theme.radius_px() + 2
        self.setStyleSheet(
            "#MiniCard{background:%(bg)s;border-radius:%(r)dpx;"
            "border:1px solid %(line)s;}"
            "#MiniBar{background:%(bar)s;border:1px solid %(line)s;"
            "border-radius:%(r2)s;}"
            "#MiniBtn{background:%(btn)s;color:%(text)s;"
            "border:none;border-radius:%(r1)s;font-size:%(f11)s;padding:0 7px;}"
            "#MiniBtn:hover{background:%(btn2)s;}"
            "#MiniBtn:disabled{background:%(btn)s;color:%(line)s;}"
            "#MiniCoach{background:%(coach)s;border:1px solid %(line)s;"
            "border-radius:%(r2)s;}"
            "#CoachTitle{color:%(text)s;font-size:%(f11)s;font-weight:600;}"
            "#CoachText{color:%(sub)s;font-size:%(f10)s;}"
            "#MiniBtnLeft{background:%(btn)s;color:%(sub)s;border:none;"
            "border-radius:%(r1)s;font-size:%(f10)s;text-align:left;padding:0 8px;}"
            "#MiniBtnLeft:hover{background:%(btn2)s;color:%(text)s;}"
            % {
                "bg": theme.c("overlay"), "line": theme.c("overlay_line"),
                "bar": theme.mix(theme.c("overlay"), "#000000", 0.18),
                "coach": theme.mix(theme.c("overlay"), "#FFFFFF", 0.06),
                "btn": theme.mix(theme.c("overlay"), "#FFFFFF", 0.09),
                "btn2": theme.mix(theme.c("overlay"), "#FFFFFF", 0.18),
                "text": theme.c("overlay_text"), "sub": theme.c("overlay_sub"),
                "r": r, "r1": theme.c("r1"), "r2": theme.c("r2"),
                "f10": theme.px(10), "f11": theme.px(11),
            })
        self.update()

    # ================= 显示 / 挂起 =================
    def start(self):
        if self.suspended:
            return
        self.anim_stop()
        self.expanded = False
        self.bar.hide()
        self.card.hide()
        self.empty.setVisible(not self._cid)
        self.canvas.setVisible(bool(self._cid))
        self.card.setGeometry(0, 0, self.collapsed_w(), self.peek_h())
        self.setGeometry(self._geo_for(self.collapsed_w()))
        self.show()
        self.raise_()
        self._poll.start()
        self.update()

    def suspend(self, on: bool):
        self.suspended = on
        if on:
            self._poll.stop()
            self.hide()
        else:
            self.start()

    def shutdown(self):
        self._poll.stop()
        self.hide()
        self.close()

    # ================= 展开 / 收起 =================
    def expand(self):
        if self.suspended or self.expanded:
            return
        self.expanded = True
        self.card.show()
        self.empty.setVisible(not self._cid)
        self.canvas.setVisible(bool(self._cid))
        self._animate(self._geo_for(self.peek_w()))
        self._show_bar()
        if not bool(STORE.cfg("edge.coach_seen", False)):
            QTimer.singleShot(280, self._show_coach)
        if self._cid:
            self._load_page(self._page)

    def collapse(self):
        if not self.expanded:
            return
        self.expanded = False
        self.bar.hide()
        self.coach.hide()
        self._coach_timer.stop()
        self._animate(self._geo_for(self.collapsed_w()))
        if self._cid:
            STORE.touch_history(self._cid, self._name, self._page, self._total)
            STORE.save_all()
            self.progress_changed.emit(self._cid, self._page, self._total)

    def _on_anim_done(self):
        if not self.expanded:
            self.card.hide()
            self.update()

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    def pin(self, on: bool = True):
        self.pinned = bool(on)

    def _animate(self, target: QRect):
        self.anim.stop()
        self.anim.setStartValue(self.geometry())
        self.anim.setEndValue(target)
        self.anim.start()

    def anim_stop(self):
        if self.anim.state() == QAbstractAnimation.State.Running:
            to = self.anim.endValue()
            self.anim.stop()
            if to:
                self.setGeometry(to)
        else:
            self.anim.stop()

    # ================= 内容 =================
    def set_chapter(self, path: str, name: str, cid: str, book_title: str = "",
                    page: int = 0, total: int = 0):
        changed = cid != self._cid
        self._path, self._name, self._cid = path, name, cid
        self._book = book_title
        self._total = total or (STORE.progress(cid) or {}).get("total", 0) or 0
        self._page = max(0, min(int(page), max(0, self._total - 1))) if self._total else int(page)
        if changed:
            self._cache.clear()
            self._pending.clear()
        self._job_key = f"mini:{cid}"
        head = f"{book_title} · {name}" if book_title else name
        fm = self.lbl_title.fontMetrics()
        self.lbl_title.setText(fm.elidedText(head, Qt.ElideMiddle, 200))
        self.lbl_title.setToolTip(f"{head}\n第 {self._page + 1} 页")
        self._sync_page_label()
        self.empty.setVisible(not cid and self.expanded)
        self.canvas.setVisible(bool(cid))
        if cid and self.expanded:
            self._load_page(self._page)
        elif cid:
            self._load_page(self._page)      # 预解，滑出时零等待

    def set_progress(self, page: int, total: int):
        if not self._cid:
            return
        self._total = total or self._total
        self._page = max(0, min(int(page), max(0, self._total - 1))) if self._total else int(page)
        self._sync_page_label()
        if self.expanded:
            self._load_page(self._page)

    def set_chapters(self, chapters: list[dict], current: str = ""):
        """主窗口同步当前书的全部话数，供小窗内切换 / 接续下一话。"""
        self._chapters = list(chapters or [])
        self.btn_chapters.setVisible(len(self._chapters) > 1)
        self._sync_page_label()

    def _chapter_index(self) -> int:
        for i, ch in enumerate(self._chapters):
            if ch.get("id") == self._cid:
                return i
        return -1

    def neighbor_chapter(self, step: int) -> dict | None:
        """同一本书里相邻的一话（step=+1 下一话 / -1 上一话）。"""
        i = self._chapter_index()
        if i < 0:
            return None
        j = i + step
        return self._chapters[j] if 0 <= j < len(self._chapters) else None

    def _go_next_chapter(self):
        nxt = self.neighbor_chapter(1)
        if nxt:
            self._switch_chapter(nxt["id"], page=0)

    def _choose_chapter(self):
        if not self._chapters:
            return
        w = max(200, min(320, self.width() - 24))
        picker = _ChapterPicker(self._chapters, self._cid, w)
        picker.picked.connect(self._switch_chapter)
        bw = self.bar.width()
        px = self.bar.x() + (8 if self.side == "left" else bw - w - 8)
        py = self.bar.y() - picker.height() - 6
        picker.move(self.mapToGlobal(QPoint(max(8, px), max(8, py))))
        picker.show()
        self._picker = picker

    def _switch_chapter(self, cid: str, page: int | None = None, to_end: bool = False):
        ch = next((c for c in self._chapters if c.get("id") == cid), None)
        if not ch:
            return
        total = int((STORE.progress(cid) or {}).get("total", 0) or 0)
        if not total:
            try:
                from .cbr import ComicSource
                src = ComicSource(ch.get("path", ""))
                total = src.page_count
                src.close()
            except Exception:
                total = 0
        if to_end and total:
            page = total - 1
        elif page is None:
            page = int((STORE.progress(cid) or {}).get("page", 0) or 0)
        page = max(0, min(int(page or 0), total - 1)) if total else int(page or 0)
        book = (STORE.book(ch.get("book", "")) or {}).get("title", "")
        self.set_chapter(ch.get("path", ""), ch.get("name", ""), cid, book, page, total)
        STORE.touch_history(cid, ch.get("name", ""), page, total)
        STORE.save_all()
        self.progress_changed.emit(cid, page, total)
        self._show_bar()

    def _sync_page_label(self):
        self.lbl_page.setText(
            f"{self._page + 1} / {self._total}" if self._total else "—")
        self._sync_nav_buttons()
        self._fit_title()

    def _sync_nav_buttons(self):
        nxt = self.neighbor_chapter(1)
        self.btn_next.setText("›")
        self.btn_next.setFixedWidth(24)
        self.btn_next.setToolTip("下一页（滚轮 / 点击右侧；末页继续则进入下一话）")
        self.btn_prev.setText("‹")
        self.btn_prev.setFixedWidth(24)
        self.btn_prev.setToolTip("上一页（首页继续则回到上一话末页）")
        self.btn_next_ch.setVisible(len(self._chapters) > 1)
        self.btn_next_ch.setEnabled(bool(nxt))
        self.btn_next_ch.setToolTip(
            f"下一话 · {nxt.get('name', '')}" if nxt else "已经是最后一话")

    def _fit_title(self):
        head = f"{self._book} · {self._name}" if self._book else self._name
        # 两行布局：标题独占一行，宽度按面板宽度算
        avail = max(80, self.width() - 36)
        fm = self.lbl_title.fontMetrics()
        self.lbl_title.setText(fm.elidedText(head, Qt.ElideMiddle, avail))
        self.lbl_title.setToolTip(f"{head}\n第 {self._page + 1} / {self._total} 页")

    def current_chapter(self) -> dict:
        return {"path": self._path, "name": self._name, "cid": self._cid,
                "book": self._book, "page": self._page, "total": self._total}

    def turn(self, step: int):
        if not self._cid or step == 0:
            return
        target = self._page + step
        if step > 0 and self._total and target > self._total - 1:
            nxt = self.neighbor_chapter(1)
            if nxt:                     # 末页继续往后 → 自动进入下一话
                self._switch_chapter(nxt["id"], page=0)
                return
            target = self._total - 1
        elif step < 0 and target < 0:
            prv = self.neighbor_chapter(-1)
            if prv:                     # 首页继续往前 → 上一话最后一页
                self._switch_chapter(prv["id"], to_end=True)
                return
            target = 0
        if target == self._page:
            return
        self._page = target
        self._sync_page_label()
        self._load_page(target)
        STORE.touch_history(self._cid, self._name, self._page, self._total)
        self.progress_changed.emit(self._cid, self._page, self._total)

    # ---------- 页面解码 ----------
    def _display_size(self):
        dpr = self.devicePixelRatioF() or 1.0
        w = max(120, self.peek_w() - 2)
        h = max(120, self.peek_h() - 2)
        return (int(w * dpr), int(h * dpr))

    def _load_page(self, index: int, force: bool = False):
        if not self._cid:
            return
        pm = self._cache.get(index)
        if pm is not None and not force:
            self.canvas.set_pixmap(pm)
            self._prefetch(index)
            return
        self.canvas.set_pixmap(None)
        self.canvas.set_hint(f"载入第 {index + 1} 页…")
        if index in self._pending:
            return
        w, h = self._display_size()
        self._pending.add(index)
        ASYNC.page(self._path, self._job_key, index, w, h)
        self._prefetch(index)

    def _prefetch(self, index: int):
        w, h = self._display_size()
        for i in (index + 1, index - 1):
            if 0 <= i < (self._total or 10 ** 6) and i not in self._cache \
                    and i not in self._pending:
                self._pending.add(i)
                ASYNC.page(self._path, self._job_key, i, w, h)

    def _on_page(self, key: str, index: int, image):
        if not self._job_key or key != self._job_key:
            return
        self._pending.discard(index)
        if image is None or image.isNull():
            return
        pm = QPixmap.fromImage(image)
        self._cache[index] = pm
        while len(self._cache) > CACHE_MAX:
            far = max(self._cache, key=lambda i: abs(i - self._page))
            if far == self._page:
                break
            self._cache.pop(far, None)
        if index == self._page:
            self.canvas.set_pixmap(pm)
            self._fit_to_page(pm)

    def _fit_to_page(self, pm: QPixmap):
        """让面板高度贴合当前页比例，避免上下留黑边。"""
        if pm is None or pm.isNull() or pm.width() <= 0:
            return
        scr = self._screen()
        ratio = pm.height() / pm.width()
        h = int(self.peek_w() * ratio)
        h = max(140, min(h, int(scr.height() * 0.94)))
        if abs(h - self._page_h) <= 2:
            return
        self._page_h = h
        if self.expanded:
            w = self.peek_w()          # 用目标宽度，避免动画中途把宽度定小
            y = scr.y() + max(0, (scr.height() - h) // 2)
            x = scr.x() + scr.width() - w if self.side == "right" else scr.x()
            self._animate(QRect(x, y, w, h))
            self.bar.setGeometry(8, h - BAR_H - 8, w - 16, BAR_H)

    # ================= 底部信息条 =================
    def _show_bar(self):
        if not self.expanded:
            return
        self.bar.show()
        self._layout_children()

    def enterEvent(self, e):
        self._show_bar()
        super().enterEvent(e)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if self.expanded and not self.pinned:   # 鼠标离开立即缩回，不留延迟
            self.collapse()

    def mouseMoveEvent(self, e):
        self._show_bar()
        super().mouseMoveEvent(e)

    def _show_coach(self, manual: bool = False):
        if not self.expanded:
            return
        self.coach.show()
        self.coach.raise_()
        self._layout_children()
        self._coach_timer.start()
        if manual:
            self._show_bar()

    def _hide_coach(self):
        self._coach_timer.stop()
        self.coach.hide()
        if not bool(STORE.cfg("edge.coach_seen", False)):
            STORE.set_cfg("edge.coach_seen", True)
            STORE.save_config()

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
        in_range = g.y() - 8 <= cur.y() <= g.y() + g.height() + 8
        inside = g.adjusted(-10, -10, 10, 10).contains(cur)

        if not self.expanded:
            if inside or (self.auto_peek and on_edge and in_range):
                self.expand()
            return
        if not inside and not self.pinned:      # 立即缩回（无延迟）
            self.collapse()

    # ================= 右键菜单 =================
    def _menu(self, pos: QPoint):
        m = QMenu(self)
        nxt, prv = self.neighbor_chapter(1), self.neighbor_chapter(-1)
        a_prev_ch = m.addAction(f"上一话：{prv.get('name', '')}" if prv else "上一话")
        a_prev_ch.setEnabled(bool(prv))
        a_next_ch = m.addAction(f"下一话：{nxt.get('name', '')}" if nxt else "下一话")
        a_next_ch.setEnabled(bool(nxt))
        m.addSeparator()
        a_open = m.addAction("在主窗口打开当前页")
        a_fold = m.addAction("收起")
        a_side = m.addAction("停靠到左侧" if self.side == "right" else "停靠到右侧")
        a_shape = m.addAction("切换为细缝" if self.shape == "strip" else "切换为小封面条")
        a_peek = m.addAction("边缘感应：开" if self.auto_peek else "边缘感应：关")
        m.addSeparator()
        a_close = m.addAction("关闭迷你阅读器")
        chosen = m.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == a_prev_ch:
            if prv:
                self._switch_chapter(prv["id"], to_end=True)
        elif chosen == a_next_ch:
            if nxt:
                self._switch_chapter(nxt["id"], page=0)
        elif chosen == a_open:
            self.open_in_main.emit()
        elif chosen == a_fold:
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

    # ================= 设置项 =================
    def set_side(self, side: str):
        self.side = side
        STORE.set_cfg("edge.side", side)
        if self.isVisible() and not self.suspended:
            self.start()

    def set_shape(self, shape: str):
        self.shape = shape
        STORE.set_cfg("edge.shape", shape)
        if self.isVisible() and not self.suspended:
            self.start()

    def set_auto_peek(self, on: bool):
        self.auto_peek = bool(on)
        STORE.set_cfg("edge.auto_peek", self.auto_peek)

    # ================= 空态：最近在读 =================
    def set_recent_list(self, items: list[dict]):
        while self.recent_box.count():
            it = self.recent_box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        rows = [h for h in (items or []) if h.get("path")][:4]
        for h in rows:
            total = h.get("total", 0) or 0
            pos = f"{int(h.get('page', 0) or 0) + 1}/{total}" if total else "未读"
            book = h.get("book_title", "")
            label = f"{book} · {h.get('name', '')}" if book else h.get("name", "")
            b = QPushButton(f"{label[:20]}   {pos}")
            b.setObjectName("MiniBtnLeft")
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(28)
            b.clicked.connect(lambda _=False, p=h.get("path", ""), n=h.get("name", ""),
                              k=h.get("key", ""): self._open_recent(p, n, k))
            self.recent_box.addWidget(b)

    def _open_recent(self, path: str, name: str, cid: str):
        self.open_chapter.emit(path, name, cid)
