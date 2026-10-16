"""书详情页：一本书下面的各话列表（导入/阅读/整理）。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .cbr import natkey
from .store import BOOKCOVER_DIR, COVER_DIR, STORE
from .tasks import ASYNC
from .theme import ACCENT

COVER_W, COVER_H = 104, 146


def fmt_time(ts: float) -> str:
    if not ts:
        return "未读"
    d = time.time() - ts
    if d < 60:
        return "刚刚"
    if d < 3600:
        return f"{int(d // 60)} 分钟前"
    if d < 86400:
        return f"{int(d // 3600)} 小时前"
    if d < 86400 * 7:
        return f"{int(d // 86400)} 天前"
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


class ChapterRow(QFrame):
    """一话（一个 cbz / 一个图片文件夹）。"""

    activated = Signal(str, str, str)     # path, name, cid
    context_menu = Signal(str, QPoint)    # cid, pos

    def __init__(self, index: int, ch: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(62)
        self.setCursor(Qt.PointingHandCursor)
        self.cid = ch["id"]
        self.ch = ch

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(12)

        self.no = QLabel(str(index))
        self.no.setFixedWidth(34)
        self.no.setAlignment(Qt.AlignCenter)
        self.no.setStyleSheet("color:#8B93A1;font-size:12px;font-weight:600;")
        lay.addWidget(self.no)

        self.thumb = QLabel()
        self.thumb.setFixedSize(30, 42)
        self.thumb.setStyleSheet("background:#E9ECF0;border-radius:4px;")
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)

        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        name = QLabel()
        name.setStyleSheet("color:#1B1E23;font-size:12px;font-weight:600;")
        fm = QFontMetrics(name.font())
        kind = "文件夹" if ch.get("kind") == "dir" else "压缩包"
        name.setText(fm.elidedText(ch["name"], Qt.ElideMiddle, 320))
        h = STORE.progress(self.cid) or {}
        total = h.get("total") or 0
        page = (h.get("page") or 0) + 1 if total else 0
        meta = f"{kind} · {total} 页" if total else f"{kind} · 未读"
        if total:
            meta += f" · 读到 {page}/{total} · 已读 {h.get('count', 0)} 次 · {fmt_time(h.get('time', 0))}"
        sub = QLabel(meta)
        sub.setObjectName("Muted")
        v.addWidget(name)
        v.addWidget(sub)
        lay.addLayout(v, 1)

        # 进度条
        bar_host = QFrame()
        bar_host.setFixedSize(120, 6)
        bar_host.setStyleSheet("background:#E3E6EA;border-radius:3px;")
        self.bar = QFrame(bar_host)
        ratio = 0.0 if not total else min(1.0, page / total)
        self.bar.setGeometry(0, 0, int(120 * ratio), 6)
        color = "#2E9E5B" if h.get("finished") else ACCENT
        self.bar.setStyleSheet(f"background:{color};border-radius:3px;")
        lay.addWidget(bar_host)

        self.state = QLabel("已读完" if h.get("finished") else (f"{int(ratio*100)}%" if total else ""))
        self.state.setFixedWidth(48)
        self.state.setAlignment(Qt.AlignCenter)
        self.state.setStyleSheet(
            f"color:{'#2E9E5B' if h.get('finished') else '#8B93A1'};font-size:11px;")
        lay.addWidget(self.state)

        self._load_thumb()

    def _load_thumb(self):
        c = COVER_DIR / f"{self.cid}_420.jpg"
        if c.exists():
            pm = QPixmap(str(c)).scaled(30, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumb.setPixmap(pm)
        else:
            self.thumb.setText("📄")
            ASYNC.cover(self.ch["path"])

    def apply_cover(self, path: str):
        pm = QPixmap(path)
        if not pm.isNull():
            self.thumb.setText("")
            self.thumb.setPixmap(pm.scaled(30, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self.ch["path"], self.ch["name"], self.cid)
        elif e.button() == Qt.RightButton:
            self.context_menu.emit(self.cid, e.globalPosition().toPoint())
        super().mouseReleaseEvent(e)


class BookDetailPage(QWidget):
    """书详情：封面 + 书名 + 各话列表。"""

    back_requested = Signal()
    open_chapter = Signal(str, str, str)     # path, name, cid
    import_requested = Signal(str)           # bid
    rename_requested = Signal(str)           # bid
    cover_requested = Signal(str)            # bid
    changed = Signal()                       # 数据变了（让书架刷新）
    toast = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        self.bid = ""
        self._rows: dict[str, ChapterRow] = {}
        self._chapter_order: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        # ---- 顶部操作条 ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_back = QPushButton("← 书架")
        self.btn_back.setObjectName("Ghost")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self.back_requested)
        bar.addWidget(self.btn_back)
        bar.addStretch(1)
        self.btn_resume = QPushButton("继续阅读")
        self.btn_resume.setObjectName("Primary")
        self.btn_rename = QPushButton("重命名")
        self.btn_cover = QPushButton("封面")
        self.btn_import = QPushButton("＋ 导入话数")
        for b in (self.btn_rename, self.btn_cover, self.btn_import):
            b.setObjectName("Ghost")
        for b in (self.btn_resume, self.btn_rename, self.btn_cover, self.btn_import):
            b.setCursor(Qt.PointingHandCursor)
            bar.addWidget(b)
        root.addLayout(bar)

        # ---- 书信息卡 ----
        self.card = QFrame()
        self.card.setObjectName("Card")
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(16)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#E9ECF0;border-radius:8px;color:#9AA2AC;font-size:11px;")
        self.cover.setCursor(Qt.PointingHandCursor)
        self.cover.setToolTip("点击设置封面")
        self.cover.mouseReleaseEvent = lambda e: self.cover_requested.emit(self.bid) \
            if e.button() == Qt.LeftButton else None
        cl.addWidget(self.cover)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(6)
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("color:#1B1E23;font-size:19px;font-weight:700;")
        self.lbl_meta = QLabel("")
        self.lbl_meta.setObjectName("Muted")
        self.lbl_path = QLabel("")
        self.lbl_path.setObjectName("Muted")
        self.lbl_path.setWordWrap(True)
        self.pbar_host = QFrame()
        self.pbar_host.setFixedHeight(6)
        self.pbar_host.setStyleSheet("background:#E3E6EA;border-radius:3px;")
        self.pbar = QFrame(self.pbar_host)
        self.pbar.setGeometry(0, 0, 0, 6)
        self.pbar.setStyleSheet(f"background:{ACCENT};border-radius:3px;")
        info.addWidget(self.lbl_title)
        info.addWidget(self.lbl_meta)
        info.addWidget(self.pbar_host)
        info.addWidget(self.lbl_path)
        info.addStretch(1)
        cl.addLayout(info, 1)
        root.addWidget(self.card)

        # ---- 话列表 ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.lay = QVBoxLayout(self.host)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self.lay.addStretch(1)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        self.empty = QLabel("这本书还没有内容\n点右上角「＋ 导入话数」，或把 .cbz / 图片文件夹拖进来")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#9AA2AC;font-size:13px;line-height:180%;")
        root.addWidget(self.empty, 1)

        self.btn_resume.clicked.connect(self._resume)
        self.btn_import.clicked.connect(lambda: self.import_requested.emit(self.bid))
        self.btn_rename.clicked.connect(lambda: self.rename_requested.emit(self.bid))
        self.btn_cover.clicked.connect(lambda: self.cover_requested.emit(self.bid))
        ASYNC.sig.cover.connect(self._on_cover)

    # ================= 数据 =================
    def load(self, bid: str):
        self.bid = bid
        self.refresh()

    def book_title(self) -> str:
        return (STORE.book(self.bid) or {}).get("title", "")

    def refresh(self):
        b = STORE.book(self.bid)
        if not b:
            return
        st = STORE.book_stats(self.bid)
        self.lbl_title.setText(b["title"])
        self.lbl_meta.setText(
            f"共 {st['chapters']} 话 · 已读完 {st['finished']} 话 · "
            f"阅读 {st['times']} 次 · 最近 {fmt_time(st['last_time'])}")
        chs = STORE.chapters_of(self.bid)
        if chs:
            parent = Path(chs[0]["path"]).parent
            self.lbl_path.setText(f"来源目录：{parent}")
        else:
            self.lbl_path.setText("还没有导入内容")
        self.pbar.setGeometry(0, 0, int(self.pbar_host.width() * st["ratio"]) if chs else 0, 6)
        self.btn_resume.setEnabled(bool(chs))

        # 话列表
        while self.lay.count() > 1:
            it = self.lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        self._chapter_order = [c["id"] for c in chs]
        for i, ch in enumerate(chs, 1):
            row = ChapterRow(i, ch)
            row.activated.connect(self.open_chapter)
            row.context_menu.connect(self._menu)
            self.lay.insertWidget(self.lay.count() - 1, row)
            self._rows[ch["id"]] = row
        self.empty.setVisible(not chs)
        self.scroll.setVisible(bool(chs))
        self._load_cover()

    def _load_cover(self):
        cid, custom = STORE.book_cover_source(self.bid)
        custom_file = BOOKCOVER_DIR / f"{self.bid}.jpg"
        for p in ([custom] if custom else []) + [str(custom_file),
                                                 str(COVER_DIR / f"{cid}_420.jpg") if cid else ""]:
            if p and Path(p).exists():
                pm = QPixmap(p)
                if not pm.isNull():
                    self.cover.setText("")
                    self.cover.setPixmap(pm.scaled(COVER_W, COVER_H, Qt.KeepAspectRatio,
                                                   Qt.SmoothTransformation))
                    return
        self.cover.setPixmap(QPixmap())
        self.cover.setText("点此设置封面")
        if cid:
            ch = STORE.chapter(cid)
            if ch:
                ASYNC.cover(ch["path"])

    def _on_cover(self, cid: str, cover_path: str):
        row = self._rows.get(cid)
        if row:
            row.apply_cover(cover_path)
        target, _ = STORE.book_cover_source(self.bid)
        if cid == target:
            self._load_cover()

    def _resume(self):
        last = STORE.last_chapter(self.bid)
        if last:
            self.open_chapter.emit(last["path"], last["name"], last["id"])

    # ================= 一话的右键菜单 =================
    def _menu(self, cid: str, pos: QPoint):
        ch = STORE.chapter(cid)
        if not ch:
            return
        h = STORE.progress(cid) or {}
        m = QMenu(self)
        a_read = m.addAction(f"继续阅读（第 {(h.get('page', 0) or 0) + 1} 页）"
                             if h.get("total") else "阅读")
        a_cover = m.addAction("用作本书封面")
        m.addSeparator()
        a_done = m.addAction("标记已读")
        a_undone = m.addAction("标记未读")
        a_rename = m.addAction("重命名…")
        a_reveal = m.addAction("在文件夹中显示")
        m.addSeparator()
        a_out = m.addAction("移出这本书")
        a_del = m.addAction("删除文件（移入回收站）")
        chosen = m.exec(pos)
        if chosen is None:
            return
        if chosen == a_read:
            self.open_chapter.emit(ch["path"], ch["name"], cid)
        elif chosen == a_cover:
            STORE.set_book_cover(self.bid, f"cid:{cid}")
            STORE.save_all()
            self._load_cover()
            self.changed.emit()
            self.toast.emit(f"已把《{ch['name']}》设为封面")
        elif chosen == a_done:
            self._mark(cid, True)
        elif chosen == a_undone:
            self._mark(cid, False)
        elif chosen == a_rename:
            from .dialogs import PromptDialog
            new = PromptDialog.get_text(self, "重命名", "话名", ch["name"], placeholder="例如：第 12 话")
            if new:
                STORE.rename_chapter(cid, new)
                STORE.save_all()
                self.refresh()
                self.changed.emit()
        elif chosen == a_reveal:
            from .shelf import reveal_in_explorer
            reveal_in_explorer(ch["path"])
        elif chosen == a_out:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "移出这本书", f"把《{ch['name']}》移出本书？（不删除文件）",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                STORE.remove_chapter(cid)
                STORE.save_all()
                self.refresh()
                self.changed.emit()
                self.toast.emit("已移出（文件保留在磁盘）")
        elif chosen == a_del:
            from PySide6.QtWidgets import QMessageBox
            if QMessageBox.question(
                    self, "删除文件",
                    f"将文件移入回收站？\n\n{ch['name']}\n{ch['path']}\n\n（可从回收站还原）",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                if recycle_file(ch["path"]):
                    STORE.remove_chapter(cid)
                    STORE.save_all()
                    self.refresh()
                    self.changed.emit()
                    self.toast.emit("已移入回收站")
                else:
                    self.toast.emit("删除失败，文件可能被占用")

    def _mark(self, cid: str, done: bool):
        h = STORE.progress(cid) or {}
        total = h.get("total") or 0
        if not total:
            try:
                from .cbr import ComicSource
                ch = STORE.chapter(cid)
                if ch:
                    src = ComicSource(ch["path"])
                    total = src.page_count
                    src.close()
            except Exception:
                total = 0
        STORE.touch_history(cid, (STORE.chapter(cid) or {}).get("name", ""), 0, total)
        STORE.mark_finished(cid, done)
        STORE.save_all()
        self.refresh()
        self.changed.emit()

    def resizeEvent(self, e):
        st = STORE.book_stats(self.bid) if self.bid else {"ratio": 0}
        n = st.get("chapters", 0)
        self.pbar.setGeometry(0, 0, int(self.pbar_host.width() * st.get("ratio", 0)) if n else 0, 6)
        super().resizeEvent(e)


def recycle_file(path: str) -> bool:
    """移入回收站（不使用永久删除）。文件夹走递归回收。"""
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
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
    except Exception:
        return False
