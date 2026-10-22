"""CBZ 桌面阅读器 —— 程序入口。"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 无控制台启动时 stdout 可能为 None，避免 print 崩溃；
# stderr 留给 logging_setup 接管（转写到 data/app.log，而不是丢弃）
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QFont                                  # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app.main_window import MainWindow                           # noqa: E402
from app import __version__, theme                               # noqa: E402
from app.logging_setup import (install_excepthook, install_qt_handler,   # noqa: E402
                               log_environment, setup_logging)
from app.single_instance import SingleInstance                   # noqa: E402


def selftest() -> int:
    """打包产物自检：不依赖 GUI，把结果写入 data/selftest_report.txt 并返回退出码。"""
    import json
    import platform
    import traceback

    lines: list[str] = []
    ok = True

    def log(msg: str):
        lines.append(msg)

    log(f"frozen      : {getattr(sys, 'frozen', False)}")
    log(f"executable  : {sys.executable}")
    log(f"python      : {sys.version.split()[0]}")
    log(f"platform    : {platform.platform()}")

    try:
        from app.store import APP_DIR, CACHE_DIR, DATA_DIR, LIB_DIR, STORE
        log(f"app_dir     : {APP_DIR}")
        for d in (DATA_DIR, CACHE_DIR, LIB_DIR):
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        log("dirs        : 可写 OK")
    except Exception as e:
        ok = False
        log(f"dirs        : 失败 {e!r}")
        traceback.print_exc()

    try:
        from PIL import features
        log(f"pillow webp : {features.check('webp')}")
        log(f"pillow jpg  : {features.check('jpg')}")
        if not features.check("webp"):
            ok = False
    except Exception as e:
        ok = False
        log(f"pillow      : 失败 {e!r}")

    try:
        from app.cbr import ComicSource
        books = STORE.book_list()
        chs = []
        for b in books:
            chs += STORE.chapters_of(b["id"])
        log(f"books       : {len(books)} 本 / {len(chs)} 话")
        if chs:
            c = chs[0]
            src = ComicSource(c["path"])
            n = src.page_count
            im = src.image(0)
            cover = src.cover_path()
            title = STORE.chapter_book_title(c["id"])
            log(f"decode      : 《{title}》{c['name']} 共 {n} 页，首图 {im.size} {im.mode}")
            log(f"cover cache : {cover}")
            if n <= 0 or im.size[0] <= 0:
                ok = False
            src.close()
        else:
            log("decode      : 书库为空，跳过（先新建书并导入话数再自检可覆盖此项）")
    except Exception as e:
        ok = False
        log(f"decode      : 失败 {e!r}")
        traceback.print_exc()

    try:
        import zipfile  # noqa: F401
        import PySide6
        from PySide6.QtCore import qVersion
        log(f"pyside6     : {PySide6.__version__} / Qt {qVersion()}")
    except Exception as e:
        ok = False
        log(f"pyside6     : 失败 {e!r}")

    log(f"result      : {'PASS' if ok else 'FAIL'}")
    report = "\n".join(lines)
    try:
        from app.store import DATA_DIR
        (DATA_DIR / "selftest_report.txt").write_text(report, encoding="utf-8")
    except Exception:
        pass
    print(report)
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    setup_logging()
    install_excepthook()
    install_qt_handler()

    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("CBZ 阅读器")
    app.setApplicationDisplayName("CBZ 阅读器")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    theme.init()          # 读取个性化配置（主题 / 强调色 / 圆角 / 字号）
    theme.apply()         # 生成并应用全局 QSS

    log_environment(__version__)
    from app.store import STORE
    for label in STORE.recovered:
        logging.getLogger("app").warning("数据文件已从备份恢复：%s", label)

    # 单实例：第二个进程负责把已有窗口唤到前台，然后退出。
    # 多个进程同时写 books.json 会互相覆盖，默认不允许。
    allow_multi = "--allow-multi" in sys.argv
    single = SingleInstance()
    if not allow_multi:
        if not single.acquire():
            for _ in range(6):
                if SingleInstance.notify():
                    logging.getLogger("app").info("已有实例在运行，已唤起其窗口")
                    return 0
                time.sleep(0.35)
            logging.getLogger("app").warning("检测到已有实例，但未能唤醒")
            # 不弹模态框：无桌面环境（CI / 无头）会永久阻塞
            return 0
        app.aboutToQuit.connect(single.release)
    else:
        logging.getLogger("app").warning(
            "以 --allow-multi 启动：多实例同时写书库可能互相覆盖")

    win = MainWindow()
    win.show()
    if not allow_multi:
        single.activated.connect(lambda: win.show_window())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
