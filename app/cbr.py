"""漫画源解析：一话可以是 .cbz/.zip 压缩包，也可以是装满图片的文件夹。

同时提供导入用的扫描工具：从一个文件/文件夹推导出「哪些是一话」。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import zipfile
from pathlib import Path

from PIL import Image

from .store import COVER_DIR, SIZE_DIR

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".jfif", ".avif"}
ZIP_EXT = {".cbz", ".zip"}

try:
    RES_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    RES_LANCZOS = Image.LANCZOS


def natkey(s: str):
    """自然排序：'第2话' < '第10话'。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def book_key(path) -> str:
    return hashlib.md5(str(Path(path)).lower().replace("\\", "/").encode("utf-8")).hexdigest()[:16]


def is_zip_comic(path) -> bool:
    p = Path(path)
    return p.suffix.lower() in ZIP_EXT and p.is_file()


# 兼容旧命名
is_cbz = is_zip_comic


def _iter_images(root: Path):
    """遍历目录下所有图片（递归、跳过隐藏文件/目录与 __MACOSX、不跟随符号链接）。"""
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__MACOSX"]
        for name in filenames:
            if name.startswith("."):
                continue
            f = Path(dirpath) / name
            if f.suffix.lower() in IMG_EXT:
                yield f


def has_images(d: Path, deep: bool = False) -> bool:
    """文件夹里是否有图片。

    deep=False 只看直属文件（用于判断「这个目录本身是不是一话」）；
    deep=True 连同子目录一起看（用于判断「这棵树里有没有图」）。
    """
    if not d.is_dir():
        return False
    try:
        if deep:
            return next(_iter_images(d), None) is not None
        for f in d.iterdir():
            if f.is_file() and not f.name.startswith(".") \
                    and f.suffix.lower() in IMG_EXT:
                return True
    except Exception:
        return False
    return False


def image_from_bytes(data: bytes, max_w: int | None = None, max_h: int | None = None) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    if max_w or max_h:
        im.thumbnail((max_w or 10 ** 6, max_h or 10 ** 6), RES_LANCZOS)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


class ComicSource:
    """一话的读取句柄：压缩包 或 图片文件夹（线程安全）。"""

    def __init__(self, path):
        self.path = Path(path)
        self.is_dir = self.path.is_dir()
        self.key = book_key(self.path)
        self._zf: zipfile.ZipFile | None = None
        self._lock = threading.RLock()
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
        if self._names is not None:
            return self._names
        names: list[str] = []
        try:
            if self.is_dir:
                for f in _iter_images(self.path):
                    names.append(f.relative_to(self.path).as_posix())
            else:
                for n in self.zip.namelist():
                    if n.endswith("/") or "__MACOSX" in n:
                        continue
                    # 任一路径段以 . 开头都算隐藏（.hidden/004.png、.git/…）
                    if any(part.startswith(".") for part in Path(n).parts):
                        continue
                    if Path(n).suffix.lower() in IMG_EXT:
                        names.append(n)
        except Exception:
            names = []
        names.sort(key=natkey)
        self._names = names
        return names

    @property
    def page_count(self) -> int:
        return len(self.names)

    def read(self, index: int) -> bytes:
        n = self.names
        if not n:
            raise IndexError("empty comic")
        index = max(0, min(index, len(n) - 1))
        name = n[index]
        if self.is_dir:
            return (self.path / name).read_bytes()
        with self._lock:
            return self.zip.read(name)

    def image(self, index: int, max_w=None, max_h=None) -> Image.Image:
        return image_from_bytes(self.read(index), max_w, max_h)

    # ---------- 页面尺寸（带磁盘缓存）----------
    def _fingerprint(self) -> float:
        try:
            if self.is_dir:
                ts = [self.path.stat().st_mtime]
                for f in _iter_images(self.path):
                    ts.append(f.stat().st_mtime)
                return max(ts) if ts else 0.0
            return self.path.stat().st_mtime
        except Exception:
            return 0.0

    @property
    def page_sizes(self) -> list[tuple[int, int]]:
        if self._sizes is not None:
            return self._sizes
        cache = SIZE_DIR / f"{self.key}.json"
        fp = self._fingerprint()
        try:
            if cache.exists():
                obj = json.loads(cache.read_text(encoding="utf-8"))
                if obj.get("count") == self.page_count and obj.get("fp") == fp and obj.get("sizes"):
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
            cache.write_text(json.dumps({"count": len(sizes), "fp": fp, "sizes": sizes}),
                             encoding="utf-8")
        except Exception:
            pass
        return sizes

    # ---------- 封面 ----------
    def cover_path(self, width: int = 420) -> Path | None:
        out = COVER_DIR / f"{self.key}_{width}.jpg"
        try:
            if out.exists() and out.stat().st_mtime >= self._fingerprint():
                return out
        except Exception:
            pass
        if self.page_count == 0:
            return None
        try:
            im = self.image(0)
            if im.width > width:
                im = im.resize((width, max(1, round(im.height * width / im.width))), RES_LANCZOS)
            im.convert("RGB").save(out, "JPEG", quality=82)
            return out
        except Exception:
            return None


# 兼容旧命名
Cbz = ComicSource


class SourcePool:
    """复用已打开的句柄，避免频繁 reopen。"""

    def __init__(self, limit: int = 4):
        self._limit = limit
        self._items: dict[str, ComicSource] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def get(self, path) -> ComicSource:
        key = book_key(path)
        with self._lock:
            if key in self._items:
                self._order.remove(key)
                self._order.append(key)
                return self._items[key]
            cb = ComicSource(path)
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


POOL = SourcePool()


# ================= 导入扫描：一个来源 -> 若干「话」 =================
def scan_chapters(source) -> list[dict]:
    """把用户选中的文件/文件夹拆成一话一话。

    规则：
      - 单个 .cbz/.zip            -> 一话（文件）
      - 文件夹本身含图片           -> 一话（文件夹）
      - 文件夹里含子文件夹         -> 每个含图片的子文件夹各算一话
      - 文件夹里的 .cbz/.zip       -> 每个各算一话
    """
    p = Path(source)
    out: list[dict] = []

    def add(path: Path, kind: str, name: str | None = None):
        out.append({"path": str(path), "kind": kind, "name": name or path.stem or path.name})

    if p.is_file():
        if is_zip_comic(p):
            add(p, "file")
        return out

    if not p.is_dir():
        return out

    if has_images(p):
        add(p, "dir", p.name)
        return out

    for child in sorted(list(p.iterdir()), key=lambda x: natkey(x.name)):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if has_images(child) or has_images(child, deep=True):
                add(child, "dir", child.name)
            else:
                for f in sorted(child.rglob("*"), key=lambda x: natkey(str(x))):
                    if is_zip_comic(f):
                        add(f, "file", f.stem)
        elif is_zip_comic(child):
            add(child, "file", child.stem)
    return out


def has_any_comic(path) -> bool:
    """拖拽时判断是否值得接手。"""
    p = Path(path)
    if p.is_file():
        return is_zip_comic(p)
    if p.is_dir():
        return has_images(p) or has_images(p, deep=True) or bool(scan_chapters(p))
    return False
