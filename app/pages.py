"""历史记录页 + 设置页。"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from .hotkey import parse_hotkey
from .imgutil import cover_pixmap
from .window import Selector, Toggle
from .store import APP_DIR, DATA_DIR, STORE
from .tasks import ASYNC
from . import theme


def _nz(state) -> bool:
    """Qt 勾选状态 → bool。"""
    return bool(state)


def fmt_time(ts: float) -> str:
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 60:
        return "刚刚"
    if d < 3600:
        return f"{int(d // 60)} 分钟前"
    if d < 86400:
        return f"{int(d // 3600)} 小时前"
    if d < 86400 * 7:
        return f"{int(d // 86400)} 天前"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class StatCard(QFrame):
    def __init__(self, value: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.lbl_v = QLabel(value)
        self.lbl_v.setObjectName("StatNum")
        self.lbl_l = QLabel(label)
        self.lbl_l.setObjectName("StatLbl")
        lay.addWidget(self.lbl_v)
        lay.addWidget(self.lbl_l)

    def set_value(self, v: str):
        self.lbl_v.setText(v)


class HistoryRow(QFrame):
    resume = Signal(str, str, str)
    remove = Signal(str)

    def __init__(self, h: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(74)
        self._key = h["key"]
        self._path = h.get("path", "")
        self._name = h.get("name", "")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(12)

        self.thumb = QLabel()
        self.thumb.setFixedSize(40, 56)
        self.thumb.setObjectName("CoverBox")
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)
        self._load_thumb()

        info = QWidget()
        v = QVBoxLayout(info)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        name = QLabel()
        name.setObjectName("CardTitle")
        fm = QFontMetrics(name.font())
        label = f"{h.get('book_title')} · {self._name}" if h.get("book_title") else self._name
        name.setText(fm.elidedText(label, Qt.ElideMiddle, 400))
        total = h.get("total", 0) or 0
        page = (h.get("page", 0) or 0) + 1
        ratio = 0.0 if not total else min(1.0, page / total)
        sub = QLabel(f"第 {page}/{total} 页 · 阅读 {h.get('count', 0)} 次 · {fmt_time(h.get('time', 0))}"
                     + ("  · 已读完" if h.get("finished") else ""))
        sub.setObjectName("Muted")
        bar = QFrame()
        bar.setFixedHeight(4)
        theme.style(bar, "background:$border;border-radius:2px;")
        bin_ = QFrame(bar)
        bin_.setGeometry(0, 0, int(240 * ratio), 4)
        theme.now(bin_, "background:$accent;border-radius:2px;")
        bar.setFixedWidth(240)
        v.addWidget(name)
        v.addWidget(sub)
        v.addWidget(bar)
        lay.addWidget(info, 1)

        b1 = QPushButton("继续阅读")
        b1.setObjectName("Primary")
        b1.setFixedWidth(100)
        b1.setCursor(Qt.PointingHandCursor)
        b1.clicked.connect(lambda: self.resume.emit(self._path, self._name, self._key))
        b2 = QPushButton("移除记录")
        b2.setObjectName("Ghost")
        b2.setFixedWidth(94)
        b2.setCursor(Qt.PointingHandCursor)
        b2.clicked.connect(lambda: self.remove.emit(self._key))
        lay.addWidget(b1)
        lay.addWidget(b2)

    def _load_thumb(self):
        from .store import COVER_DIR
        c = COVER_DIR / f"{self._key}_420.jpg"
        if c.exists():
            pm = cover_pixmap(QPixmap(str(c)), 40, 56, theme.radius_px() - 2,
                              self.devicePixelRatioF())
            self.thumb.setPixmap(pm)
        else:
            self.thumb.setText("📕")
            ASYNC.cover(self._path, 420)


class HistoryPage(QWidget):
    open_book = Signal(str, str, str)
    toast = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel("阅读历史")
        t.setObjectName("SectionTitle")
        head.addWidget(t)
        head.addStretch(1)
        b_clear = QPushButton("清空历史")
        b_clear.setObjectName("Danger")
        b_clear.setCursor(Qt.PointingHandCursor)
        b_clear.clicked.connect(self._clear)
        head.addWidget(b_clear)
        root.addLayout(head)

        self.stats = QHBoxLayout()
        self.stats.setSpacing(10)
        self.s1 = StatCard("0", "在读书籍")
        self.s2 = StatCard("0", "已读完")
        self.s3 = StatCard("0", "总阅读次数")
        self.s4 = StatCard("0", "累计页数")
        for s in (self.s1, self.s2, self.s3, self.s4):
            self.stats.addWidget(s)
        root.addLayout(self.stats)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.lay = QVBoxLayout(self.host)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.lay.addStretch(1)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        self.empty = QLabel("还没有阅读记录 —— 打开一本书就会自动记录进度")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("EmptyState")
        root.addWidget(self.empty, 1)

        ASYNC.sig.cover.connect(lambda *_: self.refresh() if self.isVisible() else None)
        self.refresh()

    def refresh(self):
        while self.lay.count() > 1:
            it = self.lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        items = STORE.recent_chapters(200)
        for h in items:
            row = HistoryRow(h)
            row.resume.connect(self.open_book)
            row.remove.connect(self._remove_one)
            self.lay.insertWidget(self.lay.count() - 1, row)

        books = STORE.book_list()
        read_books = sum(1 for b in books if b["stats"]["read"])
        finished = sum(b["stats"]["finished"] for b in books)
        times = sum(b["stats"]["times"] for b in books)
        pages = 0
        for b in books:
            for c in STORE.chapters_of(b["id"]):
                h = STORE.progress(c["id"]) or {}
                if h.get("finished"):
                    pages += int(h.get("total", 0) or 0)
        self.s1.set_value(str(read_books))
        self.s2.set_value(str(finished))
        self.s3.set_value(str(times))
        self.s4.set_value(str(pages))
        self.empty.setVisible(not items)
        self.scroll.setVisible(bool(items))
        self.s1.lbl_l.setText(f"在读书籍 / 共 {len(books)} 本")

    def _remove_one(self, key: str):
        STORE.history.pop(key, None)
        STORE.save_all()
        self.toast.emit("已移除该条记录")
        self.refresh()

    def _clear(self):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "清空历史", "清空全部阅读历史记录？（不影响书架与文件）",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            STORE.clear_history()
            STORE.save_all()
            self.toast.emit("历史记录已清空")
            self.refresh()


class KeyCapture(QLineEdit):
    """热键录制输入框。"""

    changed = Signal(str)

    def __init__(self, spec: str, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按下组合键")
        self.setFixedWidth(190)
        self.setText(spec)
        self.setCursor(Qt.PointingHandCursor)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_unknown):
            return
        if k in (Qt.Key_Backspace, Qt.Key_Delete):
            self.setText("")
            self.changed.emit("")
            return
        mods = []
        m = e.modifiers()
        if m & Qt.ControlModifier:
            mods.append("ctrl")
        if m & Qt.AltModifier:
            mods.append("alt")
        if m & Qt.ShiftModifier:
            mods.append("shift")
        if m & Qt.MetaModifier:
            mods.append("win")
        key = ""
        fkeys = {getattr(Qt, f"Key_F{i}"): f"f{i}" for i in range(1, 25)}
        if k in fkeys:
            key = fkeys[k]
        elif e.text() and e.text().isprintable():
            t = e.text().lower()
            key = "space" if t == " " else t
        if not key:
            return
        if not mods and not key.startswith("f"):
            self.setText("需带 Ctrl/Alt/Win 修饰键")
            return
        spec = "+".join(mods + [key])
        self.setText(spec)
        self.changed.emit(spec)
        e.accept()


class SettingsPage(QWidget):
    toast = Signal(str)
    hotkey_changed = Signal(str, str)
    opacity_changed = Signal(float)
    edge_changed = Signal(dict)
    close_action_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 12)
        outer.setSpacing(10)
        head = QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(1)
        t = QLabel("设置")
        t.setObjectName("SectionTitle")
        sub = QLabel("外观（主题 / 强调色 / 圆角 / 字号）在左侧「个性化」页，这里管功能与行为")
        sub.setObjectName("PageSub")
        head.addWidget(t)
        head.addWidget(sub)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        # ---- 热键与隐藏 ----
        g1, b1 = self._group(lay, "热键与隐藏")
        row = QHBoxLayout()
        row.addWidget(self._lbl("隐藏 / 恢复窗口"))
        self.kp_hide = KeyCapture(STORE.cfg("hotkey_hide", "ctrl+`"))
        self.kp_hide.changed.connect(lambda s: self._save_hotkey("hotkey_hide", "hide", s))
        row.addWidget(self.kp_hide)
        self.lbl_hide_state = QLabel("")
        self.lbl_hide_state.setObjectName("Muted")
        row.addWidget(self.lbl_hide_state)
        row.addStretch(1)
        b1.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._lbl("桌面伪装 开 / 关"))
        self.kp_camo = KeyCapture(STORE.cfg("hotkey_camo", "ctrl+shift+x"))
        self.kp_camo.changed.connect(lambda s: self._save_hotkey("hotkey_camo", "camo", s))
        row.addWidget(self.kp_camo)
        row.addStretch(1)
        b1.addLayout(row)

        b1.addWidget(self._hint("隐藏窗口后仍在托盘中，按同一热键恢复。伪装状态下再次按热键即可解除"
                                "（也可连点窗口右下角三次）。"))

        # ---- 阅读 ----
        _g2, b2 = self._group(lay, "阅读默认")
        row = QHBoxLayout()
        row.addWidget(self._lbl("默认阅读方向"))
        self.cmb_dir = Selector()
        self.cmb_dir.addItems(["从左到右", "从右到左（日漫）"])
        self.cmb_dir.setCurrentIndex(1 if STORE.cfg("reader.rtl") else 0)
        self.cmb_dir.currentIndexChanged.connect(
            lambda i: (STORE.set_cfg("reader.rtl", i == 1), STORE.save_config()))
        row.addWidget(self.cmb_dir)
        row.addSpacing(20)
        row.addWidget(self._lbl("默认模式"))
        self.cmb_mode = Selector()
        self.cmb_mode.addItems(["连续滚动", "单页翻页"])
        self.cmb_mode.setCurrentIndex(0 if STORE.cfg("reader.mode") == "scroll" else 1)
        self.cmb_mode.currentIndexChanged.connect(
            lambda i: (STORE.set_cfg("reader.mode", "scroll" if i == 0 else "single"), STORE.save_config()))
        row.addWidget(self.cmb_mode)
        row.addStretch(1)
        b2.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._lbl("阅读背景"))
        self.cmb_bg = Selector()
        for name, color in (("深灰（默认）", "#101216"), ("纯黑", "#000000"),
                            ("墨蓝", "#0E1420"), ("暖白", "#F2EFE9"), ("米黄", "#EFE6D0")):
            self.cmb_bg.addItem(name, color)
        cur = STORE.cfg("reader.bg", "#101216")
        idx = max(0, self.cmb_bg.findData(cur))
        self.cmb_bg.setCurrentIndex(idx)
        self.cmb_bg.currentIndexChanged.connect(self._save_bg)
        row.addWidget(self.cmb_bg)
        row.addSpacing(20)
        row.addWidget(self._lbl("工具条自动隐藏"))
        self.chk_autohide = Toggle()
        self.chk_autohide.setChecked(bool(STORE.cfg("reader_ui.auto_hide_toolbar", True)))
        self.chk_autohide.stateChanged.connect(
            lambda s: (STORE.set_cfg("reader_ui.auto_hide_toolbar", bool(s)), STORE.save_config()))
        row.addWidget(self.chk_autohide)
        row.addStretch(1)
        b2.addLayout(row)

        # ---- 伪装 ----
        _g3, b3 = self._group(lay, "桌面伪装")
        row = QHBoxLayout()
        row.addWidget(self._lbl("伪装外观"))
        self.cmb_camo = Selector()
        self.cmb_camo.addItem("Excel 表格", "excel")
        self.cmb_camo.addItem("Word 文档", "word")
        self.cmb_camo.addItem("CMD 终端", "term")
        self.cmb_camo.setCurrentIndex(max(0, self.cmb_camo.findData(STORE.cfg("camo.skin", "excel"))))
        self.cmb_camo.currentIndexChanged.connect(self._save_camo)
        row.addWidget(self.cmb_camo)
        row.addSpacing(20)
        row.addWidget(self._lbl("伪装时从任务栏隐藏"))
        self.chk_tb = Toggle()
        self.chk_tb.setChecked(bool(STORE.cfg("camo.hide_in_taskbar", True)))
        self.chk_tb.stateChanged.connect(
            lambda s: (STORE.set_cfg("camo.hide_in_taskbar", bool(s)), STORE.save_config()))
        row.addWidget(self.chk_tb)
        row.addStretch(1)
        b3.addLayout(row)
        b3.addWidget(self._hint("伪装时窗口标题会同步改为对应的应用名；解锁方式：热键，或连点窗口右下角 3 次。"))

        # ---- 窗口 ----
        _g4, b4 = self._group(lay, "窗口")
        row = QHBoxLayout()
        row.addWidget(self._lbl("窗口不透明度"))
        self.sld_op = QSlider(Qt.Horizontal)
        self.sld_op.setRange(40, 100)
        self.sld_op.setValue(int(float(STORE.cfg("window.opacity", 1.0)) * 100))
        self.sld_op.setFixedWidth(200)
        self.lbl_op = QLabel(f"{self.sld_op.value()}%")
        self.lbl_op.setFixedWidth(46)
        self.sld_op.valueChanged.connect(self._save_opacity)
        row.addWidget(self.sld_op)
        row.addWidget(self.lbl_op)
        row.addSpacing(18)
        row.addWidget(self._lbl("关闭窗口时"))
        self.cmb_close = Selector()
        self.cmb_close.addItem("每次询问", "ask")
        self.cmb_close.addItem("关闭软件", "quit")
        self.cmb_close.addItem("最小化到托盘", "tray")
        self.cmb_close.setCurrentIndex(
            {"ask": 0, "quit": 1, "tray": 2}.get(STORE.cfg("window.close_action", "ask"), 0))
        self.cmb_close.currentIndexChanged.connect(
            lambda i: self.close_action_changed.emit(self.cmb_close.currentData()))
        row.addWidget(self.cmb_close)
        row.addStretch(1)
        b4.addLayout(row)
        b4.addWidget(self._hint("按住窗口任意边缘可自由缩放；拖住标题栏任意位置可移动；双击标题栏最大化。"
                                "「关闭窗口时」可选每次询问、直接退出、或最小化到托盘继续后台运行。"))

        # ---- 屏幕边缘小窗 ----
        _g6, b6 = self._group(lay, "边缘迷你阅读器")
        row = QHBoxLayout()
        row.addWidget(self._lbl("启用"))
        self.chk_edge = Toggle()
        self.chk_edge.setChecked(bool(STORE.cfg("edge.enabled", True)))
        self.chk_edge.stateChanged.connect(lambda s: self._emit_edge({"enabled": _nz(s)}))
        row.addWidget(self.chk_edge)
        row.addSpacing(18)
        row.addWidget(self._lbl("停靠位置"))
        self.cmb_edge_side = Selector()
        self.cmb_edge_side.addItem("屏幕右侧", "right")
        self.cmb_edge_side.addItem("屏幕左侧", "left")
        self.cmb_edge_side.setCurrentIndex(0 if STORE.cfg("edge.side", "right") == "right" else 1)
        self.cmb_edge_side.currentIndexChanged.connect(
            lambda i: self._emit_edge({"side": self.cmb_edge_side.currentData()}))
        row.addWidget(self.cmb_edge_side)
        row.addStretch(1)
        b6.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._lbl("收起形态"))
        self.cmb_edge_shape = Selector()
        self.cmb_edge_shape.addItem("细缝（6px，最隐蔽）", "sliver")
        self.cmb_edge_shape.addItem("窄条（40px，好点中）", "strip")
        self.cmb_edge_shape.setCurrentIndex(0 if STORE.cfg("edge.shape", "sliver") == "sliver" else 1)
        self.cmb_edge_shape.currentIndexChanged.connect(
            lambda i: self._emit_edge({"shape": self.cmb_edge_shape.currentData()}))
        row.addWidget(self.cmb_edge_shape)
        row.addSpacing(18)
        row.addWidget(self._lbl("边缘感应"))
        self.chk_edge_peek = Toggle()
        self.chk_edge_peek.setChecked(bool(STORE.cfg("edge.auto_peek", True)))
        self.chk_edge_peek.stateChanged.connect(
            lambda s: self._emit_edge({"auto_peek": _nz(s)}))
        row.addWidget(self.chk_edge_peek)
        row.addStretch(1)
        b6.addLayout(row)
        b6.addWidget(self._hint(
            "贴在屏幕边缘的隐蔽式小阅读器：平时只是一条细缝，鼠标碰到屏幕边缘即滑出当前页，"
            "滚轮或点击左右两侧翻页，Ctrl+滚轮调整阅读窗大小，鼠标离开立即缩回；双击页面在主窗口打开当前页。"
            "右键可切换左右停靠 / 细缝或窄条 / 边缘感应。开启桌面伪装或全屏阅读时自动隐身。"))

        # ---- 库与数据 ----
        _g5, b5 = self._group(lay, "书库与数据")
        row = QHBoxLayout()
        self.lbl_lib = QLabel(STORE.cfg("library_dir", ""))
        self.lbl_lib.setObjectName("Muted")
        self.lbl_lib.setWordWrap(True)
        row.addWidget(self.lbl_lib, 1)
        b_open_lib = QPushButton("打开目录")
        b_open_lib.setObjectName("Ghost")
        b_open_lib.clicked.connect(lambda: self._open_dir(STORE.cfg("library_dir", "")))
        b_chg_lib = QPushButton("更改目录")
        b_chg_lib.setObjectName("Ghost")
        b_chg_lib.clicked.connect(self._change_lib)
        for b in (b_open_lib, b_chg_lib):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        b5.addLayout(row)

        row = QHBoxLayout()
        b_data = QPushButton("打开数据目录")
        b_data.setObjectName("Ghost")
        b_data.setCursor(Qt.PointingHandCursor)
        b_data.clicked.connect(lambda: self._open_dir(str(DATA_DIR)))
        b_reset = QPushButton("恢复默认设置")
        b_reset.setObjectName("Danger")
        b_reset.setCursor(Qt.PointingHandCursor)
        b_reset.clicked.connect(self._reset)
        row.addWidget(b_data)
        row.addWidget(b_reset)
        row.addStretch(1)
        b5.addLayout(row)

        lay.addStretch(1)

    # ---------- 组件 ----------
    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("FormLabel")
        l.setMinimumWidth(130)
        return l

    @staticmethod
    def _hint(text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("Muted")
        l.setWordWrap(True)
        return l

    @staticmethod
    def _group(parent: QVBoxLayout, title: str):
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("GroupTitle")
        v.addWidget(t)
        parent.addWidget(card)
        return card, v

    # ---------- 回调 ----------
    def _save_bg(self, _i):
        STORE.set_cfg("reader.bg", self.cmb_bg.currentData())
        STORE.save_config()
        self.toast.emit("阅读背景已保存（对当前阅读器立即生效）")

    def _save_camo(self, _i):
        STORE.set_cfg("camo.skin", self.cmb_camo.currentData())
        STORE.save_config()
        self.toast.emit("伪装外观已切换")

    def _save_opacity(self, v: int):
        self.lbl_op.setText(f"{v}%")
        STORE.set_cfg("window.opacity", v / 100.0)
        STORE.save_config()
        self.opacity_changed.emit(v / 100.0)

    def _save_hotkey(self, cfg_key: str, action: str, spec: str):
        if spec and not parse_hotkey(spec):
            self.toast.emit("热键格式无效")
            return
        STORE.set_cfg(cfg_key, spec)
        STORE.save_config()
        self.hotkey_changed.emit(action, spec)

    def set_hotkey_state(self, action: str, ok: bool, spec: str):
        if action == "hide":
            self.lbl_hide_state.setText("已生效" if ok else "注册失败，可能被其它程序占用")
            theme.now(self.lbl_hide_state, "color:%s;font-size:%s;"
                      % (theme.c("ok" if ok else "danger"), theme.px(11)))

    def _open_dir(self, path: str):
        try:
            if not path or not Path(path).exists():
                self.toast.emit("目录不存在")
                return
            if os.name == "nt":
                os.startfile(path)          # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            self.toast.emit("无法打开目录")

    def _change_lib(self):
        d = QFileDialog.getExistingDirectory(self, "选择书库目录", STORE.cfg("library_dir", ""))
        if d:
            STORE.set_cfg("library_dir", d)
            STORE.save_config()
            self.lbl_lib.setText(d)
            self.toast.emit("书库目录已更新")

    def _reset(self):
        from .store import DEFAULTS
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "恢复默认", "恢复全部设置为默认值？（书架与历史不受影响）",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            keep = STORE.config.get("library_dir")
            STORE.config.clear()
            STORE.config.update({k: v for k, v in DEFAULTS.items()})
            if keep:
                STORE.config["library_dir"] = keep
            STORE.save_config()
            self.toast.emit("已恢复默认设置，重启生效")

    def _emit_edge(self, d: dict):
        for k, v in d.items():
            STORE.set_cfg(f"edge.{k}", v)
        STORE.save_config()
        self.edge_changed.emit(d)

    def refresh(self):
        self.lbl_lib.setText(STORE.cfg("library_dir", ""))
        pairs = ((self.chk_edge, bool(STORE.cfg("edge.enabled", True))),
                 (self.chk_edge_peek, bool(STORE.cfg("edge.auto_peek", True))))
        for wdg, val in pairs:
            wdg.blockSignals(True)
            wdg.setChecked(val)
            wdg.blockSignals(False)
        self.cmb_edge_side.blockSignals(True)
        self.cmb_edge_side.setCurrentIndex(0 if STORE.cfg("edge.side", "right") == "right" else 1)
        self.cmb_edge_side.blockSignals(False)
        self.cmb_edge_shape.blockSignals(True)
        self.cmb_edge_shape.setCurrentIndex(0 if STORE.cfg("edge.shape", "sliver") == "sliver" else 1)
        self.cmb_edge_shape.blockSignals(False)
        if hasattr(self, "cmb_close"):
            self.cmb_close.blockSignals(True)
            self.cmb_close.setCurrentIndex(
                {"ask": 0, "quit": 1, "tray": 2}.get(STORE.cfg("window.close_action", "ask"), 0))
            self.cmb_close.blockSignals(False)
