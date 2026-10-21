"""配置 / 书架(书→话两层) / 历史记录 —— JSON 持久化（原子写入）。"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：数据与缓存放在 exe 同级目录（安装到用户目录，可写）
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CACHE_DIR = APP_DIR / "cache"
COVER_DIR = CACHE_DIR / "covers"
SIZE_DIR = CACHE_DIR / "sizes"
BOOKCOVER_DIR = CACHE_DIR / "bookcovers"
LIB_DIR = APP_DIR / "library"

for _d in (DATA_DIR, CACHE_DIR, COVER_DIR, SIZE_DIR, BOOKCOVER_DIR, LIB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.json"
SHELF_FILE = DATA_DIR / "books.json"
LEGACY_SHELF_FILE = DATA_DIR / "shelf.json"

DEFAULTS = {
    "library_dir": str(LIB_DIR),
    "hotkey_hide": "ctrl+`",
    "hotkey_camo": "ctrl+shift+x",
    "reader": {
        "mode": "scroll",        # scroll | single
        "fit": "width",          # width | height | original
        "zoom": 1.0,
        "rtl": False,            # True = 日漫从右往左
        "bg": "#101216",
        "gap": 0,       # 页间距（0 = 无冗余边框）
    },
    "window": {"w": 1200, "h": 780, "x": None, "y": None, "opacity": 1.0},
    "import": {"on_conflict": "skip"},   # skip | overwrite | rename
    "edge": {
        "enabled": True,
        "side": "right",      # right | left
        "shape": "sliver",    # sliver=细缝(6px) | strip=窄条(40px)
        "auto_peek": True,    # 鼠标碰到屏幕边缘自动滑出
    },
    "camo": {
        "skin": "excel",
        "excel_title": "Microsoft Excel - 工作簿1.xlsx",
        "word_title": "工作报告.docx - Word",
        "term_title": "C:\\Windows\\System32\\cmd.exe",
        "hide_in_taskbar": True,
    },
    "reader_ui": {"auto_hide_toolbar": True},
    "theme": {
        "name": "paper",      # paper | linen | mist | sakura | ink | dusk
        "accent": "",         # "" = 跟随主题；否则 pine/indigo/clay/wine/violet/slate
        "radius": 10,         # 6 紧凑 | 10 标准 | 14 圆润
        "scale": 1.0,         # 0.92 小 | 1.0 标准 | 1.08 大 | 1.16 特大
    },
}


# ================= 话数排列 =================
ORDER_MODES = {
    "source": "默认（导入顺序）",
    "natural": "数字顺序（1, 1.5, 2）",
    "sub_before": "小节前置（3.1, 3.2, 3）",
    "part": "上下篇（1上, 1下, 1）",
}
DEFAULT_ORDER = "source"

_PART_RANK = (("上", 0), ("前", 0), ("中", 1), ("下", 2), ("后", 2),
              ("续", 3), ("完", 4), ("终", 5))


def _first_number(name: str):
    import re
    m = re.search(r"((?:\d+)(?:[.．]\d+)?)", str(name))
    if not m:
        return None
    try:
        return float(m.group(1).replace("．", "."))
    except ValueError:
        return None


def _part_rank(name: str) -> int:
    import re
    low = str(name).lower()
    for key, rank in _PART_RANK:
        if key in low:
            return rank
    m = re.search(r"part\s*(\d+)", low)
    return int(m.group(1)) if m else -1


def chapter_order_key(ch: dict, mode: str):
    """按模式生成排序键；source 模式另行处理。"""
    from .cbr import natkey
    name = str(ch.get("name", ""))
    num = _first_number(name)
    part = _part_rank(name)
    if num is None:
        return (1, 0.0, 0, part, natkey(name))
    if mode == "natural":
        return (0, num, 0, part, natkey(name))
    if mode == "part":
        # 同一话的「上/中/下」先排，未分篇的整话排在后面
        return (0, num, 0 if part >= 0 else 1, part, natkey(name))
    whole = int(num)
    frac = round(num - whole, 6)
    if mode == "sub_before":
        # 3.1 / 3.2 在 3 之前
        return (0, float(whole), 0 if frac else 1, frac, part, natkey(name))
    return (0, num, 0, part, natkey(name))


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def chapter_id(path) -> str:
    """一话的 id：沿用文件路径哈希，保证老历史记录可无缝对应。"""
    return hashlib.md5(str(Path(path)).lower().replace("\\", "/").encode("utf-8")).hexdigest()[:16]


def new_book_id(seed: str | None = None) -> str:
    if seed:
        return "b" + hashlib.md5(seed.lower().encode("utf-8")).hexdigest()[:12]
    return "b" + uuid.uuid4().hex[:12]


class Store:
    """线程安全的配置 + 书库（书/话）+ 历史。

    数据结构：
      books    : bid -> {id, title, added, cover, note}
      chapters : cid -> {id, book, path, name, kind, size, mtime, added}
                 kind: "file"(cbz/zip) | "dir"(图片文件夹)
      history  : cid -> {page, total, pos, time, count, finished, name}
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.config = _deep_merge(DEFAULTS, self._read(CONFIG_FILE, {}))
        self.history: dict = self._read(HISTORY_FILE, {})
        data = self._read(SHELF_FILE, {})
        self.books: dict = data.get("books", {})
        self.chapters: dict = data.get("chapters", {})
        self._migrate_legacy()

    # ---------- 底层 ----------
    @staticmethod
    def _read(path: Path, default):
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return default

    @staticmethod
    def _write(path: Path, obj) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def save_config(self) -> None:
        with self._lock:
            self._write(CONFIG_FILE, self.config)

    def save_all(self) -> None:
        with self._lock:
            self._write(CONFIG_FILE, self.config)
            self._write(HISTORY_FILE, self.history)
            self._write(SHELF_FILE, {"books": self.books, "chapters": self.chapters})

    # ---------- 老数据迁移：扁平书架 -> 一书多话 ----------
    def _migrate_legacy(self) -> None:
        legacy = self._read(LEGACY_SHELF_FILE, None)
        if not isinstance(legacy, dict) or not legacy:
            return
        if self.books:
            return
        groups: dict[str, list[dict]] = {}
        for key, v in legacy.items():
            p = Path(v.get("path", ""))
            if not p.exists():
                continue
            groups.setdefault(str(p.parent), []).append({**v, "key": key, "path": str(p)})
        for _parent, items in groups.items():
            title = Path(_parent).name or "未命名书架"
            bid = new_book_id(seed=f"legacy::{_parent}")
            self.books[bid] = {"id": bid, "title": title, "added": time.time(),
                               "cover": "", "note": "由旧版书架自动迁移"}
            for v in items:
                cid = v.get("key") or chapter_id(v["path"])
                self.chapters[cid] = {
                    "id": cid, "book": bid, "path": v["path"], "kind": "file",
                    "name": Path(v["path"]).stem,
                    "size": v.get("size", 0), "mtime": v.get("mtime", 0),
                    "added": v.get("added", time.time()),
                }
        try:
            LEGACY_SHELF_FILE.rename(LEGACY_SHELF_FILE.with_suffix(".json.migrated"))
        except Exception:
            pass
        self.save_all()

    # ---------- 配置 ----------
    def cfg(self, path: str, default=None):
        node = self.config
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set_cfg(self, path: str, value) -> None:
        with self._lock:
            parts = path.split(".")
            node = self.config
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = value

    # ================= 书 =================
    def add_book(self, title: str, note: str = "") -> str:
        bid = new_book_id()
        with self._lock:
            self.books[bid] = {"id": bid, "title": title.strip() or "未命名书",
                               "added": time.time(), "cover": "", "note": note}
        return bid

    def book(self, bid: str) -> dict | None:
        with self._lock:
            b = self.books.get(bid)
            return dict(b) if b else None

    def rename_book(self, bid: str, title: str) -> None:
        with self._lock:
            if bid in self.books:
                self.books[bid]["title"] = title.strip() or self.books[bid]["title"]

    def set_book_cover(self, bid: str, source: str) -> None:
        """source: "" 自动（首话首图） | "cid:<话id>" | "file:<图片路径>" """
        with self._lock:
            if bid in self.books:
                self.books[bid]["cover"] = source

    def remove_book(self, bid: str) -> None:
        """移除书及其话记录（不删除磁盘文件）。"""
        with self._lock:
            self.books.pop(bid, None)
            for cid in [c for c, v in self.chapters.items() if v.get("book") == bid]:
                self.chapters.pop(cid, None)
                self.history.pop(cid, None)

    def book_list(self) -> list[dict]:
        with self._lock:
            out = []
            for bid, b in self.books.items():
                e = dict(b)
                e["stats"] = self.book_stats(bid)
                out.append(e)
            out.sort(key=lambda x: x.get("added", 0))
            return out

    def book_cover_source(self, bid: str):
        """返回 (cid_or_None, custom_png_or_None)。"""
        with self._lock:
            b = self.books.get(bid)
            if not b:
                return None, None
            cover = b.get("cover") or ""
            if cover.startswith("file:"):
                return None, cover[5:]
            if cover.startswith("cid:"):
                cid = cover[4:]
                if cid in self.chapters:
                    return cid, None
            chs = self.chapters_of(bid)
            return (chs[0]["id"] if chs else None), None

    # ================= 话 =================
    def add_chapter(self, bid: str, path: str, name: str = "", kind: str = "file",
                    size: int = 0, mtime: float = 0.0) -> str:
        cid = chapter_id(path)
        p = Path(path)
        with self._lock:
            self.chapters[cid] = {
                "id": cid, "book": bid, "path": str(p),
                "kind": kind, "name": (name or p.stem or p.name).strip(),
                "size": size or (p.stat().st_size if p.is_file() else 0),
                "mtime": mtime or (p.stat().st_mtime if p.exists() else 0),
                "added": time.time(),
            }
        return cid

    def chapter(self, cid: str) -> dict | None:
        with self._lock:
            c = self.chapters.get(cid)
            return dict(c) if c else None

    def book_order(self, bid: str) -> str:
        with self._lock:
            mode = (self.books.get(bid) or {}).get("order", DEFAULT_ORDER)
        return mode if mode in ORDER_MODES else DEFAULT_ORDER

    def set_book_order(self, bid: str, mode: str) -> None:
        with self._lock:
            if bid in self.books and mode in ORDER_MODES:
                self.books[bid]["order"] = mode

    def chapters_of(self, bid: str, order: str | None = None) -> list[dict]:
        """按本书设置的排列方式返回各话。

        source（默认）= 按导入先后，不做任何重排；其余模式按名称解析。
        """
        with self._lock:
            items = [dict(v) for v in self.chapters.values() if v.get("book") == bid]
            mode = order or (self.books.get(bid) or {}).get("order", DEFAULT_ORDER)
        if mode not in ORDER_MODES:
            mode = DEFAULT_ORDER
        if mode == "source":
            # 稳定排序：added 相同（或缺失）时保留 dict 的插入顺序
            items.sort(key=lambda x: float(x.get("added", 0) or 0))
        else:
            items.sort(key=lambda x: chapter_order_key(x, mode))
        return items

    def rename_chapter(self, cid: str, name: str) -> None:
        with self._lock:
            if cid in self.chapters and name.strip():
                self.chapters[cid]["name"] = name.strip()

    def remove_chapter(self, cid: str) -> None:
        with self._lock:
            self.chapters.pop(cid, None)

    def chapter_book_title(self, cid: str) -> str:
        with self._lock:
            c = self.chapters.get(cid)
            if not c:
                return ""
            return (self.books.get(c.get("book"), {}) or {}).get("title", "")

    # ================= 进度 / 历史 =================
    def touch_history(self, cid: str, name: str, page: int, total: int,
                      pos: float = 0.0, count: bool = False) -> None:
        with self._lock:
            h = self.history.get(cid) or {}
            h["name"] = name
            h["page"] = int(page)
            h["total"] = int(total)
            h["pos"] = float(pos)
            h["time"] = time.time()
            h["count"] = int(h.get("count", 0)) + (1 if count else 0)
            self.history[cid] = h

    def progress(self, cid: str) -> dict | None:
        with self._lock:
            return self.history.get(cid)

    def mark_finished(self, cid: str, finished: bool = True) -> None:
        with self._lock:
            h = self.history.setdefault(cid, {})
            h["finished"] = finished

    def book_stats(self, bid: str) -> dict:
        with self._lock:
            chs = [dict(v) for v in self.chapters.values() if v.get("book") == bid]
            total = len(chs)
            read = finished = 0
            last_time = 0.0
            last_cid = ""
            times = 0
            for c in chs:
                h = self.history.get(c["id"]) or {}
                if h.get("total"):
                    read += 1
                    times += int(h.get("count", 0) or 0)
                    if h.get("finished"):
                        finished += 1
                    if (h.get("time") or 0) > last_time:
                        last_time = h["time"]
                        last_cid = c["id"]
            return {"chapters": total, "read": read, "finished": finished,
                    "times": times, "last_time": last_time, "last_cid": last_cid,
                    "ratio": (finished / total) if total else 0.0}

    def last_chapter(self, bid: str) -> dict | None:
        """继续阅读：最近读过但未读完的一话，否则第一话。"""
        chs = self.chapters_of(bid)
        if not chs:
            return None
        best, best_time = None, -1.0
        for c in chs:
            h = self.history.get(c["id"]) or {}
            if h.get("total") and not h.get("finished"):
                t = h.get("time") or 0
                if t > best_time:
                    best, best_time = c, t
        if best:
            return best
        for c in chs:
            if not (self.history.get(c["id"]) or {}).get("finished"):
                return c
        return chs[0]

    def recent_chapters(self, limit: int = 12) -> list[dict]:
        with self._lock:
            items = []
            for cid, h in self.history.items():
                c = self.chapters.get(cid)
                if not c:
                    continue
                e = dict(h)
                e["key"] = cid
                e["path"] = c.get("path", "")
                e["kind"] = c.get("kind", "file")
                e["name"] = c.get("name", h.get("name", ""))
                e["book"] = c.get("book", "")
                e["book_title"] = (self.books.get(c.get("book")) or {}).get("title", "")
                items.append(e)
            items.sort(key=lambda x: x.get("time", 0), reverse=True)
            return items[:limit]

    def clear_history(self) -> None:
        with self._lock:
            self.history.clear()

    # ---- 兼容旧调用（历史页/统计用）----
    def recent(self, limit: int = 12) -> list[dict]:
        return self.recent_chapters(limit)


STORE = Store()
