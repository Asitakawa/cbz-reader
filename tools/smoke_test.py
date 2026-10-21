"""无头冒烟测试：书→话两层模型（新增书 / 导入 / 书详情 / 阅读 / 复制入库 / 伪装 / 边缘小窗 / 窗口交互）。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt              # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

from app.cbr import ComicSource                    # noqa: E402
from app.main_window import MainWindow             # noqa: E402
from app.store import CACHE_DIR, DATA_DIR, STORE   # noqa: E402
from app.tasks import ASYNC                        # noqa: E402
from app.theme import QSS                          # noqa: E402

DEMO = r"C:\Users\Arelq_\Desktop\各种bat脚本\manga_speace_ccb\O1"
SHOTS = CACHE_DIR / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
FAILS: list[str] = []


def pump(seconds: float, cond=None):
    app = QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.02)
    return bool(cond and cond())


def check(name: str, ok: bool, extra: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {name} {extra}")
    if not ok:
        FAILS.append(name)


class ImportWaiter:
    """等待一次导入完成。"""

    def __init__(self):
        self.records = None
        self.skipped = None
        ASYNC.sig.import_done.connect(self._on_done)

    def _on_done(self, records, skipped):
        if self.records is None:
            self.records, self.skipped = records, skipped


def make_test_images() -> Path:
    from PIL import Image, ImageDraw
    d = CACHE_DIR / "_test_chapter"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        im = Image.new("RGB", (240, 340), (245, 240, 232))
        dr = ImageDraw.Draw(im)
        dr.rectangle([10, 10, 229, 329], outline=(120, 120, 130), width=3)
        dr.text((20, 20), f"test page {i + 1}", fill=(40, 40, 50))
        im.save(d / f"{i + 1:03d}.png")
    return d


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    pump(0.6)

    # ---------- 1. 数据模型：书 → 话 ----------
    books = STORE.book_list()
    check("书架按「书」组织", len(books) >= 1,
          f"{len(books)} 本：" + "、".join(b["title"] for b in books[:3]))
    check("旧扁平书架已迁移",
          (DATA_DIR / "shelf.json.migrated").exists() or not (DATA_DIR / "shelf.json").exists())
    target = max(books, key=lambda b: b["stats"]["chapters"])
    check("一本书内含多话", target["stats"]["chapters"] > 1,
          f"《{target['title']}》共 {target['stats']['chapters']} 话")

    # ---------- 2. 新增书 ----------
    bid_new = STORE.add_book("临时测试书")
    STORE.save_all()
    win.shelf_page.refresh()
    pump(0.5)
    check("新增书出现在书架", bid_new in win.shelf_page._tiles,
          f"书架 {len(win.shelf_page._tiles)} 本")
    win.grab().save(str(SHOTS / "11_shelf_books.png"))

    # ---------- 3. 导入图片文件夹（一话 = 一个文件夹） ----------
    tdir = make_test_images()
    w1 = ImportWaiter()
    win.start_import([str(tdir)], bid=bid_new, copy=False)
    pump(30, lambda: w1.records is not None)
    chs_new = STORE.chapters_of(bid_new)
    dir_ch = next((c for c in chs_new if c["kind"] == "dir"), None)
    check("导入图片文件夹为一话", dir_ch is not None,
          f"{len(chs_new)} 话 / 类型 {[c['kind'] for c in chs_new]}")
    if dir_ch:
        src = ComicSource(dir_ch["path"])
        check("文件夹型一话可解析", src.page_count == 3, f"{src.page_count} 页")
        src.close()

    # ---------- 4. 书详情页 ----------
    pump(0.8)                      # 导入完成后会延时自动打开该书，先让它跑完
    win.open_book_detail(target["id"])
    pump(1.0)
    n_ch = len(STORE.chapters_of(target["id"]))
    check("书详情页列出各话", len(win.book_page._rows) == n_ch, f"{n_ch} 话")
    win.grab().save(str(SHOTS / "12_book_detail.png"))

    # ---------- 5. 阅读 ----------
    chs = STORE.chapters_of(target["id"])
    pick = chs[min(3, len(chs) - 1)]
    win.open_chapter(pick["path"], pick["name"], pick["id"])
    view = win.reader_page.view
    view.set_page(0, animate=False)
    pump(15, lambda: view.pixmap(0) is not None)
    check("打开一话", view.total > 0, f"{pick['name']} · {view.total} 页")
    check("页面解码", view.pixmap(0) is not None)
    win.grab().save(str(SHOTS / "13_reader.png"))

    view.set_page(min(4, view.total - 1), animate=False)
    pump(10, lambda: view.pixmap(view.current) is not None)
    check("翻页", view.current == min(4, view.total - 1), f"第 {view.current + 1} 页")
    view.toggle_mode()
    pump(8, lambda: view.pixmap(view.current) is not None)
    check("单页模式", view.mode == "single")
    view.zoom_by(1.5)
    pump(1.0)
    check("缩放", abs(view.zoom - 1.5) < 1e-6)
    view.set_fit("width")
    view.toggle_mode()
    view._emit_progress()
    pump(0.4)
    h = STORE.progress(pick["id"])
    check("历史按「话」记录", bool(h and h.get("total") == view.total),
          f"第 {(h or {}).get('page', 0) + 1} 页")
    st = STORE.book_stats(target["id"])
    check("书进度聚合", st["read"] >= 1 and st["last_cid"] != "",
          f"已读 {st['read']}/{st['chapters']} 话")
    last = STORE.last_chapter(target["id"])
    check("继续阅读可定位", last is not None, (last or {}).get("name", ""))

    # 返回链路：阅读器 → 书详情 → 书架
    win.back_from_reader()
    pump(0.6)
    check("阅读后返回书详情", win.stack.currentWidget() is win.book_page,
          win.book_page.book_title())
    win.book_page.back_requested.emit()
    pump(0.5)
    check("书详情返回书架", win.stack.currentWidget() is win.shelf_page)

    # ---------- 6. 搜索 / 排序 ----------
    win.shelf_page.search.setText("临时")
    pump(0.6)
    check("搜索书", len(win.shelf_page._tiles) >= 1, f"命中 {len(win.shelf_page._tiles)}")
    win.shelf_page.search.clear()
    pump(0.4)
    win.shelf_page._set_sort("chapters", "话数")
    pump(0.4)

    # ---------- 7. 复制入库（用一个本次唯一的 cbz，避免同名跳过干扰） ----------
    import zipfile
    zpath = CACHE_DIR / f"_test_copy_{int(time.time())}.cbz"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((CACHE_DIR / "_test_chapter").glob("*.png")):
            z.write(p, p.name)
    before = len(STORE.chapters_of(bid_new))
    w2 = ImportWaiter()
    win.start_import([str(zpath)], bid=bid_new, copy=True)
    pump(40, lambda: w2.records is not None)
    after_chs = STORE.chapters_of(bid_new)
    lib = str(Path(STORE.cfg("library_dir"))).lower()
    copied = [c for c in after_chs if c["path"].lower().startswith(lib)]
    check("复制入库到书库目录", len(after_chs) == before + 1 and bool(copied),
          f"{before} → {len(after_chs)} 话")
    if copied:
        src2 = ComicSource(copied[0]["path"])
        check("复制后的文件可读", src2.page_count == 3, f"{src2.page_count} 页")
        src2.close()

    # ---------- 8. 边缘迷你阅读器 ----------
    e = win.edge
    scr = e.screen().availableGeometry()
    r_edge = scr.x() + scr.width()
    e.set_shape("sliver")            # 归一化到细缝，避免受上次运行残留影响
    pump(0.8)
    check("细缝贴边隐藏",
          e.isVisible() and abs(e.x() + e.width() - r_edge) <= 1
          and e.width() == 6 and not e.card.isVisible(),
          f"x={e.x()} w={e.width()}")
    check("小窗已绑定当前章节", bool(e.current_chapter().get("cid")),
          e.current_chapter().get("name", ""))
    e._poll.stop()                       # 测试期间关闭「离开自动收起」，避免光标不在边上
    e.expand()
    pump(1.0)
    check("碰边滑出阅读窗", e.expanded and e.width() == 420 and e.card.isVisible(),
          f"w={e.width()}")
    pump(10, lambda: e._cache.get(e._page) is not None)
    check("小窗内渲染页面", e.canvas._pm is not None,
          f"第 {e._page + 1} 页已解码")
    e.grab().save(str(SHOTS / "14_edge_reader.png"))
    p0 = e._page
    e.turn(1)
    pump(1.0)
    check("小窗内翻页", e._page == p0 + 1, f"{p0 + 1} → {e._page + 1}")
    cid_now = e.current_chapter()["cid"]
    check("翻页写回阅读进度",
          int((STORE.progress(cid_now) or {}).get("page", -1)) == e._page)
    e._tick()                     # 模拟光标已离开（无延迟，应立刻缩回）
    pump(0.5)
    check("鼠标离开立即缩回细缝",
          not e.expanded and e.width() == 6 and not e.card.isVisible(), f"w={e.width()}")
    e.expand()
    pump(0.6)
    w0 = e.width()
    e.canvas.zoomed.emit(1)       # Ctrl+滚轮
    pump(0.8)
    zoomed_ok = e.width() == w0 + 40
    e.canvas.zoomed.emit(-1)
    pump(0.8)
    check("Ctrl+滚轮调整阅读窗大小", zoomed_ok and e.width() == w0,
          f"{w0} → {w0 + 40} → {e.width()}")
    e._tick()
    pump(0.4)
    e.set_shape("strip")
    pump(0.6)
    strip_ok = e.width() == 40
    e.set_shape("sliver")
    pump(0.6)
    check("细缝/窄条切换", strip_ok and e.width() == 6)
    e.set_side("left")
    pump(0.6)
    left_ok = abs(e.x() - scr.x()) <= 1
    e.set_side("right")
    pump(0.6)
    check("左右停靠", left_ok)
    e._poll.start()                      # 恢复自动收起

    # ---------- 9. 伪装 / 隐藏 / 全屏 ----------
    skins = ["excel", "word", "term"]
    for i, skin in enumerate(skins):
        STORE.set_cfg("camo.skin", skin)
        win.camo.apply_skin(skin)
        if not win._camo:
            win.toggle_camo()
        pump(0.4)
        win.camo.grab().save(str(SHOTS / f"1{5 + i}_camo_{skin}.png"))
        check(f"伪装皮肤 {skin}", win._camo and win.camo.isVisible())
        if skin == "excel":
            check("伪装时小窗隐身", not e.isVisible())
    win.toggle_camo()
    pump(0.4)
    check("退出伪装恢复小窗", not win._camo and e.isVisible())

    win.toggle_hide()
    pump(0.5)
    hidden = not win.isVisible()
    edge_hidden = not e.isVisible()
    win.toggle_hide()
    pump(0.8)
    check("热键隐藏时迷你阅读器一起藏起",
          hidden and edge_hidden and win.isVisible() and e.isVisible())
    win.toggle_fullscreen()
    pump(0.4)
    fs = win._full
    win.toggle_fullscreen()
    pump(0.4)
    check("全屏切换", fs and not win._full)
    win.maximize_window()
    pump(0.4)
    check("最大化", win.is_maximized)
    win.restore_window()
    pump(0.3)

    # ---------- 10. 拖动与八向缩放 ----------
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    win.setGeometry(300, 200, 1000, 660)
    pump(0.3)
    tb, p0 = win.title_bar, win.pos()
    g1 = QPointF(p0.x() + 80, p0.y() + 20)
    g2 = QPointF(p0.x() + 140, p0.y() + 70)
    QApplication.sendEvent(tb, QMouseEvent(QEvent.MouseButtonPress, QPointF(80, 20), g1,
                                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(tb, QMouseEvent(QEvent.MouseMove, QPointF(140, 70), g2,
                                           Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(tb, QMouseEvent(QEvent.MouseButtonRelease, QPointF(140, 70), g2,
                                           Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    pump(0.3)
    check("拖动窗口", win.pos() == p0 + QPoint(60, 50),
          f"{p0.x()},{p0.y()} → {win.pos().x()},{win.pos().y()}")

    g = win.geometry()
    gl, gm = QPointF(g.x() + 3, g.y() + 300), QPointF(g.x() - 57, g.y() + 300)
    QApplication.sendEvent(win, QMouseEvent(QEvent.MouseButtonPress, QPointF(3, 300), gl,
                                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(win, QMouseEvent(QEvent.MouseMove, QPointF(-57, 300), gm,
                                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(win, QMouseEvent(QEvent.MouseButtonRelease, QPointF(-57, 300), gm,
                                            Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    pump(0.3)
    check("左边缘缩放", win.width() == 1060 and win.x() == g.x() - 60,
          f"x={win.x()} w={win.width()}")

    g = win.geometry()
    gb = QPointF(g.x() + 500, g.y() + g.height() - 3)
    QApplication.sendEvent(win, QMouseEvent(QEvent.MouseButtonPress,
                                            QPointF(500, g.height() - 3), gb,
                                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(win, QMouseEvent(QEvent.MouseMove, QPointF(500, g.height() + 77),
                                            QPointF(gb.x(), gb.y() + 80),
                                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(win, QMouseEvent(QEvent.MouseButtonRelease, QPointF(500, g.height() + 77),
                                            QPointF(gb.x(), gb.y() + 80),
                                            Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    pump(0.3)
    check("下边缘缩放", win.height() == g.height() + 80, f"h={win.height()}")

    # ---------- 11. 其他页面 ----------
    win.switch(1)
    pump(1.2)
    win.grab().save(str(SHOTS / "18_history.png"))
    check("历史页（含书名）", win.history_page.lay.count() > 1)
    win.switch(2)
    pump(0.6)
    win.grab().save(str(SHOTS / "19_settings.png"))
    check("设置页", win.settings_page.cmb_camo.count() == 3)

    # 清理测试书（文件保留）/ 清掉本次复制进书库的测试文件
    for c in copied:
        try:
            Path(c["path"]).unlink()
        except Exception:
            pass
    for c in STORE.chapters_of(bid_new):
        STORE.remove_chapter(c["id"])
    STORE.remove_book(bid_new)
    STORE.save_all()
    win.shelf_page.refresh()

    ASYNC.wait(2000)
    print("\n截图目录:", SHOTS)
    if FAILS:
        print("失败项:", ", ".join(FAILS))
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
