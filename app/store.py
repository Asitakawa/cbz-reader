"""配置 / 历史记录 / 书架数据库 —— JSON 持久化（原子写入）。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
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
LIB_DIR = APP_DIR / "library"

for _d in (DATA_DIR, CACHE_DIR, COVER_DIR, SIZE_DIR, LIB_DIR):
    _d.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.json"
SHELF_FILE = DATA_DIR / "shelf.json"

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
        "gap": 10,
    },
    "window": {"w": 1200, "h": 780, "x": None, "y": None, "opacity": 1.0},
    "import": {"on_conflict": "skip"},   # skip | overwrite | rename
    "edge": {
        "enabled": True,
        "side": "right",      # right | left
        "shape": "strip",     # strip=封面条(56px) | sliver=细缝(8px)
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
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Store:
    """线程安全的配置 + 数据存取。"""

    def __init__(self):
        self._lock = threading.RLock()
        self.config = _deep_merge(DEFAULTS, self._read(CONFIG_FILE, {}))
        self.history: dict = self._read(HISTORY_FILE, {})
        self.shelf: dict = self._read(SHELF_FILE, {})   # key -> {path, name, size, mtime, added}
        self._dirty = set()

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
            self._write(SHELF_FILE, self.shelf)

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

    # ---------- 书架 ----------
    def add_book(self, path: str, name: str, size: int, mtime: float) -> str:
        from .cbr import book_key
        key = book_key(path)
        with self._lock:
            self.shelf[key] = {
                "path": str(path), "name": name, "size": size,
                "mtime": mtime, "added": time.time(),
            }
        return key

    def remove_book(self, key: str) -> None:
        with self._lock:
            self.shelf.pop(key, None)
            self.history.pop(key, None)

    def shelf_entries(self) -> list[dict]:
        with self._lock:
            items = []
            for k, v in self.shelf.items():
                if not Path(v.get("path", "")).exists():
                    continue
                e = dict(v)
                e["key"] = k
                items.append(e)
            items.sort(key=lambda x: x.get("added", 0))
            return items

    # ---------- 历史 ----------
    def touch_history(self, key: str, name: str, page: int, total: int,
                      pos: float = 0.0, count: bool = False) -> None:
        with self._lock:
            h = self.history.get(key) or {}
            h["name"] = name
            h["page"] = int(page)
            h["total"] = int(total)
            h["pos"] = float(pos)
            h["time"] = time.time()
            h["count"] = int(h.get("count", 0)) + (1 if count else 0)
            self.history[key] = h

    def progress(self, key: str) -> dict | None:
        with self._lock:
            return self.history.get(key)

    def recent(self, limit: int = 12) -> list[dict]:
        with self._lock:
            items = []
            for k, h in self.history.items():
                if k not in self.shelf:
                    continue
                e = dict(h)
                e["key"] = k
                e["path"] = self.shelf[k].get("path", "")
                e["name"] = self.shelf[k].get("name", h.get("name", ""))
                items.append(e)
            items.sort(key=lambda x: x.get("time", 0), reverse=True)
            return items[:limit]

    def clear_history(self) -> None:
        with self._lock:
            self.history.clear()

    def mark_finished(self, key: str, finished: bool = True) -> None:
        with self._lock:
            h = self.history.setdefault(key, {})
            h["finished"] = finished


STORE = Store()
