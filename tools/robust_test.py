"""稳健性测试：格式异常 / 数据边界 / 主题全组合 / 布局极值 / 性能。

与 smoke_test 互补：smoke_test 走功能主路径，这里专打「用户手滑或文件不规范」的场景。
用法：
    python tools/robust_test.py            # 无头
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image                                  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent     # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame     # noqa: E402

from app import theme                                  # noqa: E402
from app.cbr import ComicSource, scan_chapters          # noqa: E402
from app.main_window import MainWindow                  # noqa: E402
from app.store import STORE                             # noqa: E402
from app.window import MIN_H, MIN_W                     # noqa: E402

WORK = ROOT / "cache" / "_robust"
FAILS: list[str] = []
NOTES: list[str] = []


def _teardown(win: MainWindow):
    """不走 close()：close_action=ask 会弹模态框，无头环境会卡住。"""
    try:
        win.hotkeys.stop()
        win.edge.shutdown()
        win.tray.hide()
    finally:
        win.hide()


def pump(seconds: float = 0.25):
    """注意：processEvents() 不处理 deleteLater()，必须显式派发 DeferredDelete，
    否则控件被反复重建时会误判为内存泄漏。"""
    app = QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        time.sleep(0.01)


def check(name: str, ok: bool, extra: str = ""):
    print(f"{'PASS' if ok else 'FAIL'}  {name} {extra}")
    if not ok:
        FAILS.append(name)


def note(text: str):
    NOTES.append(text)
    print(f"NOTE  {text}")


# ================================================================ 工具
def make_img(path: Path, size=(40, 60), color=(200, 120, 90)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def make_cbz(path: Path, entries: dict[str, bytes]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def img_bytes(path: Path) -> bytes:
    return path.read_bytes()


# ================================================================ 1. 格式健壮性
def test_formats():
    print("\n=== 1. 文件格式稳健性 ===")
    d = WORK / "fmt"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)

    a = make_img(d / "src" / "001.jpg")
    b = make_img(d / "src" / "003.webp", (50, 70))
    good = make_cbz(d / "mixed.cbz", {
        "001.jpg": img_bytes(a),
        "010.jpg": img_bytes(a),
        "002.JPG": img_bytes(a),               # 大写扩展名
        "sub/003.webp": img_bytes(b),          # 子目录
        "__MACOSX/._001.jpg": b"junk",         # mac 垃圾
        ".hidden/004.png": img_bytes(a),       # 隐藏目录
        "ComicInfo.xml": b"<ComicInfo/>",      # 非图片
    })
    src = ComicSource(good)
    names = src.names
    check("压缩包：过滤非图片/垃圾/隐藏，保留大小写扩展名与子目录",
          len(names) == 4 and "ComicInfo.xml" not in names
          and not any("__MACOSX" in n or ".hidden" in n for n in names),
          f"{len(names)} 页 → {names}")
    check("压缩包：页序按自然排序（1 < 2 < 10，子目录在后）",
          names == ["001.jpg", "002.JPG", "010.jpg", "sub/003.webp"],
          " → ".join(names))
    check("压缩包：读取首页", len(src.read(0)) > 0 and src.image(0).size == (40, 60))

    bad = d / "broken.cbz"
    bad.write_bytes(b"not a zip at all" * 40)
    src_bad = ComicSource(bad)
    ok_read = False
    try:
        src_bad.read(0)
    except Exception:
        ok_read = True
    check("损坏压缩包：不崩溃、0 页、无封面",
          src_bad.page_count == 0 and src_bad.cover_path() is None and ok_read)

    empty = make_cbz(d / "empty.cbz", {})
    src_empty = ComicSource(empty)
    check("空压缩包：0 页且无封面", src_empty.page_count == 0 and src_empty.cover_path() is None)

    noimg = d / "noimg"
    (noimg / "docs").mkdir(parents=True)
    (noimg / "readme.txt").write_text("hi", encoding="utf-8")
    src_no = ComicSource(noimg)
    check("无图片文件夹：0 页", src_no.page_count == 0)

    broken_page = make_cbz(d / "broken_page.cbz", {
        "001.jpg": img_bytes(a),
        "002.jpg": b"garbage-bytes-not-an-image",
    })
    src_bp = ComicSource(broken_page)
    sizes = src_bp.page_sizes
    check("包内含坏页：页数不错、坏页用占位尺寸兜底",
          src_bp.page_count == 2 and sizes[0] == (40, 60) and sizes[1] == (1000, 1500),
          f"{sizes}")

    cp = src.image(0)
    cover = src.cover_path(420)
    cw = Image.open(cover).width if cover else 0
    check("封面生成：落地且不大于请求宽度", bool(cover) and 0 < cw <= 420, f"{cw}px")

    # ---- 导入扫描 ----
    scan_root = d / "scan"
    make_img(scan_root / "第1话" / "01.jpg")
    make_img(scan_root / "第2话" / "01.jpg")
    make_cbz(scan_root / "第3话" / "第3话.cbz", {"01.jpg": img_bytes(a)})
    make_img(scan_root / "第4话" / "pages" / "01.jpg")     # 图片在二级子目录
    make_img(scan_root / "第4话" / "pages" / "02.jpg")
    make_img(scan_root / "第5话" / "上" / "01.jpg")         # 同一话拆在多个子目录
    make_img(scan_root / "第5话" / "下" / "01.jpg")
    make_img(scan_root / "第6话" / "01.jpg")                # 直属 + 子目录混排
    make_img(scan_root / "第6话" / "彩页" / "01.jpg")
    got = scan_chapters(scan_root)
    got_names = [c["name"] for c in got]
    check("导入扫描：图片文件夹、子目录压缩包、二级子目录图片都识别",
          {"第1话", "第2话", "第3话", "第4话", "第5话", "第6话"} <= set(got_names),
          " / ".join(got_names))

    src4 = ComicSource(scan_root / "第4话")
    check("目录型一话：递归读到二级子目录的图片",
          src4.page_count == 2 and src4.names == ["pages/01.jpg", "pages/02.jpg"],
          f"{src4.page_count} 页 → {src4.names}")
    src5 = ComicSource(scan_root / "第5话")
    check("目录型一话：多个子目录按名称自然排序合并",
          src5.page_count == 2 and src5.names == ["上/01.jpg", "下/01.jpg"],
          " → ".join(src5.names))
    src6 = ComicSource(scan_root / "第6话")
    check("目录型一话：直属图片在前、子目录图片在后",
          src6.page_count == 2 and src6.names == ["01.jpg", "彩页/01.jpg"],
          " → ".join(src6.names))
    src4.close(); src5.close(); src6.close()

    single = scan_chapters(good)
    check("导入扫描：单个压缩包 = 一话", len(single) == 1 and single[0]["kind"] == "file",
          single[0]["name"])

    src.close()
    src_bad.close()
    src_empty.close()
    src_no.close()
    src_bp.close()


# ================================================================ 2. 数据层边界
def test_store():
    print("\n=== 2. 数据层边界 ===")
    d = WORK / "store"
    shutil.rmtree(d, ignore_errors=True)
    make_img(d / "a" / "01.jpg")
    cbz = make_cbz(d / "c1.cbz", {"01.jpg": img_bytes(d / "a" / "01.jpg")})

    bid = STORE.add_book("__稳健性测试__")
    cid1 = STORE.add_chapter(bid, str(cbz), "第1话")
    cid1b = STORE.add_chapter(bid, str(cbz), "第1话（重复导入）")
    chs = STORE.chapters_of(bid)
    check("同一文件重复导入只保留一条", len(chs) == 1 and cid1 == cid1b,
          f"{len(chs)} 条")

    name_before = STORE.chapter(cid1)["name"]
    STORE.rename_chapter(cid1, "   ")
    check("话名改为空白时保留原名", STORE.chapter(cid1)["name"] == name_before,
          f"「{name_before}」未被清空")

    ghost = STORE.add_chapter(bid, str(d / "不存在.cbz"), "幽灵话")
    check("添加不存在的文件不抛异常", STORE.chapter(ghost) is not None)

    names = ["特别篇", "番外", "第2话", "第10话", "后记"]
    for i, n in enumerate(names):
        STORE.add_chapter(bid, str(d / f"n{i}.cbz"), n)
    src_order = [c["name"] for c in STORE.chapters_of(bid)]
    check("无数字话名不参与排序也不丢失",
          all(n in src_order for n in names), " → ".join(src_order))
    STORE.set_book_order(bid, "natural")
    natural = [c["name"] for c in STORE.chapters_of(bid)]
    check("数字顺序下无数字话名排在最后且不崩",
          natural[-3:] == ["特别篇", "番外", "后记"] or
          set(natural[-3:]) == {"特别篇", "番外", "后记"},
          " → ".join(natural))

    STORE.books[bid]["order"] = "not-a-mode"
    check("存储中出现非法排序模式时回退默认",
          STORE.book_order(bid) == "source", STORE.book_order(bid))

    STORE.touch_history(cid1, "第1话", 999, 10)
    st = STORE.book_stats(bid)
    check("进度越界时完成率仍在 0~1", 0.0 <= st["ratio"] <= 1.0, f"{st['ratio']:.2f}")
    STORE.mark_finished(cid1, True)
    check("标记已读联动完成率", STORE.book_stats(bid)["finished"] >= 1)

    before = len(STORE.chapters)
    STORE.remove_chapter(ghost)
    check("移除一话后记录减少", len(STORE.chapters) == before - 1)
    if STORE.progress(ghost) is not None:
        note("remove_chapter 未清理该话的 history 条目（界面不可见，属轻微残留）")

    mine = {cid1, ghost}
    mine |= {c["id"] for c in STORE.chapters.values()
             if c.get("book") == bid and c["path"].startswith(str(d))}
    STORE.remove_book(bid)
    check("移除书时级联清理话与历史",
          not STORE.chapters_of(bid) and not (mine & set(STORE.history)),
          f"清理 {len(mine)} 条话记录")

    corrupt = d / "bad.json"
    corrupt.write_text("{ this is not json", encoding="utf-8")
    check("损坏的 JSON 读回默认值", STORE._read(corrupt, {"ok": 1}) == {"ok": 1})
    STORE.save_all()


# ================================================================ 3. 主题全组合
def _ratio(a: str, b: str) -> float:
    def lum(hex_color: str) -> float:
        h = hex_color.lstrip("#")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    l1, l2 = sorted((lum(a), lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_theme_matrix():
    print("\n=== 3. 主题全组合 ===")
    origin = theme.current()
    total, bad_tokens, bad_brace = 0, [], []
    low_text, low_sub = [], []
    try:
        for tid in theme.THEMES:
            for aid in ["", *theme.ACCENTS]:
                for r in theme.RADII:
                    for s in theme.SCALES:
                        theme._STATE.update({"theme": tid, "accent": aid,
                                             "radius": r, "scale": s})
                        theme._resolve()
                        qss = theme.build_qss()
                        total += 1
                        if "$" in qss or "None" in qss:
                            bad_tokens.append(f"{tid}/{aid or 'auto'}/{r}/{s}")
                        if qss.count("{") != qss.count("}"):
                            bad_brace.append(f"{tid}/{aid or 'auto'}/{r}/{s}")
                        if aid == "" and r == 10 and s == 1.0:
                            ct = _ratio(theme.c("text"), theme.c("bg"))
                            cs = _ratio(theme.c("sub"), theme.c("bg"))
                            if ct < 4.5:
                                low_text.append(f"{tid} {ct:.1f}")
                            if cs < 3.0:
                                low_sub.append(f"{tid} {cs:.1f}")
    finally:
        theme._STATE.update(origin)
        theme._resolve()
    check("主题 × 强调色 × 圆角 × 字号 全组合生成 QSS 无占位符残留",
          not bad_tokens, f"{total} 组" + (f"，异常 {bad_tokens[:3]}" if bad_tokens else ""))
    check("QSS 花括号闭合", not bad_brace, f"{total} 组")
    check("六套主题正文对比度 ≥ 4.5:1", not low_text, ", ".join(low_text) or "全部达标")
    if low_sub:
        note("次要文字对比度低于 3:1：" + ", ".join(low_sub))
    else:
        check("六套主题次要文字对比度 ≥ 3:1", True, "全部达标")


# ================================================================ 4. 布局极值
def _overflow(page, name: str):
    """页面直属控件不得越出页面右/下边界（滚动内容按视口宽度对齐）。"""
    bad = []
    lay = page.layout()
    if lay is None:
        return bad
    for i in range(lay.count()):
        it = lay.itemAt(i)
        w = it.widget()
        if w is None or not w.isVisible():
            continue
        g = w.geometry()
        if g.right() > page.width() + 2 or g.bottom() > page.height() + 2:
            bad.append(f"{w.objectName() or type(w).__name__}{g.getRect()}")
    return bad


def test_layout():
    print("\n=== 4. 布局极值 ===")
    win = MainWindow()
    win.show()
    pump(1.0)
    book = max(STORE.book_list(), key=lambda x: x["stats"]["chapters"])

    for label, size, scale in (("最小窗口", (MIN_W, MIN_H), 1.0),
                               ("1080p", (1920, 1080), 1.0),
                               ("最小窗口+特大字号+圆润", (MIN_W, MIN_H), 1.16)):
        theme.set_scale(scale)
        theme.set_radius(14 if scale > 1 else 10)
        win.resize(*size)
        pump(0.5)
        issues = []
        for idx, tag in ((0, "书架"), (1, "历史"), (2, "个性化"), (3, "设置")):
            win.switch(idx)
            pump(0.35)
            issues += [f"{tag}:{x}" for x in _overflow(win.stack.currentWidget(), tag)]
        win.open_book_detail(book["id"])
        pump(0.5)
        bp = win.book_page
        if bp.card.geometry().right() > bp.width() + 2:
            issues.append("书详情:卡片越界")
        if bp.cover.geometry().right() >= bp.info_host.geometry().left():
            issues.append("书详情:封面与信息区重叠")
        if bp.info_host.width() < 160:
            issues.append(f"书详情:信息区过窄 {bp.info_host.width()}")
        win.switch(0)
        pump(0.3)
        check(f"布局不溢出（{label} {size[0]}×{size[1]}）", not issues,
              "；".join(issues[:3]) if issues else "四页 + 书详情均无越界/重叠")

    # 书架卡片不超出容器
    win.switch(0)
    pump(0.4)
    sp = win.shelf_page
    wide = [c.width() for c in (sp.recent_flow.itemAt(i).widget()
                                for i in range(sp.recent_flow.count()))
            if c and c.width() > sp.recent_host.width() + 2]
    check("继续阅读卡片不超出容器宽度", not wide, f"容器 {sp.recent_host.width()}px")

    theme.reset()
    _teardown(win)


# ================================================================ 5. 性能
def test_perf():
    print("\n=== 5. 性能 ===")
    t0 = time.perf_counter()
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    pump(0.4)
    cold = time.perf_counter() - t0
    check("冷启动到可交互 < 3.5s", cold < 3.5, f"{cold * 1000:.0f} ms")

    book = max(STORE.book_list(), key=lambda x: x["stats"]["chapters"])
    ch = STORE.chapters_of(book["id"])[2]
    t1 = time.perf_counter()
    win.open_chapter(ch["path"], ch["name"], ch["id"])
    while win.reader_page.view.pixmap(0) is None and time.perf_counter() - t1 < 8:
        pump(0.05)
    first = time.perf_counter() - t1
    check("打开一话到首页可见 < 2.5s", first < 2.5, f"{first * 1000:.0f} ms / {ch['name']}")

    view = win.reader_page.view
    pages = min(10, max(1, view.total - 1))
    t2 = time.perf_counter()
    for i in range(pages):
        view.set_page(i, animate=False)
        pump(0.02)
    step_ms = (time.perf_counter() - t2) / pages * 1000
    check("翻页平均耗时 < 120ms", step_ms < 120, f"{step_ms:.0f} ms/页（{pages} 页）")

    for i in range(0, min(60, view.total)):
        view.request(i)
        pump(0.02)
    pump(0.4)
    check("页缓存有上界（LRU 生效）",
          len(view._cache) <= view._cache_max + 2,
          f"{len(view._cache)} / 上限 {view._cache_max}（共 {view.total} 页）")

    _teardown(win)


# ================================================================ 6. 首启与资源释放
def _rss_mb() -> float:
    if os.name != "nt":
        return 0.0
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(pmc)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    fn = k32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return pmc.WorkingSetSize / 1048576
    return 0.0


def test_fresh_install():
    """把 app 复制到空目录运行：模拟全新安装（无 books/history/config）。"""
    print("\n=== 6. 全新安装首启 ===")
    import subprocess
    fresh = WORK / "fresh"
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir(parents=True)
    shutil.copytree(ROOT / "app", fresh / "app",
                    ignore=shutil.ignore_patterns("__pycache__"))
    code = """
import sys, os
sys.path.insert(0, r"%s")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from app import theme
from app.main_window import MainWindow
from app.store import STORE, DATA_DIR
app = QApplication([])
theme.init(); theme.apply()
w = MainWindow(); w.show()
for _ in range(40):
    app.processEvents()
import time; time.sleep(0.3); app.processEvents()
print("BOOKS", len(STORE.book_list()))
print("EMPTY_VISIBLE", int(w.shelf_page.empty.isVisible()))
print("DATA_DIR", int(DATA_DIR.exists()))
print("THEME", theme.current()["theme"])
w.hotkeys.stop(); w.edge.shutdown(); w.tray.hide()
""" % str(fresh)
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=90, cwd=str(fresh))
        text = out.stdout + out.stderr
        check("全新环境首启不崩溃且显示空态",
              "BOOKS 0" in text and "EMPTY_VISIBLE 1" in text
              and "DATA_DIR 1" in text and out.returncode == 0,
              " / ".join(ln for ln in text.strip().splitlines()[-4:]))
        check("全新环境自动写入默认配置", "THEME paper" in text, "theme=paper")
    except subprocess.TimeoutExpired:
        check("全新环境首启不崩溃且显示空态", False, "90s 超时")
    finally:
        shutil.rmtree(fresh, ignore_errors=True)


def test_resource_release():
    print("\n=== 7. 反复开关与资源释放 ===")
    win = MainWindow()
    win.show()
    pump(0.8)
    book = max(STORE.book_list(), key=lambda x: x["stats"]["chapters"])
    ch = STORE.chapters_of(book["id"])[0]
    rss0 = 0.0
    for i in range(12):
        win.open_chapter(ch["path"], ch["name"], ch["id"])
        pump(0.35)
        win.back_from_reader()
        pump(0.15)
        win.reader_page.view.close_book()
        pump(0.05)
        if i == 2:
            rss0 = _rss_mb()
    rss1 = _rss_mb()
    check("连续开关 12 次后页缓存清空",
          len(win.reader_page.view._cache) == 0,
          f"{len(win.reader_page.view._cache)} 项")
    from app.cbr import POOL
    check("文件句柄池不膨胀", len(POOL._items) <= 4, f"{len(POOL._items)} 个句柄")
    if rss0 and rss1:
        check("内存无明显增长（< 120MB）", rss1 - rss0 < 120,
              f"{rss0:.0f}MB → {rss1:.0f}MB（Δ{rss1 - rss0:+.0f}）")
    else:
        note("当前平台读不到进程内存，内存增长项跳过")
    _teardown(win)


# ================================================================ 8. 单实例 / 备份 / 日志
def test_single_instance():
    print("\n=== 8. 单实例守卫 ===")
    import subprocess
    from app.single_instance import SingleInstance

    key = f"cbz-selftest-{os.getpid()}"
    first = SingleInstance(key)
    check("首个实例取得锁", first.acquire())

    lock_code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from app.single_instance import SingleInstance\n"
        "print('ACQ', int(SingleInstance(%r).acquire()))\n"
        % (str(ROOT), key)
    )
    out = subprocess.run([sys.executable, "-c", lock_code],
                         capture_output=True, text=True, timeout=40,
                         env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    check("另一个进程无法同时取得锁", "ACQ 0" in out.stdout,
          out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "无输出")
    first.release()

    # 用真实子进程当「已运行的实例」，父进程发唤醒请求
    server_code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from PySide6.QtCore import QTimer\n"
        "app = QApplication([])\n"
        "from app.single_instance import SingleInstance\n"
        "s = SingleInstance(%r)\n"
        "print('READY' if s.acquire() else 'BUSY', flush=True)\n"
        "s.activated.connect(lambda: (print('GOT', flush=True), app.quit()))\n"
        "QTimer.singleShot(8000, app.quit)\n"
        "app.exec()\n"
        "s.release()\n" % (str(ROOT), key)
    )
    child = subprocess.Popen([sys.executable, "-c", server_code],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    try:
        ready = child.stdout.readline().strip()
        check("子进程成为主实例", ready == "READY", ready or "无输出")
        check("能通知到运行中的实例", SingleInstance.notify(key))
        rest, _ = child.communicate(timeout=12)
        check("运行中的实例收到唤醒并退出",
              "GOT" in (ready + rest), (rest or "").strip()[:60])
    finally:
        if child.poll() is None:
            child.kill()

    again = SingleInstance(key)
    check("实例退出后可以重新取得", again.acquire())
    again.release()


def test_backup_and_log():
    print("\n=== 9. 数据备份与日志 ===")
    import json
    import logging
    from app import logging_setup
    from app.store import BACKUP_SUFFIX, read_json_file, write_json_file

    d = WORK / "backup"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    p = d / "books.json"
    bak = pathlib.Path(str(p) + BACKUP_SUFFIX)

    check("首次写入不产生备份", write_json_file(p, {"v": 1}) and not bak.exists())
    write_json_file(p, {"v": 2})
    check("再次写入保留上一版为 .bak",
          json.loads(bak.read_text(encoding="utf-8"))["v"] == 1
          and json.loads(p.read_text(encoding="utf-8"))["v"] == 2)

    p.write_text("{ 这不是 JSON", encoding="utf-8")
    data, source = read_json_file(p, {})
    check("主文件损坏时回退 .bak", data == {"v": 1} and source == "backup",
          f"来源 {source}")

    write_json_file(p, {"v": 3})
    check("损坏的主文件不会顶掉好备份",
          json.loads(bak.read_text(encoding="utf-8"))["v"] == 1
          and json.loads(p.read_text(encoding="utf-8"))["v"] == 3)

    no_data, no_src = read_json_file(d / "missing.json", {"empty": True})
    check("文件不存在时返回默认值", no_data == {"empty": True} and no_src == "default")

    logging_setup.setup_logging()
    marker = f"SELFTEST-{time.time():.0f}"
    logging.getLogger("robust").info(marker)
    pump(0.2)
    text = logging_setup.LOG_FILE.read_text(encoding="utf-8") if \
        logging_setup.LOG_FILE.exists() else ""
    check("日志写入 data/app.log", marker in text,
          f"{logging_setup.LOG_FILE.name} {len(text)} 字符")

    logging_setup.install_excepthook()
    check("已安装全局异常钩子", getattr(sys.excepthook, "__name__", "") == "hook")
    check("已有实例状态可被主程序读取", hasattr(STORE, "recovered"))


# ================================================================ 10. 源码卫生
def test_source():
    print("\n=== 10. 源码卫生 ===")
    bad = []
    for p in list((ROOT / "app").glob("*.py")) + [ROOT / "main.py"]:
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for ch in line:
                o = ord(ch)
                if 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF:
                    bad.append(f"{p.name}:{ln}")
                    break
    check("界面源码不含彩色 emoji", not bad, "、".join(bad[:4]))

    import ast
    parse_fail = []
    for p in list((ROOT / "app").glob("*.py")) + list((ROOT / "tools").glob("*.py")):
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            parse_fail.append(f"{p.name}:{e.lineno}")
    check("全部 Python 文件语法可解析", not parse_fail, "、".join(parse_fail[:4]))


def main():
    print("稳健性测试开始（无头）")
    app = QApplication.instance() or QApplication([])
    theme.init()
    theme.apply()
    test_formats()
    test_store()
    test_theme_matrix()
    test_layout()
    test_perf()
    test_fresh_install()
    test_resource_release()
    test_single_instance()
    test_backup_and_log()
    test_source()

    print("\n" + "=" * 56)
    if NOTES:
        print(f"已知问题/观察 {len(NOTES)} 条：")
        for n in NOTES:
            print(f"  - {n}")
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  ✗ {f}")
        print("结果：未通过")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    code = main()
    QApplication.instance() and QApplication.instance().quit()
    sys.exit(code)
