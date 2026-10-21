"""阅读器：连续滚动 / 单页翻页；自绘滚动、异步解码、LRU 缓存、工具条自动隐藏。"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from .cbr import Cbz
from . import theme
from .store import STORE
from .tasks import ASYNC

PAD = 0          # 页面四周不留白：图片有多大就铺多大
CACHE_MAX = 20
MAX_DECODE_W = 2400
MAX_DECODE_H = 3400


class ReaderView(QWidget):
    """阅读视图：自绘页面栈，只解码可见页。"""

    page_changed = Signal(int, int, float)   # index, total, ratio

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        self.book: Cbz | None = None
        self.total = 0
        self.sizes: list[tuple[int, int]] = []
        self.layout: list[tuple[float, float, float, float]] = []
        self._cache: dict[int, QPixmap] = {}
        self._order: list[int] = []
        dpr = self.devicePixelRatioF() or 1.0
        self._cache_max = CACHE_MAX if dpr <= 1.25 else max(6, int(CACHE_MAX / (dpr * dpr)))
        self._loading: set[int] = set()

        r = STORE.cfg("reader", {})
        self.mode = r.get("mode", "scroll")      # scroll | single
        self.fit = r.get("fit", "width")         # width | height | original | custom
        self.zoom = float(r.get("zoom", 1.0) or 1.0)
        self.rtl = bool(r.get("rtl", False))
        self.bg = r.get("bg", "#101216")
        self.gap = int(r.get("gap", 0))

        self._scroll = 0.0
        self._content_h = 0.0
        self._cur = 0
        self._drag_y = None
        self._smooth = QTimer(self)
        self._smooth.setInterval(16)
        self._smooth.timeout.connect(self._smooth_step)
        self._smooth_target = 0.0
        ASYNC.sig.page.connect(self._on_page)
        theme.bus.changed.connect(self.update)

    # ================= 打开 / 关闭 =================
    def open_book(self, path: str, start_page: int = 0, pos: float = 0.0) -> bool:
        self.close_book()
        cb = Cbz(path)
        if cb.page_count == 0:
            return False
        self.book = cb
        self.total = cb.page_count
        self.sizes = cb.page_sizes
        self._cur = max(0, min(start_page, self.total - 1))
        self._cache.clear()
        self._order.clear()
        self._loading.clear()
        self._scroll = 0.0
        self.relayout()
        self.set_page(self._cur, ratio=pos if self.mode == "scroll" else 0.0, animate=False)
        self.update()
        return True

    def close_book(self):
        if self.book:
            self.book.close()
            self.book = None

    # ================= 布局 =================
    def _avail(self):
        return max(60, self.width() - 2 * PAD), max(60, self.height() - 2 * PAD)

    def _scale_for(self, w: int, h: int, aw: int, ah: int) -> float:
        if self.fit == "custom":
            return max(0.02, self.zoom)
        if self.fit == "original":
            return max(0.02, 1.0 * self.zoom)
        if self.mode == "single":
            return max(0.02, min(aw / max(1, w), ah / max(1, h)) * self.zoom)
        # 逐页按自身宽/高缩放：图片多宽就铺多宽，不留左右/上下冗余边框
        if self.fit == "height":
            return max(0.02, ah / max(1, h) * self.zoom)
        return max(0.02, aw / max(1, w) * self.zoom)

    def relayout(self):
        vw, vh = self.width(), self.height()
        if not self.sizes:
            self.layout, self._content_h = [], 0.0
            return
        aw, ah = self._avail()
        if self.mode == "single":
            i = max(0, min(self._cur, len(self.sizes) - 1))
            w, h = self.sizes[i]
            s = self._scale_for(w, h, aw, ah)
            pw, ph = w * s, h * s
            lay = [(0.0, 0.0, 0.0, 0.0)] * len(self.sizes)   # 其余页占位，避免叠画
            lay[i] = ((vw - pw) / 2, (vh - ph) / 2, pw, ph)
            self.layout = lay
            self._content_h = float(vh)
            return
        lay, y, max_w = [], float(PAD), 0.0
        for (w, h) in self.sizes:
            s = self._scale_for(w, h, aw, ah)
            pw, ph = w * s, h * s
            max_w = max(max_w, pw)
            lay.append((0.0, y, pw, ph))
            y += ph + self.gap
        self.layout = [((vw - pw) / 2, py, pw, ph) for (_x, py, pw, ph) in lay]
        self._content_h = y - self.gap + PAD

    # ================= 解码缓存 =================
    def _target_size(self, i: int):
        if i < 0 or i >= len(self.layout):
            return 0, 0
        _x, _y, w, h = self.layout[i]
        # 按「物理像素」解码：高 DPI 屏上若按逻辑像素出图，Qt 会再放大绘制导致发虚
        dpr = self.devicePixelRatioF() or 1.0
        return (min(int((w + 2) * dpr), MAX_DECODE_W),
                min(int((h + 2) * dpr), MAX_DECODE_H))

    def request(self, i: int):
        if not self.book or i < 0 or i >= self.total:
            return
        if i in self._loading:
            return
        tw, th = self._target_size(i)
        if tw <= 0:
            return
        cached = self._cache.get(i)
        if cached is not None:
            # 尺寸校验：布局没定尺寸时解码出来的小图不能一直用（会发虚），
            # 目标变大就丢弃重解；但不能超过原图自身宽度，否则会反复重解。
            src_w = self.sizes[i][0] if i < len(self.sizes) else tw
            need = min(tw, int(src_w))
            if cached.width() >= need * 0.92:
                return
            self._cache.pop(i, None)
            try:
                self._order.remove(i)
            except ValueError:
                pass
        self._loading.add(i)
        ASYNC.page(str(self.book.path), self.book.key, i, tw, th)

    def pixmap(self, i: int):
        return self._cache.get(i)

    def _request_around(self, i: int):
        """预取当前页与前后各一页（不依赖 paint 事件）。"""
        for j in (i, i + 1, i - 1):
            self.request(j)

    def showEvent(self, e):
        super().showEvent(e)
        if self.book:
            self._request_around(self._cur)

    def _on_page(self, key: str, index: int, image):
        if not self.book or key != self.book.key:
            return
        self._loading.discard(index)
        if image is None or image.isNull():
            return
        pm = QPixmap.fromImage(image)
        pm.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
        self._cache[index] = pm
        self._order.append(index)
        while len(self._order) > self._cache_max:
            self._cache.pop(self._order.pop(0), None)
        self.update()

    def clear_cache(self):
        self._cache.clear()
        self._order.clear()
        self._loading.clear()

    # ================= 绘制 =================
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(self.bg))
        if not self.layout:
            p.end()
            return
        r = e.rect()
        off = int(self._scroll) if self.mode == "scroll" else 0
        visible = []
        for i, (x, y, w, h) in enumerate(self.layout):
            if w < 2 or h < 2:
                continue
            sy = y - off
            if sy > r.bottom() + 40 or sy + h < r.top() - 40:
                continue
            visible.append(i)
            pm = self._cache.get(i)
            if pm is not None and not pm.isNull():
                # 画进布局槽位：源图小于槽位（低分辨率页）时也能正确铺满、不跑位
                p.drawPixmap(QRect(int(x), int(sy), int(w), int(h)), pm)
            else:
                dark = QColor(self.bg).lightness() < 128
                p.setPen(QColor("#2A2F38" if dark else "#DED8CB"))
                p.setBrush(QColor("#1A1E25" if dark else "#F1ECE1"))
                p.drawRoundedRect(QRect(int(x), int(sy), int(w), int(h)),
                                  theme.radius_px(), theme.radius_px())
                p.setPen(QColor("#6B7280" if dark else "#8E8577"))
                p.drawText(QRect(int(x), int(sy), int(w), int(h)),
                           Qt.AlignCenter, f"{i + 1} / {self.total}")
        for i in visible:
            self.request(i)
        p.end()

    # ================= 滚动 =================
    def _max_scroll(self) -> float:
        if self.mode != "scroll":
            return 0.0
        return max(0.0, self._content_h - self.height())

    def scroll_to(self, value: float, animate: bool = False):
        target = max(0.0, min(self._max_scroll(), float(value)))
        if animate:
            self._smooth_target = target
            if not self._smooth.isActive():
                self._smooth.start()
        else:
            self._smooth.stop()
            self._scroll = target
            self.update()
            self._update_current()

    def scroll_by(self, dy: float, animate: bool = False):
        base = self._smooth_target if self._smooth.isActive() else self._scroll
        self.scroll_to(base + dy, animate)

    def _smooth_step(self):
        d = self._smooth_target - self._scroll
        if abs(d) < 1.2:
            self._scroll = self._smooth_target
            self._smooth.stop()
        else:
            self._scroll += d * 0.3
        self.update()
        self._update_current()

    # ================= 页码 =================
    def set_page(self, index: int, ratio: float = 0.0, animate: bool = True):
        if not self.layout or self.total <= 0:
            return
        index = max(0, min(index, self.total - 1))
        self._cur = index
        if self.mode == "single":
            self._scroll = 0.0
            self.relayout()
            self._request_around(index)
            self.update()
        else:
            _x, y, _w, h = self.layout[index]
            self.scroll_to(y - PAD + h * max(0.0, min(1.0, ratio)), animate=animate)
            self._request_around(index)
        self._emit_progress()

    def next_page(self, step: int = 1):
        if self.mode == "single":
            self.set_page(self._cur + step, animate=False)
        else:
            self.scroll_by(self.height() * 0.9 * (1 if step > 0 else -1), animate=True)

    def _update_current(self):
        if self.mode != "scroll" or not self.layout:
            return
        mid = self._scroll + self.height() / 2
        best, bd = self._cur, float("inf")
        for i, (_x, y, _w, h) in enumerate(self.layout):
            d = abs((y + h / 2) - mid)
            if d < bd:
                best, bd = i, d
        self._cur = best
        self._emit_progress()

    def _emit_progress(self):
        if self.total <= 0:
            return
        pos = 0.0
        if self.mode == "scroll" and self._cur < len(self.layout):
            _x, y, _w, h = self.layout[self._cur]
            pos = 0.0 if h <= 0 else max(0.0, min(1.0, (self._scroll - (y - PAD)) / h))
        self.page_changed.emit(self._cur, self.total, pos)

    @property
    def current(self) -> int:
        return self._cur

    # ================= 缩放 / 模式 =================
    def zoom_by(self, factor: float):
        self.zoom = max(0.15, min(6.0, self.zoom * factor))
        self.fit = "custom"
        self.relayout()
        self.clear_cache()
        if self.mode == "single":
            self.set_page(self._cur, animate=False)
        else:
            self.scroll_to(self._scroll, animate=False)
        self.update()

    def set_fit(self, fit: str):
        self.fit = fit
        self.zoom = 1.0
        self.relayout()
        self.clear_cache()
        if self.mode == "scroll":
            self.scroll_to(0, animate=False)
        self.update()
        self._emit_progress()

    def toggle_mode(self) -> str:
        self.mode = "single" if self.mode == "scroll" else "scroll"
        self._scroll = 0.0
        self._smooth.stop()
        self.relayout()
        self.clear_cache()
        if self.mode == "scroll":
            self.scroll_to(0, animate=False)
        else:
            self.set_page(self._cur, animate=False)
        self._emit_progress()
        self.update()
        return self.mode

    # ================= 交互 =================
    def resizeEvent(self, e):
        self.relayout()
        self.clear_cache()
        super().resizeEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.12 ** (e.angleDelta().y() / 120.0))
            e.accept()
            return
        dy, dx = e.angleDelta().y() / 120.0, e.angleDelta().x() / 120.0
        if self.mode == "single" and abs(dy) >= abs(dx):
            self.next_page(1 if dy < 0 else -1)
            e.accept()
            return
        self.scroll_by(-dy * 120, animate=False)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_y = e.position().y()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_y is not None and (e.buttons() & Qt.LeftButton):
            self.scroll_by(self._drag_y - e.position().y(), animate=False)
            self._drag_y = e.position().y()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_y = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Right, Qt.Key_D):
            self.next_page(-1 if self.rtl else 1)
        elif k in (Qt.Key_Left, Qt.Key_A):
            self.next_page(1 if self.rtl else -1)
        elif k in (Qt.Key_Down, Qt.Key_J):
            self.scroll_by(100, animate=True)
        elif k in (Qt.Key_Up, Qt.Key_K):
            self.scroll_by(-100, animate=True)
        elif k in (Qt.Key_Space, Qt.Key_PageDown):
            self.next_page(1) if self.mode == "single" else self.scroll_by(self.height() * 0.9, True)
        elif k == Qt.Key_PageUp:
            self.scroll_by(-self.height() * 0.9, True)
        elif k == Qt.Key_Home:
            self.set_page(0, animate=False)
        elif k == Qt.Key_End:
            self.set_page(self.total - 1, animate=False)
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.15)
        elif k == Qt.Key_Minus:
            self.zoom_by(1 / 1.15)
        elif k == Qt.Key_0:
            self.set_fit("width")
        else:
            super().keyPressEvent(e)
            return
        e.accept()


class ReaderPage(QWidget):
    """阅读页 = 视图 + 自动隐藏工具条 + 页码角标。"""

    back_requested = Signal()
    camo_requested = Signal()
    fullscreen_requested = Signal()

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        self._name = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.view = ReaderView(self)
        self.view.page_changed.connect(self._on_page_changed)
        lay.addWidget(self.view, 1)

        self.bar = QFrame(self)
        self.bar.setObjectName("ReaderBar")
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(12, 7, 12, 8)
        bl.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        self.btn_back = QPushButton("← 书架")
        self.lbl_title = QLabel("")
        self.lbl_title.setObjectName("ReaderTitle")
        self.lbl_title.setMaximumWidth(260)
        self.btn_mode = QPushButton("滚动")
        self.btn_mode.setCheckable(True)
        self.btn_fit = QPushButton("适配宽")
        self.btn_rtl = QPushButton("左→右")
        self.btn_rtl.setCheckable(True)
        self.btn_zo = QPushButton("−")
        self.btn_zi = QPushButton("+")
        self.lbl_zoom = QLabel("自动")
        self.lbl_zoom.setFixedWidth(40)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setFixedWidth(160)
        self.lbl_page = QLabel("0 / 0")
        self.lbl_page.setFixedWidth(70)
        self.lbl_page.setAlignment(Qt.AlignCenter)
        self.btn_camo = QPushButton("伪装")
        self.btn_fs = QPushButton("⛶")
        self.btn_fs.setToolTip("全屏 (F11)")

        self.btn_pin = QPushButton("固定")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip("固定工具栏，不再自动隐藏")
        self.btn_pin.setCursor(Qt.PointingHandCursor)

        bl.addLayout(top)
        bl.addLayout(bottom)
        top.addWidget(self.btn_back)
        top.addWidget(self.lbl_title, 1)
        top.addWidget(self.lbl_page)
        top.addWidget(self.btn_pin)
        top.addWidget(self.btn_camo)
        top.addWidget(self.btn_fs)
        sep = QFrame()
        sep.setObjectName("BarSep")
        sep.setFixedSize(1, 16)
        bottom.addWidget(self.btn_mode)
        bottom.addWidget(self.btn_fit)
        bottom.addWidget(self.btn_rtl)
        bottom.addSpacing(4)
        bottom.addWidget(sep)
        lbl_zoom_title = QLabel("缩放")
        lbl_zoom_title.setObjectName("BarLabel")
        bottom.addWidget(lbl_zoom_title)
        bottom.addWidget(self.btn_zo)
        bottom.addWidget(self.lbl_zoom)
        bottom.addWidget(self.btn_zi)
        bottom.addWidget(self.slider, 1)

        for w, tip in (
                (self.btn_back, "返回书详情（Esc）"),
                (self.btn_mode, "连续滚动 / 单页翻页（M）"),
                (self.btn_fit, "适配方式：宽 / 高 / 原始（0 恢复适配宽）"),
                (self.btn_rtl, "阅读方向：左→右 / 右→左（R）"),
                (self.btn_zo, "缩小（- 或 Ctrl+滚轮）"),
                (self.btn_zi, "放大（+ 或 Ctrl+滚轮）"),
                (self.slider, "拖动跳页"),
                (self.lbl_page, "当前页 / 总页数"),
                (self.btn_camo, "桌面伪装（Ctrl+Shift+X）"),
                (self.btn_fs, "全屏（F11）"),
        ):
            w.setToolTip(tip)
        self.lbl_title.setToolTip("书名 · 话名")
        self.btn_pin.clicked.connect(self._toggle_pin)

        # 工具条收起后常驻的小把手：告诉用户工具栏在哪里
        self.grip = QPushButton("⌃  工具栏", self)
        self.grip.setObjectName("BarGrip")
        self.grip.setCursor(Qt.PointingHandCursor)
        self.grip.setToolTip("显示工具栏（移动鼠标也会自动出现）")
        self.grip.setFixedSize(96, 26)
        self.grip.clicked.connect(self._show_toolbar_pinned)
        self.grip.hide()

        self.badge = QLabel("", self)
        self.badge.setObjectName("PageBadge")

        self.btn_back.clicked.connect(self.back_requested)
        self.btn_camo.clicked.connect(self.camo_requested)
        self.btn_fs.clicked.connect(self.fullscreen_requested)
        self.btn_mode.clicked.connect(lambda: self._apply_mode(self.view.toggle_mode()))
        self.btn_fit.clicked.connect(self._cycle_fit)
        self.btn_rtl.clicked.connect(self._toggle_rtl)
        self.btn_zo.clicked.connect(lambda: self.view.zoom_by(1 / 1.15))
        self.btn_zi.clicked.connect(lambda: self.view.zoom_by(1.15))
        self.slider.sliderReleased.connect(lambda: self.view.set_page(self.slider.value(), animate=False))
        self.slider.valueChanged.connect(self._slider_moved)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._maybe_hide)
        self.setMouseTracking(True)

    # ---------- 打开 ----------
    def open(self, path: str, name: str, page: int = 0, pos: float = 0.0) -> bool:
        self._name = name
        self.lbl_title.setText(name)
        self.lbl_title.setToolTip(path)
        ok = self.view.open_book(path, page, pos)
        self._apply_mode(self.view.mode)
        self.btn_rtl.setChecked(self.view.rtl)
        self.btn_rtl.setText("右→左" if self.view.rtl else "左→右")
        self._sync_texts()
        self.btn_pin.blockSignals(True)
        self.btn_pin.setChecked(not bool(STORE.cfg("reader_ui.auto_hide_toolbar", True)))
        self.btn_pin.setText("已固定" if self.btn_pin.isChecked() else "固定")
        self.btn_pin.blockSignals(False)
        self.view.setFocus()
        self._flash()
        return ok

    def close_book(self):
        self.view.close_book()

    def book_name(self) -> str:
        return self._name

    # ---------- 工具条 ----------
    def _apply_mode(self, mode: str):
        self.btn_mode.setChecked(mode == "single")
        self.btn_mode.setText("单页" if mode == "single" else "滚动")
        STORE.set_cfg("reader.mode", mode)

    def _sync_texts(self):
        self.btn_fit.setText({"width": "适配宽", "height": "适配高",
                              "original": "原始尺寸"}.get(self.view.fit, "自定义"))
        self.lbl_zoom.setText("自动" if self.view.fit != "custom"
                              else f"{int(self.view.zoom * 100)}%")

    def _cycle_fit(self):
        order = ["width", "height", "original"]
        cur = self.view.fit if self.view.fit in order else "width"
        self.view.set_fit(order[(order.index(cur) + 1) % 3])
        self._sync_texts()

    def _toggle_rtl(self):
        self.view.rtl = self.btn_rtl.isChecked()
        self.btn_rtl.setText("右→左" if self.view.rtl else "左→右")
        STORE.set_cfg("reader.rtl", self.view.rtl)

    def _slider_moved(self, v: int):
        if self.slider.isSliderDown():
            self.lbl_page.setText(f"{v + 1} / {self.view.total}")

    def _on_page_changed(self, idx: int, total: int, _pos: float):
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setMaximum(max(0, total - 1))
            self.slider.setValue(idx)
            self.slider.blockSignals(False)
        self.lbl_page.setText(f"{idx + 1} / {total}")
        self.badge.setText(f"{idx + 1} / {total}")
        self._sync_texts()

    def _pinned(self) -> bool:
        return self.btn_pin.isChecked()

    def _maybe_hide(self):
        if self._pinned():
            return
        if STORE.cfg("reader_ui.auto_hide_toolbar", True) and not self.bar.underMouse():
            self.bar.hide()
            self.badge.hide()
            self.grip.show()
            self.grip.raise_()

    def _flash(self):
        self.bar.show()
        self.badge.show()
        self.grip.hide()
        self._relayout_overlays()
        if not self._pinned():
            self._hide_timer.start(2600)

    def _toggle_pin(self):
        pinned = self.btn_pin.isChecked()
        self.btn_pin.setText("已固定" if pinned else "固定")
        STORE.set_cfg("reader_ui.auto_hide_toolbar", not pinned)
        STORE.save_config()
        if pinned:
            self._hide_timer.stop()
            self.bar.show()
            self.grip.hide()
            self._relayout_overlays()
        else:
            self._hide_timer.start(1800)

    def _show_toolbar_pinned(self):
        self.btn_pin.setChecked(True)
        self._toggle_pin()

    def mouseMoveEvent(self, e):
        self._flash()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hide_timer.start(1200)
        super().leaveEvent(e)

    def resizeEvent(self, e):
        self._relayout_overlays()
        super().resizeEvent(e)

    def _relayout_overlays(self):
        bh = max(72, self.bar.sizeHint().height())
        bw = min(self.width() - 40, max(520, self.bar.sizeHint().width() + 24))
        self.bar.setGeometry((self.width() - bw) // 2, self.height() - bh - 18, bw, bh)
        self.grip.move((self.width() - self.grip.width()) // 2, self.height() - 34)
        self.badge.adjustSize()
        self.badge.move(self.width() - self.badge.width() - 18, 14)

    def set_fullscreen(self, on: bool):
        self.btn_fs.setText("⤡" if on else "⛶")

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self.back_requested.emit()
        elif k == Qt.Key_M:
            self._apply_mode(self.view.toggle_mode())
        elif k == Qt.Key_R:
            self.btn_rtl.setChecked(not self.btn_rtl.isChecked())
            self._toggle_rtl()
        else:
            super().keyPressEvent(e)
            return
        e.accept()
