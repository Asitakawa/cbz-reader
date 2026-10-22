"""日志与全局异常钩子。

窗口模式（pythonw / 打包 exe）没有控制台，旧实现把 stderr 直接丢进 devnull，
出错时现场全无。现在所有未捕获异常、Qt 警告和 traceback 都写入 data/app.log。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .store import DATA_DIR

LOG_FILE = DATA_DIR / "app.log"
_READY = False


class _LogStream:
    """把 stderr 的写入转成日志（供 traceback.print_exc 使用）。"""

    def __init__(self, logger: logging.Logger):
        self._log = logger

    def write(self, text: str) -> int:
        msg = (text or "").rstrip()
        if msg:
            self._log.error(msg)
        return len(text or "")

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def setup_logging(level: int = logging.INFO) -> None:
    global _READY
    if _READY:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
    try:
        handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except Exception:
        pass

    # pythonw / --windowed 下 stderr 为 None：转成日志，而不是丢弃
    if sys.stderr is None:
        sys.stderr = _LogStream(logging.getLogger("stderr"))
    _READY = True


def install_qt_handler() -> None:
    """把 Qt 自己的警告也收进日志（例如 QPainter / 布局告警）。"""
    try:
        from PySide6.QtCore import qInstallMessageHandler
    except Exception:
        return

    def handler(_mode, _ctx, message):
        logging.getLogger("qt").warning("%s", message)

    qInstallMessageHandler(handler)


def install_excepthook() -> None:
    shown = {"done": False}

    def hook(exc_type, exc, tb):
        logging.getLogger("uncaught").critical("未捕获异常", exc_info=(exc_type, exc, tb))
        if shown["done"]:
            return
        shown["done"] = True
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None and app.platformName() != "offscreen":
                QMessageBox.critical(
                    None, "CBZ 阅读器",
                    f"程序遇到错误：{exc}\n\n"
                    f"详细信息已写入：\n{LOG_FILE}\n\n"
                    "书架数据已保留，重启后可继续。")
        except Exception:
            pass

    sys.excepthook = hook


def log_environment(version: str) -> None:
    logging.getLogger("app").info("启动 CBZ 阅读器 v%s | %s", version, sys.executable)
