"""主窗口：导航（书架 → 书详情 → 阅读器）、托盘、全局热键、桌面伪装、屏幕边缘小窗、导入。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMenu, QMessageBox, QProgressDialog,
                               QPushButton, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .book import BookDetailPage
from .camo import CamoOverlay
from .cbr import has_any_comic
from .dialogs import PromptDialog
from .edge import EdgePanel
from .hotkey import HotkeyManager
from .pages import HistoryPage, SettingsPage
from .reader import ReaderPage
from .shelf import ShelfPage
from .store import BOOKCOVER_DIR, STORE
from .tasks import ASYNC
from .theme import ACCENT, QSS
from .window import FramelessWindow, MARGIN

NAV = [("📚", "书架"), ("🕘", "历史"), ("⚙", "设置")]
DEMO_DIR = r"C:\Users\Arelq_\Desktop\各种bat脚本\manga_speace_ccb\O1"


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(ACCENT))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(6, 8, 52, 48, 8, 8)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(14, 6, 26, 52, 4, 4)
    p.setPen(QPen(QColor(ACCENT), 3))
    p.drawLine(20, 18, 34, 18)
    p.drawLine(20, 28, 34, 28)
    p.end()
    return QIcon(pm)


class MainWindow(FramelessWindow):
    def __init__(self):
        super().__init__("CBZ 阅读器", "本地漫画书库")
        self.setWindowTitle("CBZ 阅读器")
        self.setWindowIcon(make_icon())
        self.resize(1200, 780)
        self.setAcceptDrops(True)

        self._cur: dict = {}          # 当前阅读：{cid, path, name, bid, title}
        self._camo = False
        self._full = False
        self._import_bid: str | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1500)
        self._save_timer.timeout.connect(self._flush_history)
        self._import_dlg: QProgressDialog | None = None

        # ---------------- 内容区 ----------------
        row = QHBoxLayout(self.content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.rail = QFrame()
        self.rail.setObjectName("NavRail")
        self.rail.setFixedWidth(62)
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(6, 10, 6, 10)
        rl.setSpacing(6)
        self.nav_btns: list[QPushButton] = []
        for i, (icon, name) in enumerate(NAV):
            b = QPushButton(f"{icon}\n{name}")
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(52)
            b.clicked.connect(lambda _=False, idx=i: self.switch(idx))
            rl.addWidget(b)
            self.nav_btns.append(b)
        rl.addStretch(1)
        self.btn_camo_rail = QPushButton("🕶\n伪装")
        self.btn_camo_rail.setObjectName("NavBtn")
        self.btn_camo_rail.setCursor(Qt.PointingHandCursor)
        self.btn_camo_rail.setFixedHeight(52)
        self.btn_camo_rail.setToolTip("进入桌面伪装（热键同效）")
        self.btn_camo_rail.clicked.connect(self.toggle_camo)
        rl.addWidget(self.btn_camo_rail)
        row.addWidget(self.rail)

        self.stack = QStackedWidget()
        self.shelf_page = ShelfPage()
        self.history_page = HistoryPage()
        self.settings_page = SettingsPage()
        self.reader_page = ReaderPage()
        self.book_page = BookDetailPage()
        for w in (self.shelf_page, self.history_page, self.settings_page,
                  self.reader_page, self.book_page):
            self.stack.addWidget(w)
        row.addWidget(self.stack, 1)

        # ---------------- 接线 ----------------
        self.shelf_page.open_book.connect(self.open_book_detail)
        self.shelf_page.open_chapter.connect(self.open_chapter)
        self.shelf_page.new_book_requested.connect(self.ask_new_book)
        self.shelf_page.import_to_book.connect(self.ask_import_to_book)
        self.shelf_page.rename_book.connect(self.ask_rename_book)
        self.shelf_page.cover_requested.connect(self.ask_book_cover)
        self.shelf_page.toast.connect(self.toast)

        self.book_page.back_requested.connect(lambda: self.switch(0))
        self.book_page.open_chapter.connect(self.open_chapter)
        self.book_page.import_requested.connect(self.ask_import_to_book)
        self.book_page.rename_requested.connect(self.ask_rename_book)
        self.book_page.cover_requested.connect(self.ask_book_cover)
        self.book_page.changed.connect(self.shelf_page.refresh)
        self.book_page.toast.connect(self.toast)

        self.history_page.open_book.connect(self.open_chapter)
        self.history_page.toast.connect(self.toast)
        self.settings_page.toast.connect(self.toast)
        self.settings_page.hotkey_changed.connect(self._on_hotkey_changed)
        self.settings_page.opacity_changed.connect(self.set_window_opacity)
        self.settings_page.edge_changed.connect(self._on_edge_changed)
        self.reader_page.back_requested.connect(self.back_from_reader)
        self.reader_page.camo_requested.connect(self.toggle_camo)
        self.reader_page.fullscreen_requested.connect(self.toggle_fullscreen)
        self.reader_page.view.page_changed.connect(self._on_reader_progress)
        ASYNC.sig.import_progress.connect(self._on_import_progress)
        ASYNC.sig.import_done.connect(self._on_import_done)

        # ---------------- 屏幕边缘小窗 ----------------
        self.edge = EdgePanel()
        self.edge.open_book.connect(self.open_chapter)
        self.edge.show_main.connect(lambda: self.show_window(0))
        self.edge.state_changed.connect(self._on_edge_state)
        ASYNC.sig.cover.connect(self.edge.apply_cover)
        self._sync_edge_content(recent_only=True)

        # ---------------- 伪装层 ----------------
        self.camo = CamoOverlay(self.root)
        self.camo.hide()
        self.camo.unlock_requested.connect(self.toggle_camo)
        self.camo.apply_skin(STORE.cfg("camo.skin", "excel"))

        # ---------------- 提示条 ----------------
        self.toast_lbl = QLabel("", self)
        self.toast_lbl.setObjectName("Toast")
        self.toast_lbl.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast_lbl.hide)

        # ---------------- 热键 / 托盘 ----------------
        self.hotkeys = HotkeyManager(self)
        self.hotkeys.hide_toggle.connect(self.toggle_hide)
        self.hotkeys.camo_toggle.connect(self.toggle_camo)
        self.hotkeys.start({
            "hide": STORE.cfg("hotkey_hide", "ctrl+`"),
            "camo": STORE.cfg("hotkey_camo", "ctrl+shift+x"),
        })
        QTimer.singleShot(600, self._report_hotkey_state)

        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("CBZ 阅读器")
        tm = QMenu()
        a_show = tm.addAction("显示 / 隐藏窗口")
        a_show.triggered.connect(self.toggle_hide)
        a_shelf = tm.addAction("书架")
        a_shelf.triggered.connect(lambda: self.show_window(0))
        self.a_edge = tm.addAction("屏幕边缘小窗")
        self.a_edge.setCheckable(True)
        self.a_edge.setChecked(bool(STORE.cfg("edge.enabled", True)))
        self.a_edge.toggled.connect(self._toggle_edge_from_tray)
        a_camo = tm.addAction("桌面伪装")
        a_camo.triggered.connect(self.toggle_camo)
        tm.addSeparator()
        a_quit = tm.addAction("退出")
        a_quit.triggered.connect(self.quit_app)
        self.tray.setContextMenu(tm)
        self.tray.activated.connect(
            lambda r: self.toggle_hide() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

        self.title_bar.btn_cam.clicked.connect(self.toggle_camo)
        self.title_bar.btn_hide.clicked.connect(self.toggle_hide)
        self.title_bar.btn_cam.setToolTip(f"桌面伪装（{STORE.cfg('hotkey_camo', '')}）")
        self.title_bar.btn_hide.setToolTip(f"隐藏 / 恢复窗口（{STORE.cfg('hotkey_hide', '')}）")

        self.set_window_opacity(float(STORE.cfg("window.opacity", 1.0)))
        self.restore_geometry(STORE.cfg("window", {}) or {})
        self.switch(0)
        self.update_title()
        QTimer.singleShot(300, self._sync_edge)

    # ================= 导航 =================
    def switch(self, idx: int):
        if idx != 3 and self._full:
            self.toggle_fullscreen()
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.nav_btns):
            b.setChecked(i == idx or (idx == 4 and i == 0))
        if idx == 1:
            self.history_page.refresh()
        elif idx == 2:
            self.settings_page.refresh()
        elif idx == 0:
            self.shelf_page.refresh()
            self.update_title()

    def update_title(self, name: str = "", sub: str = ""):
        if self._camo:
            return
        if name:
            title = f"{name} — CBZ 阅读器"
            subtitle = sub or "本地漫画书库"
        else:
            title = "CBZ 阅读器 · 本地漫画书库"
            subtitle = "书 → 话 → 阅读"
        self.title_bar.set_meta(title, subtitle)
        self.setWindowTitle(title)

    # ================= 书 =================
    def open_book_detail(self, bid: str):
        b = STORE.book(bid)
        if not b:
            self.toast("这本书不存在了")
            self.shelf_page.refresh()
            return
        self.book_page.load(bid)
        self.stack.setCurrentWidget(self.book_page)
        for i, btn in enumerate(self.nav_btns):
            btn.setChecked(i == 0)
        self.update_title(b["title"], f"共 {STORE.book_stats(bid)['chapters']} 话")
        if STORE.book_stats(bid)["chapters"] == 0:
            self.toast("这本书还没有内容，点「＋ 导入话数」或直接把文件拖进来")

    def ask_new_book(self):
        title = PromptDialog.get_text(self, "新增书", "书名", "",
                                      ok_text="创建并导入", placeholder="例如：某科学的超电磁炮")
        if title is None:
            return
        bid = STORE.add_book(title)
        STORE.save_all()
        self.shelf_page.refresh()
        self.open_book_detail(bid)
        self.toast(f"已创建《{STORE.book(bid)['title']}》，接下来导入各话")
        QTimer.singleShot(120, lambda: self.ask_import_to_book(bid))

    def ask_rename_book(self, bid: str):
        b = STORE.book(bid)
        if not b:
            return
        new = PromptDialog.get_text(self, "重命名", "书名", b["title"])
        if new:
            STORE.rename_book(bid, new)
            STORE.save_all()
            self.shelf_page.refresh()
            if self.stack.currentWidget() is self.book_page:
                self.book_page.refresh()
                self.update_title(STORE.book(bid)["title"])
            self.toast("书名已更新")

    def ask_book_cover(self, bid: str):
        b = STORE.book(bid)
        if not b:
            return
        menu = QMenu(self)
        a_auto = menu.addAction("自动（首话首图）")
        chs = STORE.chapters_of(bid)
        a_pick = menu.addAction("用某一话作封面…") if chs else None
        a_file = menu.addAction("选择图片文件…")
        chosen = menu.exec(self.cursor().pos() if False else self.mapToGlobal(QPoint(0, 60)))
        if chosen is None:
            return
        if chosen == a_auto:
            STORE.set_book_cover(bid, "")
            STORE.save_all()
            self._refresh_covers()
            self.toast("封面已恢复为自动")
        elif a_pick and chosen == a_pick:
            m2 = QMenu(self)
            acts = {}
            for c in chs[:40]:
                acts[m2.addAction(c["name"])] = c["id"]
            picked = m2.exec(self.mapToGlobal(QPoint(0, 60)))
            if picked in acts:
                STORE.set_book_cover(bid, f"cid:{acts[picked]}")
                STORE.save_all()
                self._refresh_covers()
                self.toast("封面已更新")
        elif chosen == a_file:
            f, _ = QFileDialog.getOpenFileName(self, "选择封面图片", "",
                                               "图片 (*.jpg *.jpeg *.png *.webp *.bmp)")
            if f:
                try:
                    from PIL import Image
                    BOOKCOVER_DIR.mkdir(parents=True, exist_ok=True)
                    out = BOOKCOVER_DIR / f"{bid}.jpg"
                    im = Image.open(f)
                    if im.mode != "RGB":
                        im = im.convert("RGB")
                    im.save(out, "JPEG", quality=88)
                    STORE.set_book_cover(bid, "")
                    STORE.save_all()
                    self._refresh_covers()
                    self.toast("封面已更新")
                except Exception:
                    self.toast("封面设置失败，请换一张图片")

    def _refresh_covers(self):
        self.shelf_page.refresh()
        if self.stack.currentWidget() is self.book_page:
            self.book_page.refresh()

    # ================= 阅读 =================
    def open_chapter(self, path: str, name: str, cid: str = ""):
        if not Path(path).exists():
            self.toast("文件不存在，可能已被移动或删除")
            return
        cid = cid or ""
        if not cid:
            from .store import chapter_id
            cid = chapter_id(path)
            if cid not in STORE.chapters:
                STORE.add_chapter(self._book_for_path(path), path, name)
                STORE.save_all()
        h = STORE.progress(cid) or {}
        page, pos = int(h.get("page", 0) or 0), float(h.get("pos", 0.0) or 0.0)
        if h.get("finished"):
            page, pos = 0, 0.0
        ok = self.reader_page.open(path, name, page, pos)
        if not ok:
            self.toast("打开失败：文件损坏或内部没有图片")
            return
        ch = STORE.chapter(cid) or {}
        bid = ch.get("book", "")
        book_title = (STORE.book(bid) or {}).get("title", "") if bid else ""
        self._cur = {"cid": cid, "path": path, "name": name, "bid": bid, "title": book_title}
        total = self.reader_page.view.total
        STORE.touch_history(cid, name, self.reader_page.view.current, total, pos, count=True)
        STORE.save_all()
        self.stack.setCurrentWidget(self.reader_page)
        for b in self.nav_btns:
            b.setChecked(False)
        self.update_title(f"{book_title} · {name}" if book_title else name, "阅读中")
        self._sync_edge_content()
        self.toast(f"已打开 · 共 {total} 页" + (f" · 续读第 {page + 1} 页" if page else ""))

    def _book_for_path(self, path: str) -> str:
        """未登记的一话：挂到同目录的书，没有就新建一本。"""
        p = Path(path)
        for c in STORE.chapters.values():
            if Path(c.get("path", "")).parent == p.parent:
                return c.get("book", "")
        bid = STORE.add_book(p.parent.name or p.stem)
        return bid

    def back_from_reader(self):
        if self._full:
            self.toggle_fullscreen()
            return
        self._flush_history()
        cid = self._cur.get("cid", "")
        bid = (STORE.chapter(cid) or {}).get("book", "") if cid else ""
        self.reader_page.close_book()
        self._cur = {}
        self.update_title()
        if bid and STORE.book(bid):
            self.open_book_detail(bid)
        else:
            self.switch(0)

    def _on_reader_progress(self, idx: int, total: int, pos: float):
        if not self._cur:
            return
        STORE.touch_history(self._cur["cid"], self._cur["name"], idx, total, pos)
        if total and idx >= total - 1:
            single = self.reader_page.view.mode == "single"
            if single or pos > 0.85:
                STORE.mark_finished(self._cur["cid"], True)
        self.edge.set_progress(idx, total, self._cur.get("name", ""))
        self._save_timer.start()

    def _flush_history(self):
        if not self._cur:
            return
        STORE.save_all()
        cid = self._cur.get("cid", "")
        if self.stack.currentWidget() is self.book_page:
            self.book_page.refresh()
        self._sync_edge_content(recent_only=True)

    # ================= 导入 =================
    def ask_import_to_book(self, bid: str):
        b = STORE.book(bid)
        if not b:
            return
        menu = QMenu(self)
        a_files = menu.addAction("选择漫画文件（可多选 .cbz / .zip）")
        a_dir = menu.addAction("选择文件夹（自动识别各话）")
        a_ref = menu.addAction("引用文件夹（不复制，直接登记）")
        a_demo = menu.addAction("载入演示目录 O1（引用）")
        chosen = menu.exec(self.mapToGlobal(QPoint(0, 90)))
        if chosen is None:
            return
        if chosen == a_files:
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择漫画文件", "", "漫画 (*.cbz *.zip);;所有文件 (*)")
            if files:
                self.start_import(files, bid=bid)
        elif chosen == a_dir:
            d = QFileDialog.getExistingDirectory(self, "选择文件夹", str(Path.home() / "Desktop"))
            if d:
                self.start_import([d], bid=bid)
        elif chosen == a_ref:
            d = QFileDialog.getExistingDirectory(self, "选择要引用的文件夹",
                                                 str(Path.home() / "Desktop"))
            if d:
                self.start_import([d], bid=bid, copy=False)
        elif chosen == a_demo:
            if Path(DEMO_DIR).exists():
                self.start_import([DEMO_DIR], bid=bid, copy=False)
            else:
                self.toast("演示目录不存在")

    def ask_import_new_book(self):
        """一步到位：选中文件/文件夹 → 自动建成一本新书。"""
        menu = QMenu(self)
        a_files = menu.addAction("选择漫画文件（可多选）")
        a_dir = menu.addAction("选择文件夹（自动识别各话）")
        chosen = menu.exec(self.mapToGlobal(QPoint(0, 90)))
        if chosen is None:
            return
        if chosen == a_files:
            files, _ = QFileDialog.getOpenFileNames(
                self, "选择漫画文件", "", "漫画 (*.cbz *.zip);;所有文件 (*)")
            if files:
                self.start_import(files)
        elif chosen == a_dir:
            d = QFileDialog.getExistingDirectory(self, "选择文件夹", str(Path.home() / "Desktop"))
            if d:
                self.start_import([d])

    def start_import(self, sources: list[str], bid: str | None = None, copy: bool = True,
                     title: str | None = None):
        sources = [s for s in sources if has_any_comic(s)]
        if not sources:
            self.toast("没有可导入的漫画文件（支持 .cbz / .zip / 图片文件夹）")
            return
        if bid is None:
            guess = title or Path(sources[0]).name
            if guess.lower().endswith((".cbz", ".zip")):
                guess = Path(sources[0]).stem
            if len(sources) > 1:
                guess = title or Path(sources[0]).parent.name or guess
            bid = STORE.add_book(guess)
            STORE.save_all()
            self.shelf_page.refresh()
        self._import_bid = bid
        dest = Path(STORE.cfg("library_dir", ""))
        dest.mkdir(parents=True, exist_ok=True)
        self._import_dlg = QProgressDialog("正在扫描…", "取消", 0, 100, self)
        self._import_dlg.setWindowTitle(f"导入到《{STORE.book(bid)['title'] if STORE.book(bid) else ''}》")
        self._import_dlg.setWindowModality(Qt.WindowModal)
        self._import_dlg.setMinimumDuration(0)
        self._import_dlg.setAutoClose(False)
        self._import_dlg.canceled.connect(self._cancel_import)
        self._import_dlg.show()
        ASYNC.import_files(sources, dest, STORE.cfg("import.on_conflict", "skip"), copy)

    def _cancel_import(self):
        if self._import_dlg:
            self._import_dlg.close()
            self._import_dlg = None
        self.toast("已请求取消（进行中的复制会完成）")

    def _on_import_progress(self, i: int, total: int, name: str):
        dlg = self._import_dlg
        if dlg is None:
            return
        try:
            dlg.setLabelText(f"[{i}/{total}]  {name}")
            dlg.setMaximum(max(1, total))
            dlg.setValue(i)
        except RuntimeError:
            self._import_dlg = None

    def _on_import_done(self, records: list, skipped: list):
        if self._import_dlg:
            self._import_dlg.close()
            self._import_dlg = None
        bid = self._import_bid or ""
        self._import_bid = None
        for r in records:
            STORE.add_chapter(bid, r["path"], r["name"], r.get("kind", "file"),
                              r.get("size", 0), r.get("mtime", 0.0))
        STORE.save_all()
        self.shelf_page.refresh()
        b = STORE.book(bid)
        if b and self.stack.currentWidget() is self.book_page and self.book_page.bid == bid:
            self.book_page.refresh()
        total = STORE.book_stats(bid)["chapters"] if bid else 0
        msg = f"导入完成：新增 {len(records)} 话"
        if skipped:
            msg += f"，跳过 {len(skipped)} 个"
        if b:
            msg += f"　《{b['title']}》现有 {total} 话"
        self.toast(msg)
        if records and b:
            QTimer.singleShot(200, lambda: self.open_book_detail(bid))

    # ================= 拖拽 =================
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p and has_any_comic(p):
                paths.append(p)
        if not paths:
            return
        e.acceptProposedAction()
        on_book = self.stack.currentWidget() is self.book_page and self.book_page.bid
        if on_book:
            self.toast(f"导入到《{self.book_page.book_title()}》…")
            self.start_import(paths, bid=self.book_page.bid)
            return
        name = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} 个来源"
        if QMessageBox.question(self, "导入为新书",
                                f"把这些内容导入成一本新书？\n\n来源：{name}",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes) == QMessageBox.Yes:
            self.start_import(paths)

    # ================= 边缘小窗 =================
    def _sync_edge_content(self, recent_only: bool = False):
        if not recent_only and self._cur:
            self.edge.set_book(self._cur["path"], self._cur["name"], self._cur["cid"],
                               book_title=self._cur.get("title", ""))
        elif not self._cur:
            recent = STORE.recent_chapters(1)
            if recent:
                h = recent[0]
                self.edge.set_book(h["path"], h["name"], h["key"],
                                   book_title=h.get("book_title", ""))
                self.edge.set_progress(int(h.get("page", 0) or 0), int(h.get("total", 0) or 0),
                                       h["name"])
            else:
                self.edge.set_recent(None)
        self.edge.set_recent_list(STORE.recent_chapters(3))

    def _sync_edge(self):
        want = (bool(STORE.cfg("edge.enabled", True))
                and not self._camo and not self._full)
        self.edge.suspend(not want)
        if self.a_edge.isChecked() != bool(STORE.cfg("edge.enabled", True)):
            self.a_edge.blockSignals(True)
            self.a_edge.setChecked(bool(STORE.cfg("edge.enabled", True)))
            self.a_edge.blockSignals(False)

    def _toggle_edge_from_tray(self, on: bool):
        STORE.set_cfg("edge.enabled", bool(on))
        STORE.save_config()
        self.settings_page.refresh()
        self._sync_edge()
        self.toast("边缘小窗已开启" if on else "边缘小窗已关闭")

    def _on_edge_state(self, enabled: bool):
        if self.a_edge.isChecked() != enabled:
            self.a_edge.blockSignals(True)
            self.a_edge.setChecked(enabled)
            self.a_edge.blockSignals(False)
        self.settings_page.refresh()

    def _on_edge_changed(self, cfg: dict):
        if "side" in cfg:
            self.edge.set_side(cfg["side"])
        if "shape" in cfg:
            self.edge.set_shape(cfg["shape"])
        if "auto_peek" in cfg:
            self.edge.set_auto_peek(cfg["auto_peek"])
        STORE.save_config()
        self._sync_edge()
        self.toast("边缘小窗设置已应用")

    # ================= 伪装 / 隐藏 / 全屏 =================
    def toggle_camo(self):
        self._camo = not self._camo
        if self._camo:
            self.camo.apply_skin(STORE.cfg("camo.skin", "excel"))
            self.camo.setGeometry(self.root.rect())
            self.camo.raise_()
            self.camo.show()
            self.camo.setFocus()
            self._apply_camo_title(True)
            if STORE.cfg("camo.hide_in_taskbar", True):
                self._set_taskbar_visible(False)
            self.tray.setToolTip("工作簿1.xlsx - Excel")
            self.toast_lbl.hide()
        else:
            self.camo.hide()
            self._apply_camo_title(False)
            if STORE.cfg("camo.hide_in_taskbar", True):
                self._set_taskbar_visible(True)
            self.tray.setToolTip("CBZ 阅读器")
            self.update_title(self.reader_page.book_name() if self._cur else "")
            self.toast("已退出伪装")
        self._sync_edge()

    def _apply_camo_title(self, on: bool):
        if on:
            skin = STORE.cfg("camo.skin", "excel")
            cfg_key = {"excel": "camo.excel_title", "word": "camo.word_title",
                       "term": "camo.term_title"}.get(skin, "camo.excel_title")
            self.setWindowTitle(STORE.cfg(cfg_key, "Microsoft Excel - 工作簿1.xlsx"))
        else:
            self.setWindowTitle("CBZ 阅读器")

    def _set_taskbar_visible(self, visible: bool):
        try:
            geo = self.geometry()
            flags = self.windowFlags()
            flags = (flags & ~Qt.Tool) if visible else (flags | Qt.Tool)
            self.setWindowFlags(flags)
            self.show()
            self.setGeometry(geo)
            if self._camo:
                self.camo.setGeometry(self.root.rect())
                self.camo.raise_()
                self.camo.show()
                self.camo.setFocus()
        except Exception:
            pass

    def show_window(self, idx: int | None = None):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if idx is not None:
            self.switch(idx)

    def toggle_hide(self):
        if self.isVisible() and not self.isMinimized():
            self._flush_history()
            self.hide()
            if self.tray.supportsMessages():
                self.tray.showMessage("CBZ 阅读器", "窗口已隐藏，按热键恢复",
                                      QSystemTrayIcon.Information, 1500)
        else:
            self.show_window()

    def toggle_fullscreen(self):
        self._full = not self._full
        if self._full:
            self._geo_before_full = self.geometry()
            self._outer_margins = self.layout().contentsMargins()
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.set_radius(0)
            self.title_bar.hide()
            self.rail.hide()
            self.showFullScreen()
        else:
            self.showNormal()
            m = self._outer_margins
            self.layout().setContentsMargins(m.left(), m.top(), m.right(), m.bottom())
            self.set_radius(10)
            self.title_bar.show()
            self.rail.show()
            if hasattr(self, "_geo_before_full"):
                self.setGeometry(self._geo_before_full)
        self.reader_page.set_fullscreen(self._full)
        self._sync_edge()

    def quit_app(self):
        self._flush_history()
        self.hotkeys.stop()
        ASYNC.wait(1500)
        STORE.set_cfg("window", self.geo_dict())
        STORE.set_cfg("window.opacity", self._opacity)
        STORE.save_all()
        self.edge.shutdown()
        self.tray.hide()
        QApplication.instance().quit()

    # ================= 热键状态 =================
    def _on_hotkey_changed(self, action: str, spec: str):
        failed = self.hotkeys.rebind({
            "hide": STORE.cfg("hotkey_hide", ""),
            "camo": STORE.cfg("hotkey_camo", ""),
        })
        ok = action not in failed
        self.settings_page.set_hotkey_state(action, ok, spec)
        self.toast(f"热键已更新：{spec}" if ok else "热键注册失败，可能被占用")

    def _report_hotkey_state(self):
        failed = self.hotkeys.failed
        self.settings_page.set_hotkey_state("hide", "hide" not in failed, "")
        if failed:
            self.toast("部分全局热键被占用，可在「设置」里修改")

    # ================= 提示条 =================
    def toast(self, text: str):
        if self._camo:
            return
        self.toast_lbl.setText(text)
        self.toast_lbl.adjustSize()
        self.toast_lbl.move((self.width() - self.toast_lbl.width()) // 2, self.height() - 92)
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self._toast_timer.start(2800)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.camo.isVisible():
            self.camo.setGeometry(self.root.rect())
        if self.toast_lbl.isVisible():
            self.toast_lbl.move((self.width() - self.toast_lbl.width()) // 2,
                                self.height() - 92)

    def keyPressEvent(self, e):
        k, m = e.key(), e.modifiers()
        if m & Qt.AltModifier and k in (Qt.Key_1, Qt.Key_2, Qt.Key_3):
            self.switch({Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2}[k])
        elif m & Qt.ControlModifier and k == Qt.Key_F:
            self.switch(0)
            self.shelf_page.search.setFocus()
            self.shelf_page.search.selectAll()
        elif k == Qt.Key_Escape and self._camo:
            self.toggle_camo()
        else:
            super().keyPressEvent(e)
            return
        e.accept()

    def closeEvent(self, e):
        self._flush_history()
        self.hotkeys.stop()
        STORE.set_cfg("window", self.geo_dict())
        STORE.set_cfg("window.opacity", self._opacity)
        STORE.save_all()
        self.edge.shutdown()
        self.tray.hide()
        super().closeEvent(e)
