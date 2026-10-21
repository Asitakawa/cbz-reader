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

    # 保证至少有一本书（首次运行会把旧书架迁移成《O1》）
    if not STORE.book_list() and Path(DEMO).exists():
        win.start_import([DEMO], copy=False)
        pump(30, lambda: bool(STORE.book_list()))
    books = STORE.book_list()
    if not books:
        print("书架为空，无法生成预览")
        return 1
    target = max(books, key=lambda b: b["stats"]["chapters"])

    # 1. 书架（书封面墙）
    win.switch(0)
    pump(1.0)
    pump(15, lambda: all(t.cover.pixmap() and not t.cover.pixmap().isNull()
                         for t in list(win.shelf_page._tiles.values())[:1]))
    win.grab().save(str(OUT / "01_书架.png"))

    # 2. 书详情（各话列表）
    win.open_book_detail(target["id"])
    pump(2.5, lambda: len(win.book_page._rows) > 0)
    pump(2.0)
    win.grab().save(str(OUT / "02_书详情.png"))

    # 3. 阅读器
    chs = STORE.chapters_of(target["id"])
    pick = chs[min(len(chs) - 1, len(chs) // 3)]
    win.open_chapter(pick["path"], pick["name"], pick["id"])
    pump(4, lambda: win.reader_page.view.pixmap(0) is not None)
    pump(1.5)
    win.grab().save(str(OUT / "03_阅读器_滚动.png"))
    win.reader_page.view.set_page(min(2, win.reader_page.view.total - 1), animate=False)
    win.reader_page.view.toggle_mode()
    pump(6, lambda: win.reader_page.view.pixmap(win.reader_page.view.current) is not None)
    pump(1.0)
    win.grab().save(str(OUT / "04_阅读器_单页.png"))
    win.back_from_reader()
    pump(1.0)

    # 4. 历史 / 设置
    win.switch(1)
    pump(1.5)
    win.grab().save(str(OUT / "05_历史记录.png"))
    win.switch(2)
    pump(0.8)
    win.grab().save(str(OUT / "06_设置.png"))

    # 5. 伪装皮肤
    for skin, name in (("excel", "07_伪装_Excel.png"), ("word", "08_伪装_Word.png"),
                       ("term", "09_伪装_CMD.png")):
        STORE.set_cfg("camo.skin", skin)
        win.camo.apply_skin(skin)
        if not win._camo:
            win.toggle_camo()
        pump(0.5)
        win.camo.grab().save(str(OUT / name))
    win.toggle_camo()
    pump(0.4)

    # 6. 边缘迷你阅读器
    e = win.edge
    e.set_shape("sliver")
    e.set_side("right")
    pump(0.8)
    e.start()
    pump(0.5)
    e.grab().save(str(OUT / "10_迷你阅读器_细缝.png"))
    e._poll.stop()
    e.expand()
    pump(1.2)
    pump(12, lambda: e._cache.get(e._page) is not None)
    pump(1.0)
    e._show_bar()
    pump(0.4)
    e.grab().save(str(OUT / "11_迷你阅读器_滑出.png"))
    e.collapse()
    pump(0.6)
    e._poll.start()

    STORE.save_all()
    win.hotkeys.stop()
    ASYNC.wait(2000)
    print("预览已生成:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
