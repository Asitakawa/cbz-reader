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
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app.main_window import MainWindow                           # noqa: E402
from app import theme                                            # noqa: E402

MUTEX_NAME = "Global\\CbzReader_SingleInstance_9F3A"
ERROR_ALREADY_EXISTS = 183

# 读取 Win32 错误码必须用 use_last_error=True + ctypes.get_last_error()：
# 直接用 ctypes.windll.kernel32.GetLastError() 会被中间调用污染，
# 曾导致「首次启动也判定为已在运行」而直接退出。
_K32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
_MUTEX_HANDLE = None


def already_running() -> bool:
    """已有实例在运行则返回 True（句柄保留到进程结束，用于占位）。"""
    global _MUTEX_HANDLE
    if _K32 is None:
        return False
    try:
        _K32.CreateMutexW.restype = ctypes.c_void_p
        _K32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        _MUTEX_HANDLE = _K32.CreateMutexW(None, False, MUTEX_NAME)
        return ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    except Exception:
        return False


def warn_already_running() -> bool:
    """不依赖 Qt 的确认框（此时 QApplication 还没创建）。

    返回 True 表示用户选择「仍然启动」，继续开新窗口。
    """
    try:
        MB_YESNO, MB_ICONQUESTION, IDYES = 0x04, 0x20, 6
        rc = ctypes.windll.user32.MessageBoxW(
            None,
            "CBZ 阅读器似乎已经在运行中。\n\n"
            "点「是」：仍然再开一个窗口（可能导致全局热键冲突）\n"
            "点「否」：退出，改为使用已在运行的那个（右下角托盘可找到）",
            "CBZ 阅读器", MB_YESNO | MB_ICONQUESTION)
        return rc == IDYES
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

    # 单实例守卫放在 QApplication 之前，避免 Qt 的 Win32 调用干扰错误码。
    # 即使误判也不会硬拦：用户可以选择仍然启动。
    if already_running() and not warn_already_running():
        return 0

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

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
