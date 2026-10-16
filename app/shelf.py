"""书架页：封面网格、继续阅读、搜索排序、批量选择、右键菜单、拖拽导入。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import (QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout,
                               QLineEdit, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from .cbr import natkey
from .store import STORE
from .tasks import ASYNC
from .theme import ACCENT

TILE_W, COVER_W, COVER_H = 154, 146, 204

try:
    NO_ORIENTATIONS = Qt.Orientations(0)
except Exception:  # pragma: no cover
    NO_ORIENTATIONS = Qt.Orientation(0)


class RecentCard(QFrame):
    """继续阅读卡片。"""

    activated = Signal(str, str, str)   # path, name, key

    def __init__(self, h: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("RecentCard")
        self.setFixedSize(190, 40)
        self.setCursor(Qt.PointingHandCursor)
        self._path = h.get("path", "")
        self._name = h.get("name", "")
        self._key = h["key"]

        cl = QHBoxLayout(self)
        cl.setContentsMargins(10, 4, 8, 4)
        cl.setSpacing(8)
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        nm = QLabel()
        nm.setObjectName("RecentName")
        fm = QFontMetrics(nm.font())
        nm.setText(fm.elidedText(self._name, Qt.ElideMiddle, 148))
        total = h.get("total", 0) or 0
        pg = (h.get("page", 0) or 0) + 1
        sub = QLabel(f"读到 {pg}/{total}" + (" · 已读完" if h.get("finished") else ""))
        sub.setObjectName("RecentSub")
        v.addWidget(nm)
        v.addWidget(sub)
        cl.addLayout(v, 1)
        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setStyleSheet(f"background:{ACCENT};border-radius:2px;")
        cl.addWidget(bar)
        self.setToolTip(self._path + "\n双击/单击继续阅读")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self._path, self._name, self._key)
        super().mouseReleaseEvent(e)



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
    clicked = Signal(str, object)          # key, modifiers
    double_clicked = Signal(str)
    context_menu = Signal(str, QPoint)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("BookTile")
        self.setFixedSize(TILE_W, COVER_H + 52)
        self.key = entry["key"]
        self.path = entry["path"]
        self.name = entry["name"]
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setCursor(Qt.PointingHandCursor)
        self._selected = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(
            f"background:#E9ECF0;border-radius:8px;color:#9AA2AC;font-size:11px;")
        lay.addWidget(self.cover, 0, Qt.AlignHCenter)

        self.badge = QLabel(self.cover)
        self.badge.setStyleSheet(
            "background:rgba(59,111,224,225);color:white;border-radius:6px;"
            "padding:1px 6px;font-size:10px;font-weight:600;")
        self.badge.hide()

        self.lbl = QLabel()
        self.lbl.setObjectName("TileMeta")
        self.lbl.setFixedWidth(COVER_W)
        f = QFont()
        f.setPointSize(9)
        self.lbl.setFont(f)
        self.lbl.setToolTip(entry["path"])
        lay.addWidget(self.lbl)

        bar = QFrame()
        bar.setFixedSize(COVER_W, 4)
        bar.setStyleSheet("background:#E3E6EA;border-radius:2px;")
        self.bar_in = QFrame(bar)
        self.bar_in.setGeometry(0, 0, 0, 4)
        self.bar_in.setStyleSheet(f"background:{ACCENT};border-radius:2px;")
        lay.addWidget(bar, 0, Qt.AlignHCenter)
        self._bar = bar

        self.update_progress(STORE.progress(self.key))
        self.set_cover(entry["path"], entry["key"])

    # ---------- 数据 ----------
    def set_cover(self, path: str, key: str):
        from .cbr import book_key
        from .store import COVER_DIR
        cached = COVER_DIR / f"{key}_420.jpg"
        if cached.exists() and cached.stat().st_mtime >= Path(path).stat().st_mtime:
            self.apply_cover(str(cached))
        else:
            self.cover.setText("加载中…")
            ASYNC.cover(path)

    def apply_cover(self, cover_path: str):
        pm = QPixmap(cover_path)
        if pm.isNull():
            return
        pm = pm.scaled(COVER_W, COVER_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.cover.setPixmap(pm)
        self.cover.setStyleSheet("background:#E9ECF0;border-radius:8px;")
        self.badge.adjustSize()
        self.badge.move(COVER_W - self.badge.width() - 6, 6)

    def update_progress(self, h: dict | None):
        name = self.name
        fm = QFontMetrics(self.lbl.font())
        self.lbl.setText(fm.elidedText(name, Qt.ElideMiddle, COVER_W))
        total = (h or {}).get("total") or 0
        page = (h or {}).get("page") or 0
        if total:
            ratio = 0.0 if (h or {}).get("finished") else min(1.0, (page + 1) / total)
            self.bar_in.setFixedWidth(max(2, int(COVER_W * ratio)))
            if (h or {}).get("finished"):
                self.badge.setText("已读完")
                self.badge.setStyleSheet(
                    "background:rgba(46,158,91,235);color:white;border-radius:6px;"
                    "padding:1px 6px;font-size:10px;font-weight:600;")
            else:
                self.badge.setText(f"{page + 1}/{total}")
                self.badge.setStyleSheet(
                    "background:rgba(59,111,224,225);color:white;border-radius:6px;"
                    "padding:1px 6px;font-size:10px;font-weight:600;")
            self.badge.show()
            self.badge.adjustSize()
            self.badge.move(COVER_W - self.badge.width() - 6, 6)
            self.lbl.setText(fm.elidedText(name, Qt.ElideMiddle, COVER_W - 34))
        else:
            self.bar_in.setFixedWidth(0)
            self.badge.hide()
        self.bar_in.setStyleSheet(
            f"background:{'#2E9E5B' if (h or {}).get('finished') else ACCENT};border-radius:2px;")

    # ---------- 选中态 ----------
    def set_selected(self, on: bool):
        self._selected = on
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._selected:
            p = QPainter(self)
            p.setPen(QColor(ACCENT))
            p.setBrush(QColor(232, 239, 252, 90))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
            p.end()

    # ---------- 交互 ----------
    def _key(self):
        return self.key

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key, e.modifiers())
        elif e.button() == Qt.RightButton:
            self.context_menu.emit(self.key, e.globalPosition().toPoint())
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit(self.key)
        super().mouseDoubleClickEvent(e)


class ShelfPage(QWidget):
    open_book = Signal(str, str, str)      # path, name, key
    import_requested = Signal()
    toast = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        self._tiles: dict[str, BookTile] = {}
        self._sel: set[str] = set()
        self._last_click = ""
        self._keyword = ""
        self._sort = "added"
        self._recent_limit = 12

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        # ---- 头栏 ----
        head = QHBoxLayout()
        head.setSpacing(8)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("SectionTitle")
        head.addWidget(self.lbl_count)
        head.addStretch(1)

        self.search = QLineEdit()
        self.search.setObjectName("SearchBox")
        self.search.setPlaceholderText("搜索书名…")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._on_search)
        head.addWidget(self.search)

        self.cmb_sort = QPushButton("添加时间")
        self.cmb_sort.setObjectName("Ghost")
        self.cmb_sort.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self.cmb_sort)
        for label, val in (("添加时间", "added"), ("书名", "name"), ("最近阅读", "recent"),
                           ("文件大小", "size")):
            a = QAction(label, menu)
            a.triggered.connect(lambda _=False, v=val, t=label: self._set_sort(v, t))
            menu.addAction(a)
        self.cmb_sort.setMenu(menu)
        head.addWidget(self.cmb_sort)

        self.btn_import = QPushButton("＋ 批量导入")
        self.btn_import.setObjectName("Primary")
        self.btn_import.setCursor(Qt.PointingHandCursor)
        self.btn_import.setToolTip("选择 CBZ 文件或整个文件夹（支持递归扫描）")
        self.btn_import.clicked.connect(self.import_requested)
        head.addWidget(self.btn_import)
        root.addLayout(head)

        # ---- 继续阅读 ----
        self.recent_box = QFrame()
        self.recent_box.setObjectName("Card")
        rb = QVBoxLayout(self.recent_box)
        rb.setContentsMargins(12, 8, 12, 10)
        rb.setSpacing(6)
        rhead = QHBoxLayout()
        t = QLabel("继续阅读")
        t.setStyleSheet("color:#1B1E23;font-size:12px;font-weight:700;")
        rhead.addWidget(t)
        rhead.addStretch(1)
        self.lbl_recent_hint = QLabel("")
        self.lbl_recent_hint.setObjectName("Muted")
        rhead.addWidget(self.lbl_recent_hint)
        rb.addLayout(rhead)
        self.recent_scroll = QScrollArea()
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFixedHeight(50)
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

        # ---- 网格 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.flow = FlowLayout(self.grid_host, margin=2, spacing=14)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        # ---- 空态 ----
        self.empty = QLabel("书架空空如也\n点击右上角「批量导入」或直接把 .cbz 拖进窗口")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#9AA2AC;font-size:13px;line-height:170%;")
        root.addWidget(self.empty, 1)

        # ---- 批量操作条 ----
        self.sel_bar = QFrame(self)
        self.sel_bar.setObjectName("Card")
        sl = QHBoxLayout(self.sel_bar)
        sl.setContentsMargins(12, 6, 12, 6)
        sl.setSpacing(8)
        self.lbl_sel = QLabel("已选 0 本")
        sl.addWidget(self.lbl_sel)
        sl.addStretch(1)
        b1 = QPushButton("标记已读"); b1.setObjectName("Ghost")
        b2 = QPushButton("标记未读"); b2.setObjectName("Ghost")
        b3 = QPushButton("移出书架"); b3.setObjectName("Danger")
        for b in (b1, b2, b3):
            b.setCursor(Qt.PointingHandCursor)
            sl.addWidget(b)
        b1.clicked.connect(lambda: self._bulk_mark(True))
        b2.clicked.connect(lambda: self._bulk_mark(False))
        b3.clicked.connect(self._bulk_remove)
        self.sel_bar.hide()

        ASYNC.sig.cover.connect(self._on_cover)
        self.refresh()

    # ================= 数据渲染 =================
    def refresh(self):
        self.rebuild_recent()
        self.rebuild_grid()

    def _entries(self) -> list[dict]:
        items = STORE.shelf_entries()
        if self._keyword:
            kw = self._keyword.lower()
            items = [e for e in items if kw in e["name"].lower()]
        if self._sort == "name":
            items.sort(key=lambda e: natkey(e["name"]))
        elif self._sort == "size":
            items.sort(key=lambda e: e.get("size", 0), reverse=True)
        elif self._sort == "recent":
            hist = STORE.history
            items.sort(key=lambda e: hist.get(e["key"], {}).get("time", 0), reverse=True)
        else:
            items.sort(key=lambda e: e.get("added", 0))
        return items

    def rebuild_grid(self):
        while self.flow.count():
            it = self.flow.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._tiles.clear()

        entries = self._entries()
        for e in entries:
            tile = BookTile(e)
            tile.clicked.connect(self._on_tile_click)
            tile.double_clicked.connect(self._on_tile_open)
            tile.context_menu.connect(self._on_tile_menu)
            self.flow.addWidget(tile)
            self._tiles[e["key"]] = tile
            if e["key"] in self._sel:
                tile.set_selected(True)

        total = len(STORE.shelf_entries())
        read = sum(1 for e in STORE.shelf_entries()
                   if STORE.progress(e["key"]) and STORE.progress(e["key"]).get("total"))
        self.lbl_count.setText(f"我的书架 · {total} 本" + (f"（{len(entries)} 匹配）" if self._keyword else ""))
        self.lbl_recent_hint.setText(f"已读过 {read} 本" if read else "")
        self.empty.setVisible(total == 0)
        self.scroll.setVisible(total > 0)
        self.recent_box.setVisible(bool(STORE.recent(1)))
        self._sync_sel_bar()

    def rebuild_recent(self):
        while self.recent_lay.count() > 1:
            it = self.recent_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for h in STORE.recent(self._recent_limit):
            card = RecentCard(h)
            card.activated.connect(self.open_book)
            self.recent_lay.insertWidget(self.recent_lay.count() - 1, card)

    def _on_cover(self, key: str, cover_path: str):
        tile = self._tiles.get(key)
        if tile:
            tile.apply_cover(cover_path)

    def on_progress_changed(self, key: str):
        tile = self._tiles.get(key)
        if tile:
            tile.update_progress(STORE.progress(key))

    # ================= 交互 =================
    def _on_search(self, text: str):
        self._keyword = text.strip()
        self.rebuild_grid()

    def _set_sort(self, val: str, label: str):
        self._sort = val
        self.cmb_sort.setText(label)
        self.rebuild_grid()

    def _on_tile_click(self, key: str, mods):
        if mods & (Qt.ControlModifier | Qt.ShiftModifier):
            if key in self._sel:
                self._sel.discard(key)
            else:
                self._sel.add(key)
        else:
            self._sel = {key} if self._sel != {key} else set()
        self._last_click = key
        for k, t in self._tiles.items():
            t.set_selected(k in self._sel)
        self._sync_sel_bar()

    def _on_tile_open(self, key: str):
        e = STORE.shelf.get(key)
        if e:
            self.open_book.emit(e["path"], e["name"], key)

    def _sync_sel_bar(self):
        n = len(self._sel)
        self.lbl_sel.setText(f"已选 {n} 本")
        self.sel_bar.setVisible(n > 0)
        if n > 0:
            self.sel_bar.setGeometry(24, self.height() - 58, min(660, self.width() - 48), 44)

    def resizeEvent(self, e):
        self._sync_sel_bar()
        super().resizeEvent(e)

    # ================= 批量操作 =================
    def _bulk_mark(self, done: bool):
        for k in list(self._sel):
            h = STORE.progress(k)
            total = (h or {}).get("total") or 0
            if not total:
                try:
                    from .cbr import Cbz
                    p = STORE.shelf.get(k, {}).get("path")
                    if p:
                        cb = Cbz(p)
                        total = cb.page_count
                        cb.close()
                except Exception:
                    total = 0
            STORE.touch_history(k, STORE.shelf.get(k, {}).get("name", ""),
                                0 if done else 0, total)
            STORE.mark_finished(k, done)
        self.toast.emit(f"已标记 {len(self._sel)} 本为{'已读' if done else '未读'}")
        self.refresh()

    def _bulk_remove(self):
        n = len(self._sel)
        for k in list(self._sel):
            STORE.remove_book(k)
        self._sel.clear()
        STORE.save_all()
        self.toast.emit(f"已从书架移除 {n} 本（文件保留在磁盘）")
        self.refresh()

    # ================= 右键菜单 =================
    def _on_tile_menu(self, key: str, pos: QPoint):
        e = STORE.shelf.get(key)
        if not e:
            return
        path = e["path"]
        menu = QMenu(self)
        h = STORE.progress(key) or {}
        act_open = menu.addAction(f"继续阅读（第 {h.get('page', 0) + 1} 页）" if h.get("total")
                                  else "开始阅读")
        menu.addSeparator()
        act_read = menu.addAction("标记为已读")
        act_unread = menu.addAction("标记为未读")
        menu.addSeparator()
        act_loc = menu.addAction("在文件夹中显示")
        act_rm = menu.addAction("从书架移除")
        act_del = menu.addAction("删除文件（移入回收站）")
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen == act_open:
            self.open_book.emit(path, e["name"], key)
        elif chosen == act_read:
            self._sel = {key}
            self._bulk_mark(True)
        elif chosen == act_unread:
            self._sel = {key}
            self._bulk_mark(False)
        elif chosen == act_loc:
            reveal_in_explorer(path)
        elif chosen == act_rm:
            STORE.remove_book(key)
            STORE.save_all()
            self.toast.emit("已从书架移除（文件保留）")
            self.refresh()
        elif chosen == act_del:
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, "删除文件",
                f"将文件移入回收站？\n\n{e['name']}\n{path}\n\n（可从回收站还原）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r == QMessageBox.Yes:
                if recycle_file(path):
                    STORE.remove_book(key)
                    STORE.save_all()
                    self.toast.emit("已移入回收站")
                    self.refresh()
                else:
                    self.toast.emit("删除失败，文件可能被占用")


# ================= 工具 =================
def reveal_in_explorer(path: str) -> None:
    try:
        p = Path(path)
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except Exception:
        pass


def recycle_file(path: str) -> bool:
    """移入回收站（不使用永久删除）。"""
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION = 3, 0x40, 0x10
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = str(Path(path).resolve()) + "\0\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION
        res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return res == 0
    except Exception:
        return False
