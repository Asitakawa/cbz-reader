"""Pillow ↔ QImage 转换工具。"""
from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage, QPixmap


def pil_to_qimage(im: Image.Image) -> QImage:
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.width, im.height, im.width * 4, QImage.Format_RGBA8888)
    return qimg.copy()   # 脱离 Python 缓冲区


def pil_to_qpixmap(im: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(im))
