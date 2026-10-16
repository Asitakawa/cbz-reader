"""真机渲染预览：使用真实 windows 平台插件（窗口会出现几秒）生成截图。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication          # noqa: E402

from app.main_window import MainWindow              # noqa: E402
from app.store import CACHE_DIR, STORE              # noqa: E402
from app.tasks import ASYNC                         # noqa: E402
from app.theme import QSS                           # noqa: E402

OUT = CACHE_DIR / "_preview"
OUT.mkdir(parents=True, exist_ok=True)
DEMO = r"C:\Users\Arelq_\Desktop\各种bat脚本\manga_speace_ccb\O1"


def pump(seconds: float, cond=None):
    app = QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.02)
    return bool(cond and cond())


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.resize(1280, 812)
    win.show()
    pump(1.0)

    if len(STORE.shelf_entries()) < 74:
        win.start_import([DEMO], copy=False)
        pump(20, lambda: len(STORE.shelf_entries()) >= 74)

    win.switch(0)
    pump(1.0)
    pump(12, lambda: all(t.cover.pixmap() and not t.cover.pixmap().isNull()
                         for t in list(win.shelf_page._tiles.values())[:12]))
    win.grab().save(str(OUT / "01_书架.png"))

    entries = sorted(STORE.shelf_entries(), key=lambda e: e["name"])
    e = next((x for x in entries if "13" in x["name"]), entries[0])
    win.open_book(e["path"], e["name"], e["key"])
    pump(3, lambda: win.reader_page.view.pixmap(0) is not None)
    win.grab().save(str(OUT / "02_阅读器_滚动.png"))

    win.reader_page.view.set_page(min(2, win.reader_page.view.total - 1), animate=False)
    pump(1.5)
    win.reader_page.view.toggle_mode()
    pump(6, lambda: win.reader_page.view.pixmap(win.reader_page.view.current) is not None)
    win.grab().save(str(OUT / "03_阅读器_单页.png"))
    win.reader_page.back_requested.emit()
    pump(1.0)

    win.switch(1)
    pump(1.2)
    win.grab().save(str(OUT / "04_历史记录.png"))

    win.switch(2)
    pump(0.8)
    win.grab().save(str(OUT / "05_设置.png"))

    for skin, name in (("excel", "06_伪装_Excel.png"), ("word", "07_伪装_Word.png"),
                       ("term", "08_伪装_CMD.png")):
        STORE.set_cfg("camo.skin", skin)
        win.camo.apply_skin(skin)
        if not win._camo:
            win.toggle_camo()
        pump(0.5)
        win.camo.grab().save(str(OUT / name))
    win.toggle_camo()
    pump(0.4)

    # 边缘小窗
    e = win.edge
    e.set_shape("strip")
    e.set_side("right")
    pump(0.6)
    e.start()
    pump(0.4)
    e.grab().save(str(OUT / "09_边缘小窗_收起.png"))
    e.expand()
    pump(1.0)
    e.grab().save(str(OUT / "10_边缘小窗_展开.png"))
    e.collapse()
    pump(0.5)

    STORE.save_all()
    win.hotkeys.stop()
    ASYNC.wait(2000)
    print("预览已生成:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
