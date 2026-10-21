"""书架页：以「书」为单位的封面墙（点进去才是各话列表）。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QFontMetrics, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QMenu, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from .cbr import natkey
from .imgutil import cover_pixmap
from .store import BOOKCOVER_DIR, COVER_DIR, STORE
from .tasks import ASYNC
from . import theme

TILE_W, COVER_W, COVER_H = 154, 146, 204

try:
    NO_ORIENTATIONS = Qt.Orientations(0)
except Exception:  # pragma: no cover
    NO_ORIENTATIONS = Qt.Orientation(0)


class FlowLayout(QLayout):
    """自动换行的流式布局。"""

    def __init__(self, parent=None, margin=0, spacing=12):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return NO_ORIENTATIONS

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for it in self._items:
            w, h = it.sizeHint().width(), it.sizeHint().height()
            if x + w > eff.right() and line_h > 0:
                x = eff.x()
                y += line_h + self._spacing
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._spacing
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


class BookTile(QFrame):
    """一本书的封面卡片。"""

    activated = Signal(str)                     # bid
    context_menu = Signal(str, QPoint)

    def __init__(self, book: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("BookTile")
        self.setFixedSize(TILE_W, COVER_H + 56)
        self.bid = book["id"]
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{book['title']}\n共 {book['stats']['chapters']} 话"
                        f"　已读完 {book['stats']['finished']} 话")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        self.cover = QLabel()
        self.cover.setObjectName("CoverBox")
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.cover, 0, Qt.AlignHCenter)

        self.badge = QLabel(self.cover)
        self.badge.setAttribute(Qt.WA_StyledBackground, True)
        theme.style(self.badge,
                    "background:$accent;color:$accent_text;border-radius:$r1;"
                    "padding:1px 6px;font-size:$f10;font-weight:600;")
        self.badge.hide()

        self.lbl = QLabel()
        self.lbl.setObjectName("TileMeta")
        self.lbl.setFixedWidth(COVER_W)
        lay.addWidget(self.lbl)

        bar = QFrame()
        bar.setFixedSize(COVER_W, 4)
        theme.style(bar, "background:$border;border-radius:2px;")
        self.bar_in = QFrame(bar)
        self.bar_in.setGeometry(0, 0, 0, 4)
        lay.addWidget(bar, 0, Qt.AlignHCenter)
        self._bar = bar

        self.refresh(book)

    # ---------- 数据 ----------
    def refresh(self, book: dict):
        self.bid = book["id"]
        title = book["title"]
        st = book["stats"]
        self.lbl.setText(QFontMetrics(self.lbl.font()).elidedText(
            title, Qt.ElideMiddle, COVER_W))
        n = st["chapters"]
        if n == 0:
            self.badge.hide()
            self.bar_in.setFixedWidth(0)
            self.cover.setPixmap(QPixmap())
            self.cover.setText("空书\n点此导入")
        else:
            self.bar_in.setFixedWidth(max(2, int(COVER_W * st["ratio"])))
            theme.now(self.bar_in, "background:%s;border-radius:2px;"
                      % theme.c("ok" if st["ratio"] >= 1 else "accent"))
            txt = f"已读完 {st['finished']}/{n}" if st["finished"] else f"{n} 话"
            self.badge.setText(txt)
            self.badge.show()
            self.badge.adjustSize()
            self.badge.move(COVER_W - self.badge.width() - 6, 6)
        self.load_cover()

    def load_cover(self):
        cid, custom = STORE.book_cover_source(self.bid)
        custom_file = BOOKCOVER_DIR / f"{self.bid}.jpg"
        if custom:
            pm = QPixmap(custom)
            if not pm.isNull():
                self._set_pixmap(pm)
                return
        if custom_file.exists():
            pm = QPixmap(str(custom_file))
            if not pm.isNull():
                self._set_pixmap(pm)
                return
        if cid:
            cached = COVER_DIR / f"{cid}_420.jpg"
            if cached.exists():
                pm = QPixmap(str(cached))
                if not pm.isNull():
                    self._set_pixmap(pm)
                    return
            self.cover.setPixmap(QPixmap())
            self.cover.setText("加载中…")
            ch = STORE.chapter(cid)
            if ch:
                ASYNC.cover(ch["path"])
        else:
            self.cover.setPixmap(QPixmap())
            self.cover.setText("空书\n点此导入")

    def _set_pixmap(self, pm: QPixmap):
        self.cover.setText("")
        self.cover.setPixmap(cover_pixmap(pm, COVER_W, COVER_H,
                                          theme.radius_px(),
                                          self.devicePixelRatioF()))
        self.badge.adjustSize()
        self.badge.move(COVER_W - self.badge.width() - 6, 6)

    def on_chapter_cover(self, cid: str, path: str):
        target_cid, _custom = STORE.book_cover_source(self.bid)
        if cid == target_cid:
            pm = QPixmap(path)
            if not pm.isNull():
                self._set_pixmap(pm)

    # ---------- 交互 ----------
    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._hover:
            p = QPainter(self)
            pen = QPen(QColor(theme.c("accent")))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            r = theme.radius_px() + 2
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), r, r)
            p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self.bid)
        elif e.button() == Qt.RightButton:
            self.context_menu.emit(self.bid, e.globalPosition().toPoint())
        super().mousePressEvent(e)


class RecentCard(QFrame):
    """继续阅读卡片（章节级）。"""

    activated = Signal(str, str, str)   # path, name, cid

    def __init__(self, h: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("RecentCard")
        self.setFixedSize(210, 42)
        self.setCursor(Qt.PointingHandCursor)
        self._cid = h.get("key", "")
        self._path = h.get("path", "")
        self._name = h.get("name", "")
        self._title = h.get("book_title") or self._name

        cl = QHBoxLayout(self)
        cl.setContentsMargins(10, 4, 8, 4)
        cl.setSpacing(8)
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        nm = QLabel()
        nm.setObjectName("RecentName")
        nm.setText(QFontMetrics(nm.font()).elidedText(self._title, Qt.ElideMiddle, 168))
        total = h.get("total", 0) or 0
        pg = (h.get("page", 0) or 0) + 1
        sub = QLabel(f"{self._name} · {pg}/{total}" if total else self._name)
        sub.setObjectName("RecentSub")
        v.addWidget(nm)
        v.addWidget(sub)
        bar = QFrame()
        bar.setFixedWidth(4)
        theme.now(bar, "background:$accent;border-radius:2px;")
        cl.insertWidget(0, bar)
        cl.addLayout(v, 1)
        self.setToolTip(f"{self._title} · {self._name}\n{self._path}")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self._path, self._name, self._cid)
        super().mouseReleaseEvent(e)


class ShelfPage(QWidget):
    """书架：书封面墙 + 继续阅读 + 新增书 / 导入。"""

    open_book = Signal(str)             # bid -> 书详情
    open_chapter = Signal(str, str, str)  # path, name, cid -> 直接开读
    new_book_requested = Signal()
    import_to_book = Signal(str)        # bid（向这本书导入话）
    rename_book = Signal(str)
    cover_requested = Signal(str)
    toast = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        self._tiles: dict[str, BookTile] = {}
        self._keyword = ""
        self._sort = "added"

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("SectionTitle")
        head.addWidget(self.lbl_count)
        head.addStretch(1)

        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("搜索书名…")
        self.search.setFixedWidth(180)
        self.search.textChanged.connect(self._on_search)
        head.addWidget(self.search)

        self.btn_sort = QPushButton("添加时间")
        self.btn_sort.setObjectName("Ghost")
        self.btn_sort.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self.btn_sort)
        for label, val in (("添加时间", "added"), ("书名", "name"),
                           ("最近阅读", "recent"), ("话数", "chapters")):
            a = QAction(label, menu)
            a.triggered.connect(lambda _=False, v=val, t=label: self._set_sort(v, t))
            menu.addAction(a)
        self.btn_sort.setMenu(menu)
        head.addWidget(self.btn_sort)

        self.btn_new = QPushButton("＋ 新增书")
        self.btn_new.setObjectName("Primary")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.setToolTip("新建一本书，然后往里面导入各话")
        self.btn_new.clicked.connect(self.new_book_requested)
        head.addWidget(self.btn_new)
        root.addLayout(head)

        # ---- 继续阅读（章节级）----
        self.recent_box = QFrame()
        self.recent_box.setObjectName("Card")
        rb = QVBoxLayout(self.recent_box)
        rb.setContentsMargins(12, 8, 12, 10)
        rb.setSpacing(6)
        rhead = QHBoxLayout()
        t = QLabel("继续阅读")
        t.setObjectName("CardTitle")
        rhead.addWidget(t)
        rhead.addStretch(1)
        self.lbl_recent_hint = QLabel("")
        self.lbl_recent_hint.setObjectName("Muted")
        rhead.addWidget(self.lbl_recent_hint)
        rb.addLayout(rhead)
        self.recent_scroll = QScrollArea()
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFixedHeight(52)
        self.recent_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.recent_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_inner = QWidget()
        self.recent_lay = QHBoxLayout(self.recent_inner)
        self.recent_lay.setContentsMargins(0, 0, 0, 0)
        self.recent_lay.setSpacing(8)
        self.recent_lay.addStretch(1)
        self.recent_scroll.setWidget(self.recent_inner)
        rb.addWidget(self.recent_scroll)
        root.addWidget(self.recent_box)

        # ---- 书封面墙 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.flow = FlowLayout(self.grid_host, margin=2, spacing=14)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        self.empty = QLabel("书架还是空的\n点右上角「＋ 新增书」建一本书，再往书里导入各话；\n"
                            "也可以直接把 .cbz 或图片文件夹拖进窗口")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("EmptyState")
        root.addWidget(self.empty, 1)

        ASYNC.sig.cover.connect(self._on_cover)
        self.refresh()

    # ================= 渲染 =================
    def _books(self) -> list[dict]:
        items = STORE.book_list()
        if self._keyword:
            kw = self._keyword.lower()
            items = [b for b in items if kw in b["title"].lower()]
        if self._sort == "name":
            items.sort(key=lambda b: natkey(b["title"]))
        elif self._sort == "recent":
            items.sort(key=lambda b: b["stats"]["last_time"], reverse=True)
        elif self._sort == "chapters":
            items.sort(key=lambda b: b["stats"]["chapters"], reverse=True)
        else:
            items.sort(key=lambda b: b.get("added", 0))
        return items

    def refresh(self):
        self._rebuild_recent()
        self._rebuild_grid()

    def _rebuild_grid(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._tiles.clear()

        books = self._books()
        for b in books:
            tile = BookTile(b)
            tile.activated.connect(self.open_book)
            tile.context_menu.connect(self._menu)
            self.flow.addWidget(tile)
            self._tiles[b["id"]] = tile

        all_books = STORE.book_list()
        total_ch = sum(b["stats"]["chapters"] for b in all_books)
        self.lbl_count.setText(
            f"我的书架 · {len(all_books)} 本书 / {total_ch} 话"
            + (f"（{len(books)} 本匹配）" if self._keyword else ""))
        self.empty.setVisible(not all_books)
        self.scroll.setVisible(bool(all_books))

    def _rebuild_recent(self):
        while self.recent_lay.count() > 1:
            it = self.recent_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        items = STORE.recent_chapters(12)
        for h in items:
            card = RecentCard(h)
            card.activated.connect(self.open_chapter)
            self.recent_lay.insertWidget(self.recent_lay.count() - 1, card)
        self.recent_box.setVisible(bool(items))
        if items:
            n = len(STORE.recent_chapters(999))
            self.lbl_recent_hint.setText(f"最近读过 {n} 话")

    def _on_cover(self, cid: str, cover_path: str):
        for tile in self._tiles.values():
            tile.on_chapter_cover(cid, cover_path)

    def _on_search(self, text: str):
        self._keyword = text.strip()
        self._rebuild_grid()

    def _set_sort(self, val: str, label: str):
        self._sort = val
        self.btn_sort.setText(label)
        self._rebuild_grid()

    # ================= 右键菜单 =================
    def _menu(self, bid: str, pos: QPoint):
        b = STORE.book(bid)
        if not b:
            return
        st = STORE.book_stats(bid)
        m = QMenu(self)
        a_open = m.addAction("打开（查看各话）")
        a_resume = m.addAction("继续阅读" if st["chapters"] else "先导入各话")
        m.addSeparator()
        a_import = m.addAction("导入话数…")
        a_rename = m.addAction("重命名…")
        a_cover = m.addAction("设置封面…")
        m.addSeparator()
        a_reveal = m.addAction("在文件夹中显示")
        a_remove = m.addAction("从书架移除（保留文件）")
        chosen = m.exec(pos)
        if chosen is None:
            return
        if chosen == a_open:
            self.open_book.emit(bid)
        elif chosen == a_resume:
            last = STORE.last_chapter(bid)
            if last:
                self.open_chapter.emit(last["path"], last["name"], last["id"])
            else:
                self.import_to_book.emit(bid)
        elif chosen == a_import:
            self.import_to_book.emit(bid)
        elif chosen == a_rename:
            self.rename_book.emit(bid)
        elif chosen == a_cover:
            self.cover_requested.emit(bid)
        elif chosen == a_reveal:
            chs = STORE.chapters_of(bid)
            if chs:
                reveal_in_explorer(chs[0]["path"])
            else:
                self.toast.emit("这本书还没有内容")
        elif chosen == a_remove:
            STORE.remove_book(bid)
            STORE.save_all()
            self.toast.emit(f"已从书架移除《{b['title']}》（文件保留在磁盘）")
            self.refresh()


# ================= 工具 =================
def reveal_in_explorer(path: str) -> None:
    try:
        p = Path(path)
        if not p.exists():
            return
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{p}"' if p.is_file() else f'explorer "{p}"')
        else:
            subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])
    except Exception:
        pass
