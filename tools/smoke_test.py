"""无头冒烟测试：验证导入 / 书架 / 阅读 / 伪装 / 各页面渲染，并输出截图。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt                  # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402

from app.main_window import MainWindow              # noqa: E402
from app.store import CACHE_DIR, STORE              # noqa: E402
from app.tasks import ASYNC                         # noqa: E402
from app.theme import QSS                           # noqa: E402

DEMO = r"C:\Users\Arelq_\Desktop\各种bat脚本\manga_speace_ccb\O1"
SHOTS = CACHE_DIR / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
FAILS: list[str] = []


def pump(seconds: float, cond=None):
    end = time.time() + seconds
    app = QApplication.instance()
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


def main() -> int:
    app = QApplication([])
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    pump(0.6)

    # ---------- 1. 导入 ----------
    done = {"n": -1}
    ASYNC.sig.import_done.connect(lambda added, skipped: done.update(n=len(added)))
    win.start_import([DEMO], copy=False)
    pump(60, lambda: done["n"] >= 0)
    total = len(STORE.shelf_entries())
    check("批量导入", total >= 74, f"书架 {total} 本，新增 {done['n']}")
    win.switch(0)
    pump(6, lambda: any(t.cover.pixmap() and not t.cover.pixmap().isNull()
                        for t in win.shelf_page._tiles.values()))
    tiles = win.shelf_page._tiles
    with_cover = sum(1 for t in tiles.values()
                     if t.cover.pixmap() and not t.cover.pixmap().isNull())
    check("封面异步生成", with_cover >= 10, f"{with_cover}/{len(tiles)} 张已就绪")
    win.grab().save(str(SHOTS / "01_shelf.png"))

    # ---------- 2. 搜索 / 排序 ----------
    win.shelf_page.search.setText("第1")
    pump(1.2)
    check("搜索过滤", 0 < len(win.shelf_page._tiles) < total,
          f"命中 {len(win.shelf_page._tiles)}")
    win.shelf_page.search.clear()
    pump(0.8)
    win.shelf_page._set_sort("name", "书名")
    pump(0.8)

    # ---------- 3. 打开阅读 ----------
    entries = sorted(STORE.shelf_entries(), key=lambda e: e["name"])
    target = None
    for e in entries:
        if "13" in e["name"]:
            target = e
            break
    target = target or entries[0]
    win.open_book(target["path"], target["name"], target["key"])
    view = win.reader_page.view
    view.set_page(0, animate=False)          # 统一从第 1 页开始断言
    pump(15, lambda: view.pixmap(0) is not None)
    check("打开 CBZ", view.total > 0, f"{target['name']} · {view.total} 页")
    check("页面解码", view.pixmap(0) is not None and not view.pixmap(0).isNull())
    win.grab().save(str(SHOTS / "02_reader_scroll.png"))

    # 翻页 + 进度
    view.set_page(min(4, view.total - 1), animate=False)
    pump(10, lambda: view.pixmap(view.current) is not None)
    check("滚动模式翻页", view.current == min(4, view.total - 1), f"当前第 {view.current + 1} 页")
    view.toggle_mode()
    pump(10, lambda: view.pixmap(view.current) is not None)
    check("单页模式", view.mode == "single")
    win.grab().save(str(SHOTS / "03_reader_single.png"))
    view.zoom_by(1.5)
    pump(1.5)
    check("缩放", abs(view.zoom - 1.5) < 1e-6 and view.fit == "custom")
    view.set_fit("width")
    pump(1.0)
    view.toggle_mode()
    view._emit_progress()
    pump(0.4)
    h = STORE.progress(target["key"])
    check("历史记录写入", bool(h and h.get("total") == view.total),
          f"读到第 {(h or {}).get('page', 0) + 1} 页 / 次数 {(h or {}).get('count')}")

    # ---------- 4. 伪装 ----------
    for skin, name in (("excel", "04_camo_excel.png"), ("word", "05_camo_word.png"),
                       ("term", "06_camo_term.png")):
        STORE.set_cfg("camo.skin", skin)
        win.camo.apply_skin(skin)
        if not win._camo:
            win.toggle_camo()
        pump(0.5)
        win.camo.grab().save(str(SHOTS / name))
        check(f"伪装皮肤 {skin}", win._camo and win.camo.isVisible())
    win.toggle_camo()
    pump(0.4)
    check("退出伪装", not win._camo)

    # ---------- 5. 隐藏 / 恢复 ----------
    win.toggle_hide()
    pump(0.3)
    hidden = not win.isVisible()
    win.toggle_hide()
    pump(0.3)
    check("热键隐藏/恢复", hidden and win.isVisible())

    # ---------- 6. 全屏 / 窗口缩放 ----------
    win.toggle_fullscreen()
    pump(0.4)
    fs = win._full
    win.grab().save(str(SHOTS / "07_fullscreen.png"))
    win.toggle_fullscreen()
    pump(0.4)
    check("全屏切换", fs and not win._full)
    win.setGeometry(100, 80, 980, 640)
    pump(0.5)
    check("窗口缩放", win.width() == 980 and win.height() == 640, f"{win.width()}x{win.height()}")
    win.maximize_window()
    pump(0.5)
    check("最大化", win.is_maximized)
    win.restore_window()
    pump(0.4)

    # ---------- 7. 其他页面 ----------
    win.reader_page.back_requested.emit()
    pump(0.8)
    win.switch(1)
    pump(1.5)
    win.grab().save(str(SHOTS / "08_history.png"))
    check("历史页", win.history_page.lay.count() > 1
          or win.history_page.s1.lbl_v.text() != "0")
    win.switch(2)
    pump(0.8)
    win.grab().save(str(SHOTS / "09_settings.png"))
    check("设置页", win.settings_page.cmb_camo.count() == 3)

    # ---------- 8. 屏幕边缘小窗 ----------
    e = win.edge
    scr = e.screen().availableGeometry()
    r_edge = scr.x() + scr.width()
    pump(0.8)
    check("边缘小窗贴边常驻",
          e.isVisible() and abs(e.x() + e.width() - r_edge) <= 1
          and e.width() == e.collapsed_w(), f"x={e.x()} w={e.width()}")
    e.expand()
    pump(0.6)
    check("碰边滑出详情", e.expanded and e.width() == 272)
    check("小窗同步书目", bool(e._book) and "/" in e.lbl_page.text(),
          f"{(e._book or {}).get('name')} · {e.lbl_page.text()}")
    check("小窗最近在读列表", e.recent_count() >= 1, f"{e.recent_count()} 条")
    e.grab().save(str(SHOTS / "10_edge_expanded.png"))
    e.collapse()
    pump(0.6)
    check("鼠标离开自动收起", not e.expanded and e.width() == e.collapsed_w())
    e.set_side("left")
    pump(0.6)
    ok_left = abs(e.x() - scr.x()) <= 1 and e.width() == e.collapsed_w()
    e.set_side("right")
    pump(0.6)
    check("左右停靠切换", ok_left and abs(e.x() + e.width() - r_edge) <= 1, f"left_ok={ok_left}")
    e.set_shape("sliver")
    pump(0.6)
    ok_sliver = e.width() == 8 and not e.strip.isVisible()
    e.set_shape("strip")
    pump(0.6)
    check("细缝/封面条形态", ok_sliver and e.width() == 56)
    win.toggle_camo()
    pump(0.5)
    hidden = not e.isVisible()
    win.toggle_camo()
    pump(0.5)
    check("伪装时小窗隐身", hidden and e.isVisible())
    win.toggle_fullscreen()
    pump(0.5)
    fs_hidden = not e.isVisible()
    win.toggle_fullscreen()
    pump(0.5)
    check("全屏阅读时小窗隐身", fs_hidden and e.isVisible())

    # ---------- 9. 拖动与八向缩放 ----------
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    win.restore_window()
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
    check("拖动窗口", win.pos() != p0 and win.pos() == p0 + QPoint(60, 50),
          f"{p0.x()},{p0.y()} -> {win.pos().x()},{win.pos().y()}")

    g = win.geometry()
    gl = QPointF(g.x() + 3, g.y() + 300)
    gm = QPointF(g.x() - 57, g.y() + 300)
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
    check("下边缘缩放", win.height() == g.height() + 80 and win.y() == g.y(),
          f"h={win.height()}")

    STORE.save_all()
    win.hotkeys.stop()
    ASYNC.wait(2000)

    print("\n截图目录:", SHOTS)
    if FAILS:
        print("失败项:", ", ".join(FAILS))
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
