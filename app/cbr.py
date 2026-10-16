"""CBZ / ZIP 漫画解析引擎：自然排序、页面尺寸探测、并行解码、封面生成。"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import zipfile
from pathlib import Path

from PIL import Image

from .store import SIZE_DIR, COVER_DIR

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".jfif", ".avif"}

try:
    RES_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    RES_LANCZOS = Image.LANCZOS


def natkey(s: str):
    """自然排序：'第2话' < '第10话'。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def book_key(path) -> str:
    return hashlib.md5(str(Path(path).resolve()).lower().encode("utf-8")).hexdigest()[:16]


def is_cbz(path) -> bool:
    p = Path(path)
    return p.suffix.lower() in (".cbz", ".zip") and p.is_file()


def image_from_bytes(data: bytes, max_w: int | None = None, max_h: int | None = None) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    if max_w or max_h:
        im.thumbnail((max_w or 10 ** 6, max_h or 10 ** 6), RES_LANCZOS)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


class Cbz:
    """单个 CBZ 文件的读取句柄（线程安全）。"""

    def __init__(self, path):
        self.path = Path(path)
        self.key = book_key(self.path)
        self._zf: zipfile.ZipFile | None = None
        self._lock = threading.RLock()   # 可重入：read() 内部会再次取锁
        self._names: list[str] | None = None
        self._sizes: list[tuple[int, int]] | None = None

    # ---------- 打开 / 关闭 ----------
    @property
    def zip(self) -> zipfile.ZipFile:
        with self._lock:
            if self._zf is None:
                self._zf = zipfile.ZipFile(self.path)  # noqa: SIM115
            return self._zf

    def close(self) -> None:
        with self._lock:
            if self._zf is not None:
                try:
                    self._zf.close()
                except Exception:
                    pass
                self._zf = None

    def __del__(self):
        self.close()

    # ---------- 页列表 ----------
    @property
    def names(self) -> list[str]:
        if self._names is None:
            try:
                z = self.zip
                names = []
                for n in z.namelist():
                    if n.endswith("/") or "__MACOSX" in n:
                        continue
                    base = Path(n).name
                    if base.startswith("."):
                        continue
                    if Path(n).suffix.lower() in IMG_EXT:
                        names.append(n)
                names.sort(key=natkey)
                self._names = names
            except Exception:
                self._names = []
        return self._names

    @property
    def page_count(self) -> int:
        return len(self.names)

    def read(self, index: int) -> bytes:
        n = self.names
        if not n:
            raise IndexError("empty cbz")
        index = max(0, min(index, len(n) - 1))
        with self._lock:
            return self.zip.read(n[index])

    def image(self, index: int, max_w=None, max_h=None) -> Image.Image:
        return image_from_bytes(self.read(index), max_w, max_h)

    # ---------- 页面尺寸（带磁盘缓存）----------
    @property
    def page_sizes(self) -> list[tuple[int, int]]:
        if self._sizes is not None:
            return self._sizes
        cache = SIZE_DIR / f"{self.key}.json"
        try:
            if cache.exists():
                st = cache.stat()
                if st.st_mtime >= self.path.stat().st_mtime:
                    obj = json.loads(cache.read_text(encoding="utf-8"))
                    if obj.get("count") == self.page_count and obj.get("sizes"):
                        self._sizes = [tuple(s) for s in obj["sizes"]]
                        return self._sizes
        except Exception:
            pass
        sizes = []
        for i in range(self.page_count):
            try:
                with Image.open(io.BytesIO(self.read(i))) as im:
                    sizes.append((im.width, im.height))
            except Exception:
                sizes.append((1000, 1500))
        self._sizes = sizes
        try:
            cache.write_text(json.dumps({"count": len(sizes), "sizes": sizes}), encoding="utf-8")
        except Exception:
            pass
        return sizes

    # ---------- 封面 ----------
    def cover_path(self, width: int = 420) -> Path | None:
        out = COVER_DIR / f"{self.key}_{width}.jpg"
        if out.exists() and out.stat().st_mtime >= self.path.stat().st_mtime:
            return out
        if self.page_count == 0:
            return None
        try:
            # 取第一页（多数单行本首图即封面）
            im = self.image(0)
            if im.width > width:
                im = im.resize((width, max(1, round(im.height * width / im.width))), RES_LANCZOS)
            im.convert("RGB").save(out, "JPEG", quality=82)
            return out
        except Exception:
            return None


class BookHandlePool:
    """复用已打开的 Cbz 句柄，避免频繁 reopen。"""

    def __init__(self, limit: int = 4):
        self._limit = limit
        self._items: dict[str, Cbz] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def get(self, path) -> Cbz:
        key = book_key(path)
        with self._lock:
            if key in self._items:
                self._order.remove(key)
                self._order.append(key)
                return self._items[key]
            cb = Cbz(path)
            self._items[key] = cb
            self._order.append(key)
            while len(self._order) > self._limit:
                old = self._order.pop(0)
                h = self._items.pop(old, None)
                if h:
                    h.close()
            return cb

    def close_all(self) -> None:
        with self._lock:
            for h in self._items.values():
                h.close()
            self._items.clear()
            self._order.clear()


POOL = BookHandlePool()
