"""页面排版骨架：居中版心 + 统一页头。

桌面窗口经常被拉到 1600px 以上，内容如果直接铺满会显得又空又散；
这里统一给一个最大宽度，窄窗口时自动收窄。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

MAX_CONTENT_W = 1280


def content_column(page: QWidget, *, max_width: int = MAX_CONTENT_W,
                   margins=(28, 20, 28, 20), spacing: int = 18) -> QVBoxLayout:
    """在页面里创建一条居中的内容列，返回其纵向布局。"""
    outer = QHBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addStretch(1)
    col = QWidget()
    col.setObjectName("ContentColumn")
    col.setMaximumWidth(max_width)
    outer.addWidget(col, 20)
    outer.addStretch(1)
    lay = QVBoxLayout(col)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


class PageHeader(QWidget):
    """页头：主标题 + 一行说明，右侧放操作。"""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("PageTitle")
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setObjectName("PageSub")
        self.lbl_sub.setVisible(bool(subtitle))
        box.addWidget(self.lbl_title)
        box.addWidget(self.lbl_sub)
        row.addLayout(box)
        row.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(10)
        row.addLayout(self.actions)

    def set_title(self, text: str):
        self.lbl_title.setText(text)

    def set_subtitle(self, text: str):
        self.lbl_sub.setText(text)
        self.lbl_sub.setVisible(bool(text))
