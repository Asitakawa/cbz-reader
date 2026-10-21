"""通用小对话框：文本输入。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)


class PromptDialog(QDialog):
    """单行文本输入对话框（用于「新增书」「重命名」）。"""

    def __init__(self, parent, title: str, label: str, default: str = "",
                 ok_text: str = "确定", placeholder: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        lab = QLabel(label)
        lab.setObjectName("FormLabel")
        lay.addWidget(lab)

        self.edit = QLineEdit(default)
        self.edit.setPlaceholderText(placeholder)
        self.edit.selectAll()
        self.edit.returnPressed.connect(self.accept)
        lay.addWidget(self.edit)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(ok_text)
        ok.setObjectName("Primary")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)



    @staticmethod
    def get_text(parent, title: str, label: str, default: str = "",
                 ok_text: str = "确定", placeholder: str = "") -> str | None:
        dlg = PromptDialog(parent, title, label, default, ok_text, placeholder)
        if dlg.exec() == QDialog.Accepted:
            return dlg.edit.text().strip()
        return None
