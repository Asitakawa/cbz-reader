"""单实例守卫：只允许一个进程写书库，第二个实例负责唤起已有窗口。

之前用 Win32 命名互斥体检测，但只弹一个「仍然启动」的确认框：
用户点「是」就会有两个进程各持一份 books.json / history.json，
后关闭的那个会把另一个的导入与进度整体覆盖。现在改为强制单实例，
并通过本地套接字把已有窗口唤到前台。
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .store import DATA_DIR

DEFAULT_KEY = "cbz-reader"


class SingleInstance(QObject):
    activated = Signal()          # 第二个实例请求「把窗口显示出来」

    def __init__(self, key: str = DEFAULT_KEY, parent=None):
        super().__init__(parent)
        self.key = key
        self._lock = QLockFile(str(DATA_DIR / f"{key}.lock"))
        self._lock.setStaleLockTime(20_000)
        self._server: QLocalServer | None = None
        self._emitting = False

    # ---------- 主实例 ----------
    def acquire(self) -> bool:
        """抢占锁并开始监听；返回 False 说明已有实例持有。"""
        if not self._lock.tryLock(100):
            # 没有写权限建不了锁文件时降级运行：宁可少一层保护，也不要「双击没反应」
            if self._lock.error() == QLockFile.PermissionError:
                logging.getLogger("app").warning("无法创建单实例锁（目录不可写），已降级运行")
                return True
            return False
        # 锁在手说明没有活着的实例，清掉上次崩溃残留的套接字名
        QLocalServer.removeServer(self.key)
        server = QLocalServer(self)
        server.newConnection.connect(self._on_connection)
        if not server.listen(self.key):
            server.listen(f"{self.key}-{os.getpid()}")
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        try:
            self._lock.unlock()
        except Exception:
            pass
        QLocalServer.removeServer(self.key)

    def _on_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            try:
                sock.waitForReadyRead(120)
                data = bytes(sock.readAll())
            finally:
                sock.disconnectFromServer()
            if b"show" in data and not self._emitting:
                # 防止唤醒过程中再次触发导致递归
                self._emitting = True
                try:
                    self.activated.emit()
                finally:
                    self._emitting = False

    # ---------- 第二个实例 ----------
    @staticmethod
    def notify(key: str = DEFAULT_KEY, timeout: int = 700) -> bool:
        """请求已有实例显示窗口；成功返回 True。"""
        sock = QLocalSocket()
        sock.connectToServer(key)
        if not sock.waitForConnected(timeout):
            return False
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(timeout)
        sock.disconnectFromServer()
        return True
