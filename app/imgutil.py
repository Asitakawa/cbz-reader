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


def cover_pixmap(pm: QPixmap, w: int, h: int, radius: int = 8, dpr: float = 1.0) -> QPixmap:
    """把封面裁成「等比铺满 + 居中裁切 + 圆角」的缩略图。

    直接用 KeepAspectRatio 缩放会在封面框里留下大片底色（像贴了张邮票），
    这里改为铺满裁切，并用圆角路径裁边，和海报纸质封面墙更接近。
    """
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPainterPath

    if pm is None or pm.isNull() or w <= 0 or h <= 0:
        return QPixmap()
    dpr = dpr or 1.0
    tw, th = int(w * dpr), int(h * dpr)
    scaled = pm.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(tw, th)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, tw, th), radius * dpr, radius * dpr)
    p.setClipPath(path)
    p.drawPixmap((tw - scaled.width()) // 2, (th - scaled.height()) // 2, scaled)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out
