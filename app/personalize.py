"""个性化页：主题画廊 / 强调色 / 圆角 / 字号，改完立即生效。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from . import theme
from .layout import PageHeader, content_column

CARD_W, CARD_H = 280, 184


class ThemeCard(QFrame):
    """一张主题预览卡：直接按该主题真实配色绘制一个迷你界面。"""

    picked = Signal(str)

    def __init__(self, tid: str, parent=None):
        super().__init__(parent)
        self.tid = tid
        self._active = False
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        m = theme.THEMES[tid]
        self.setToolTip(f"{m['name']} · {m['tag']}")

    def set_active(self, on: bool):
        if self._active != on:
            self._active = on
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(CARD_W, CARD_H)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.tid)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        m = theme.THEMES[self.tid]
        acc = theme.ACCENTS[theme.current()["accent"]]["hex"] if theme.current()["accent"] else m["accent"]
        border2 = theme.mix(m["border"], m["text"], 0.20)
        surface3 = theme.mix(m["surface"], m["text"], 0.05)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        outer = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(acc if self._active else m["border"]), 2 if self._active else 1))
        p.setBrush(QColor(m["bg"]))
        p.drawRoundedRect(outer, 12, 12)

        # ---- 迷你窗口 ----
        win = QRect(14, 14, CARD_W - 28, CARD_H - 80)
        p.setPen(QPen(QColor(m["border"]), 1))
        p.setBrush(QColor(m["surface"]))
        p.drawRoundedRect(win, 8, 8)

        # 侧边导航
        rail = QRect(win.x() + 1, win.y() + 1, 12, win.height() - 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(m["surface2"]))
        p.drawRoundedRect(rail, 7, 7)
        p.setBrush(QColor(acc))
        p.drawRoundedRect(QRect(rail.x() + 3, rail.y() + 8, 6, 16), 3, 3)
        p.setBrush(QColor(border2))
        for i in range(2):
            p.drawRoundedRect(QRect(rail.x() + 3, rail.y() + 30 + i * 12, 6, 6), 3, 3)

        # 标题条 + 搜索框
        p.setBrush(QColor(m["surface2"]))
        p.drawRoundedRect(QRect(win.x() + 20, win.y() + 9, 54, 7), 3, 3)
        p.setBrush(QColor(surface3))
        p.setPen(QPen(QColor(m["border"]), 1))
        p.drawRoundedRect(QRect(win.right() - 62, win.y() + 8, 52, 9), 4, 4)

        # 两本书的封面
        p.setPen(QPen(QColor(m["border"]), 1))
        for i in range(2):
            cx = win.x() + 20 + i * 46
            p.setBrush(QColor(m["surface2"]))
            p.drawRoundedRect(QRect(cx, win.y() + 26, 36, 48), 4, 4)
            p.setBrush(QColor(acc if i == 0 else border2))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRect(cx, win.y() + 68, 36, 3), 1, 1)
            p.setPen(QPen(QColor(m["border"]), 1))
        # 文字行
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(border2))
        p.drawRoundedRect(QRect(win.x() + 20, win.y() + 80, 116, 5), 2, 2)
        p.setBrush(QColor(acc))
        p.drawRoundedRect(QRect(win.x() + 20, win.y() + 90, 46, 7), 3, 3)

        # ---- 标题 ----
        f = QFont("Microsoft YaHei UI", 10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(m["text"]))
        p.drawText(QRect(16, CARD_H - 64, CARD_W - 32, 18), Qt.AlignLeft | Qt.AlignVCenter, m["name"])

        f2 = QFont("Microsoft YaHei UI", 8)
        p.setFont(f2)
        p.setPen(QColor(m["sub"]))
        p.drawText(QRect(16, CARD_H - 45, CARD_W - 32, 16), Qt.AlignLeft | Qt.AlignVCenter, m["tag"])

        # 选中角标
        if self._active:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(acc))
            p.drawEllipse(QRect(CARD_W - 30, 12, 18, 18))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawLine(CARD_W - 25, 21, CARD_W - 22, 25)
            p.drawLine(CARD_W - 22, 25, CARD_W - 16, 17)
        p.end()


class ColorDot(QWidget):
    """强调色圆点。"""

    picked = Signal(str)

    def __init__(self, aid: str, hex_color: str, parent=None):
        super().__init__(parent)
        self.aid = aid
        self.hex = hex_color
        self._active = False
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(theme.ACCENTS[aid]["name"])

    def set_active(self, on: bool):
        if self._active != on:
            self._active = on
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.aid)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor(self.hex) if self.hex else QColor(theme.meta()["accent"])
        if self._active:
            p.setPen(QPen(col, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(1, 1, 31, 31)
        p.setPen(QPen(QColor(theme.c("border")), 1))
        p.setBrush(col)
        p.drawEllipse(6, 6, 21, 21)
        if not self.hex:                      # 跟随主题：画一个半环示意
            p.setPen(QPen(QColor(theme.c("surface")), 2))
            p.setBrush(Qt.NoBrush)
            p.drawArc(10, 10, 13, 13, 40 * 16, 200 * 16)
        p.end()


class PersonalizePage(QWidget):
    """个性化设置页。"""

    toast = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setObjectName("Page")
        self._cards: dict[str, ThemeCard] = {}
        self._dots: dict[str, ColorDot] = {}
        self._seg_buttons: dict[str, list[QPushButton]] = {}

        outer = content_column(self, spacing=18)
        self.header = PageHeader("个性化", "")
        self.lbl_sub = self.header.lbl_sub
        self.btn_reset = QPushButton("恢复默认外观")
        self.btn_reset.setObjectName("Ghost")
        self.btn_reset.setFixedHeight(34)
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset)
        self.header.actions.addWidget(self.btn_reset)
        outer.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        # ---- 主题画廊 ----
        g, body = self._group(lay, "主题", "换一套纸色与墨色，长时间阅读更舒服")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setAlignment(Qt.AlignCenter | Qt.AlignTop)
        for i, tid in enumerate(theme.THEMES):
            card = ThemeCard(tid)
            card.picked.connect(self._pick_theme)
            grid.addWidget(card, i // 3, i % 3)
            self._cards[tid] = card
        body.addLayout(grid)

        # ---- 强调色 ----
        _g, body = self._group(lay, "强调色", "只影响选中态与关键按钮，克制地用一点颜色")
        row = QHBoxLayout()
        row.setSpacing(6)
        for aid, info in theme.ACCENTS.items():
            dot = ColorDot(aid, info["hex"])
            dot.picked.connect(self._pick_accent)
            row.addWidget(dot)
            self._dots[aid] = dot
        self.lbl_accent = QLabel("")
        self.lbl_accent.setObjectName("Muted")
        row.addSpacing(8)
        row.addWidget(self.lbl_accent)
        row.addStretch(1)
        body.addLayout(row)

        # ---- 圆角 / 字号 ----
        _g, body = self._group(lay, "形状与字号", "圆角越大越柔和；字号影响整个界面")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._mini_label("圆角"))
        row.addWidget(self._seg("radius", [(r, name) for r, name in theme.RADII.items()]))
        row.addSpacing(24)
        row.addWidget(self._mini_label("字号"))
        row.addWidget(self._seg("scale", [(s, name) for s, name in theme.SCALES.items()]))
        row.addStretch(1)
        body.addLayout(row)

        hint = QLabel("提示：素纸 / 米黄 / 樱灰 对比柔和不刺眼；雾蓝偏清冷；墨夜 / 暮褐 适合关灯阅读。"
                      "主题、强调色、圆角、字号都会立即生效，并记住到下次启动。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        body.addWidget(hint)

        lay.addStretch(1)
        theme.bus.changed.connect(self.refresh)
        self.refresh()

    # ---------- 组件 ----------
    @staticmethod
    def _group(parent: QVBoxLayout, title: str, sub: str = ""):
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 13, 16, 15)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        head.addWidget(t)
        if sub:
            s = QLabel(sub)
            s.setObjectName("Muted")
            head.addWidget(s)
        head.addStretch(1)
        v.addLayout(head)
        parent.addWidget(card)
        return card, v

    @staticmethod
    def _mini_label(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("Muted")
        lab.setMinimumWidth(36)
        return lab

    def _seg(self, key: str, items: list[tuple]) -> QFrame:
        box = QFrame()
        box.setObjectName("SegBox")
        row = QHBoxLayout(box)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        group = QButtonGroup(box)
        group.setExclusive(True)
        btns = []
        for val, label in items:
            b = QPushButton(label)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("val", val)
            b.clicked.connect(lambda _=False, v=val, k=key: self._set_value(k, v))
            group.addButton(b)
            row.addWidget(b)
            btns.append(b)
        self._seg_buttons[key] = btns
        return box

    # ---------- 回调 ----------
    def _pick_theme(self, tid: str):
        theme.set_theme(tid)
        self.toast.emit(f"已切换到「{theme.THEMES[tid]['name']}」")

    def _pick_accent(self, aid: str):
        theme.set_accent(aid)
        self.toast.emit(f"强调色：{theme.ACCENTS[aid]['name']}")

    def _set_value(self, key: str, val):
        if key == "radius":
            theme.set_radius(int(val))
            self.toast.emit(f"圆角：{theme.RADII[int(val)]}")
        else:
            theme.set_scale(float(val))
            self.toast.emit(f"字号：{theme.SCALES[float(val)]}")

    def _reset(self):
        theme.reset()
        self.toast.emit("已恢复默认外观")

    # ---------- 同步 ----------
    def refresh(self):
        cur = theme.current()
        for tid, card in self._cards.items():
            card.set_active(tid == cur["theme"])
            card.update()
        for aid, dot in self._dots.items():
            dot.set_active(aid == cur["accent"])
            dot.update()
        for key, btns in self._seg_buttons.items():
            target = cur["radius"] if key == "radius" else cur["scale"]
            for b in btns:
                v = b.property("val")
                b.blockSignals(True)
                b.setChecked(abs(float(v) - float(target)) < 1e-6)
                b.blockSignals(False)
        acc_name = theme.ACCENTS[cur["accent"]]["name"]
        accent_hex = (theme.ACCENTS[cur["accent"]]["hex"] or theme.meta()["accent"]).upper()
        self.lbl_accent.setText(f"{acc_name} {accent_hex}")
        self.header.set_subtitle(
            f"当前：{theme.meta()['name']} · {acc_name} · {theme.RADII[cur['radius']]}圆角"
            f" · {theme.SCALES[cur['scale']]}字号")
