"""异步任务：封面生成、页面解码、目录扫描导入。"""
from __future__ import annotations

import os
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .cbr import Cbz, book_key, is_cbz


class _Signals(QObject):
    cover = Signal(str, str)        # key, cover_path
    page = Signal(str, int, object)  # key, index, QImage
    import_done = Signal(list, list)  # new_files, skipped
    import_progress = Signal(int, int, str)
    scan_done = Signal(list)


class _CoverJob(QRunnable):
    def __init__(self, sig: _Signals, path: str, width: int = 420):
        super().__init__()
        self.sig, self.path, self.width = sig, path, width
        self.setAutoDelete(True)

    def run(self):
        try:
            cb = Cbz(self.path)
            p = cb.cover_path(self.width)
            cb.close()
            if p:
                self.sig.cover.emit(book_key(self.path), str(p))
        except Exception:
            traceback.print_exc(file=sys.stderr)


class _PageJob(QRunnable):
    def __init__(self, sig: _Signals, path: str, key: str, index: int,
                 max_w: int, max_h: int):
        super().__init__()
        self.sig, self.path, self.key, self.index = sig, path, key, index
        self.max_w, self.max_h = max_w, max_h
        self.setAutoDelete(True)

    def run(self):
        try:
            from .imgutil import pil_to_qimage
            cb = Cbz(self.path)
            im = cb.image(self.index, self.max_w or None, self.max_h or None)
            cb.close()
            self.sig.page.emit(self.key, self.index, pil_to_qimage(im))
        except Exception:
            traceback.print_exc(file=sys.stderr)


class _ImportJob(QRunnable):
    """扫描源 → 复制入库（或仅登记引用）。"""

    def __init__(self, sig: _Signals, sources: list[str], dest: Path, conflict: str,
                 copy: bool = True):
        super().__init__()
        self.sig, self.sources = sig, sources
        self.dest, self.conflict, self.copy = dest, conflict, copy
        self.setAutoDelete(True)

    @staticmethod
    def _scan(sources: list[str]) -> list[Path]:
        found: list[Path] = []
        for s in sources:
            p = Path(s)
            if p.is_dir():
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        fp = Path(root) / f
                        if is_cbz(fp):
                            found.append(fp)
            elif is_cbz(p):
                found.append(p)
        # 去重 + 稳定排序
        uniq, seen = [], set()
        for f in sorted(found, key=lambda x: str(x).lower()):
            r = str(f.resolve()).lower()
            if r not in seen:
                seen.add(r)
                uniq.append(f)
        return uniq

    def run(self):
        files = self._scan(self.sources)
        self.sig.scan_done.emit([str(f) for f in files])
        added, skipped = [], []
        total = len(files)
        if not self.copy:
            # 仅登记引用：直接把原文件路径写进书架
            for i, src in enumerate(files):
                self.sig.import_progress.emit(i + 1, total, src.name)
                added.append(str(src))
            self.sig.import_done.emit(added, skipped)
            return
        for i, src in enumerate(files):
            self.sig.import_progress.emit(i + 1, total, src.name)
            target = self.dest / src.name
            try:
                if target.exists():
                    if self.conflict == "skip":
                        skipped.append(str(src))
                        continue
                    if self.conflict == "rename":
                        stem, n = target.stem, 1
                        while target.exists():
                            target = self.dest / f"{stem} ({n}){target.suffix}"
                            n += 1
                    # overwrite：直接覆盖
                if src.resolve() != target.resolve():
                    shutil.copy2(src, target)
                added.append(str(target))
            except Exception:
                traceback.print_exc(file=sys.stderr)
                skipped.append(str(src))
        self.sig.import_done.emit(added, skipped)


class Async:
    """线程池门面。"""

    def __init__(self):
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(2, min(6, (os.cpu_count() or 4))))
        self.sig = _Signals()
        self.sig.setParent(None)

    def cover(self, path: str, width: int = 420):
        self.pool.start(_CoverJob(self.sig, path, width))

    def page(self, path: str, key: str, index: int, max_w: int = 0, max_h: int = 0):
        self.pool.start(_PageJob(self.sig, path, key, index, max_w, max_h))

    def import_files(self, sources: list[str], dest: Path, conflict: str, copy: bool = True):
        self.pool.start(_ImportJob(self.sig, sources, dest, conflict, copy))

    def wait(self, ms: int = 3000):
        self.pool.waitForDone(ms)


ASYNC = Async()
