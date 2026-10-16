"""CBZ 桌面阅读器 —— 程序入口。"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 无控制台启动时 stdout 可能为 None，避免 print 崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QFont                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox          # noqa: E402

from app.main_window import MainWindow                           # noqa: E402
from app.theme import QSS                                        # noqa: E402

MUTEX_NAME = "Global\\CbzReader_SingleInstance_9F3A"


def already_running() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, MUTEX_NAME)
        return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


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
        from app.cbr import Cbz
        entries = STORE.shelf_entries()
        log(f"shelf books : {len(entries)}")
        if entries:
            cb = Cbz(entries[0]["path"])
            n = cb.page_count
            im = cb.image(0)
            cover = cb.cover_path()
            log(f"decode      : {entries[0]['name']} 共 {n} 页，首图 {im.size} {im.mode}")
            log(f"cover cache : {cover}")
            if n <= 0 or im.size[0] <= 0:
                ok = False
            cb.close()
        else:
            log("decode      : 书架为空，跳过（先导入漫画再自检可覆盖此项）")
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
    app.setStyleSheet(QSS)

    if already_running():
        QMessageBox.information(None, "CBZ 阅读器", "程序已在运行中（可在托盘中找到）。")
        return 0

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
