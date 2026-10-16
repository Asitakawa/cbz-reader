"""Win32 全局热键（RegisterHotKey + 独立消息循环线程）+ 托盘支持。"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001

_SPECIAL_VK = {
    "`": 0xC0, "~": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
    "space": 0x20, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "enter": 0x0D,
    "backspace": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24,
    "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
        ("time", wintypes.DWORD), ("pt_x", wintypes.LONG), ("pt_y", wintypes.LONG),
    ]


def parse_hotkey(spec: str):
    """'ctrl+shift+x' -> (mods, vk)；非法返回 None。"""
    if not spec:
        return None
    mods, vk = 0, None
    for raw in str(spec).lower().replace(" ", "").split("+"):
        if raw in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif raw == "alt":
            mods |= MOD_ALT
        elif raw == "shift":
            mods |= MOD_SHIFT
        elif raw in ("win", "super", "meta"):
            mods |= MOD_WIN
        elif not raw:
            continue
        else:
            if raw in _SPECIAL_VK:
                vk = _SPECIAL_VK[raw]
            elif len(raw) == 1 and raw.isalnum():
                vk = ord(raw.upper())
            else:
                return None
    if vk is None:
        return None
    return mods | MOD_NOREPEAT, vk


class HotkeyManager(QObject):
    """全局热键 → Qt 信号（跨线程自动排队，安全）。"""

    hide_toggle = Signal()
    camo_toggle = Signal()
    triggered = Signal(str)   # action 名

    ACTION_HIDE = "hide"
    ACTION_CAMO = "camo"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bindings: dict[str, str] = {}      # action -> spec
        self._failed: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._stop = False
        self._pending: list[tuple[str, int, int]] | None = None
        self._id_to_action: dict[int, str] = {}
        self._lock = threading.Lock()

    # ---------- 生命周期 ----------
    def start(self, bindings: dict[str, str]) -> None:
        self._bindings = dict(bindings)
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="hotkey-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=0.6)
        self._thread = None

    def rebind(self, bindings: dict[str, str]) -> dict[str, str]:
        """热更新绑定，返回失败的 action->spec。"""
        with self._lock:
            self._bindings = dict(bindings)
            self._failed = {}
            self._pending = None  # 触发线程内重注册
        time.sleep(0.15)
        return dict(self._failed)

    @property
    def failed(self) -> dict[str, str]:
        return dict(self._failed)

    # ---------- 热键线程 ----------
    def _unregister_all(self) -> None:
        for hid in list(self._id_to_action.keys()):
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._id_to_action.clear()

    def _apply(self, bindings: dict[str, str]) -> None:
        self._unregister_all()
        self._failed = {}
        hid = 1
        for action, spec in bindings.items():
            parsed = parse_hotkey(spec)
            if not parsed:
                if spec:
                    self._failed[action] = spec
                continue
            mods, vk = parsed
            ok = user32.RegisterHotKey(None, hid, mods, vk)
            if ok:
                self._id_to_action[hid] = action
                hid += 1
            else:
                self._failed[action] = spec

    def _run(self) -> None:
        self._apply(self._bindings)
        msg = MSG()
        while not self._stop:
            with self._lock:
                if self._pending is not None:
                    self._apply(self._pending)
                    self._bindings = dict(self._pending)
                    self._pending = None
            handled = False
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                handled = True
                if msg.message == WM_HOTKEY:
                    action = self._id_to_action.get(int(msg.wParam))
                    if action:
                        if action == self.ACTION_HIDE:
                            self.hide_toggle.emit()
                        elif action == self.ACTION_CAMO:
                            self.camo_toggle.emit()
                        self.triggered.emit(action)
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            if not handled:
                time.sleep(0.03)
        self._unregister_all()


def flash_window(hwnd: int) -> None:
    """任务栏闪烁提示（可选）。"""
    try:
        user32.FlashWindow(wintypes.HWND(hwnd), True)
    except Exception:
        pass
