"""异步任务：封面生成、页面解码、导入（扫描 → 复制/引用 → 登记为一话）。"""
from __future__ import annotations

import os
import shutil
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .cbr import ComicSource, book_key, has_any_comic, scan_chapters


class _Signals(QObject):
    cover = Signal(str, str)          # key, cover_path
    bookcover = Signal(str)           # 尺寸无关的自定义书封面就绪（无参）
    page = Signal(str, int, object)   # key, index, QImage
    import_done = Signal(list, list)  # records, skipped
    import_progress = Signal(int, int, str)
    scan_done = Signal(list)


class _CoverJob(QRunnable):
    def __init__(self, sig: _Signals, path: str, width: int = 420):
        super().__init__()
        self.sig, self.path, self.width = sig, path, width
        self.setAutoDelete(True)

    def run(self):
        try:
            cb = ComicSource(self.path)
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
            cb = ComicSource(self.path)
            im = cb.image(self.index, self.max_w or None, self.max_h or None)
            cb.close()
            self.sig.page.emit(self.key, self.index, pil_to_qimage(im))
        except Exception:
            traceback.print_exc(file=sys.stderr)


class _ImportJob(QRunnable):
    """扫描来源 → 逐个一话地复制入库（或仅登记引用）。"""

    def __init__(self, sig: _Signals, sources: list[str], dest: Path, conflict: str,
                 copy: bool = True):
        super().__init__()
        self.sig, self.sources = sig, sources
        self.dest, self.conflict, self.copy = dest, conflict, copy
        self.setAutoDelete(True)

    def _unique(self, target: Path) -> Path:
        stem, n = target.stem, 1
        while target.exists():
            target = target.with_name(f"{stem} ({n}){target.suffix}")
            n += 1
        return target

    def run(self):
        try:
            items: list[dict] = []
            for s in self.sources:
                items += scan_chapters(s)
            # 去重（同一路径只收一次）
            uniq, seen = [], set()
            for it in items:
                k = str(Path(it["path"]).resolve()).lower()
                if k not in seen:
                    seen.add(k)
                    uniq.append(it)
            items = uniq
            self.sig.scan_done.emit([i["path"] for i in items])

            records, skipped = [], []
            total = len(items)
            for i, it in enumerate(items):
                self.sig.import_progress.emit(i + 1, total, it["name"])
                src = Path(it["path"])
                try:
                    stat = src.stat()
                except Exception:
                    skipped.append(str(src))
                    continue

                if not self.copy:
                    records.append({"path": str(src), "kind": it["kind"], "name": it["name"],
                                    "size": stat.st_size, "mtime": stat.st_mtime})
                    continue

                target = self.dest / src.name
                if target.exists():
                    if self.conflict == "skip":
                        skipped.append(str(src))
                        continue
                    if self.conflict == "rename":
                        target = self._unique(target)
                if it["kind"] == "dir":
                    shutil.copytree(src, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, target)
                records.append({"path": str(target), "kind": it["kind"], "name": it["name"],
                                "size": stat.st_size, "mtime": stat.st_mtime})
            self.sig.import_done.emit(records, skipped)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self.sig.import_done.emit([], [])


class Async:
    """线程池门面。"""

    def __init__(self):
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(2, min(6, (os.cpu_count() or 4))))
        self.sig = _Signals()

    def cover(self, path: str, width: int = 420):
        self.pool.start(_CoverJob(self.sig, path, width))

    def page(self, path: str, key: str, index: int, max_w: int = 0, max_h: int = 0):
        self.pool.start(_PageJob(self.sig, path, key, index, max_w, max_h))

    def import_files(self, sources: list[str], dest: Path, conflict: str, copy: bool = True):
        self.pool.start(_ImportJob(self.sig, sources, dest, conflict, copy))

    def wait(self, ms: int = 3000):
        self.pool.waitForDone(ms)

    @staticmethod
    def acceptable(paths: list[str]) -> list[str]:
        return [p for p in paths if has_any_comic(p)]


ASYNC = Async()
