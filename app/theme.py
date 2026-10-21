"""主题系统：多套配色 × 强调色 × 圆角 × 字号，全部可热切换。

设计原则（低刺激纸感）：
- 背景用带一点点暖/冷偏向的「纸色」，不用纯白纯黑；
- 正文与背景对比足够但不刺眼，次要信息用低对比灰；
- 全局只保留一个强调色，且强调色只出现在「当前态」与关键动作上；
- 圆角、字号统一由 token 派生，不散落在各处写死。
"""
from __future__ import annotations

import weakref
from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

DEFAULT_THEME = "paper"
DEFAULT_RADIUS = 10
DEFAULT_SCALE = 1.0

# ---------------------------------------------------------------- 主题定义
# 每套主题只描述「纸色 + 墨色 + 一个强调色」，其余 token 由算法派生。
THEMES: dict[str, dict] = {
    "paper": {
        "name": "素纸", "tag": "暖白护眼 · 默认", "dark": False,
        "bg": "#F4F1EA", "surface": "#FBF9F4", "surface2": "#F0ECE3",
        "border": "#E3DDD0", "border2": "#CFC7B6",
        "text": "#2A2823", "sub": "#78715F",
        "accent": "#3F6B5A", "danger": "#B0453F", "ok": "#4A7C59",
        "overlay": "#1B1E22",
    },
    "linen": {
        "name": "米黄", "tag": "暖纸 · 夜读", "dark": False,
        "bg": "#EFE7D6", "surface": "#FAF4E6", "surface2": "#E8DFCB",
        "border": "#DCCFB6", "border2": "#C9B998",
        "text": "#33302A", "sub": "#7D7361",
        "accent": "#9A6B3A", "danger": "#A8453C", "ok": "#5B7A45",
        "overlay": "#221C14",
    },
    "mist": {
        "name": "雾蓝", "tag": "清透 · 冷调", "dark": False,
        "bg": "#EDF1F5", "surface": "#FAFCFD", "surface2": "#E8EEF4",
        "border": "#DCE3EA", "border2": "#C5D1DB",
        "text": "#202630", "sub": "#6C7783",
        "accent": "#3D6E9E", "danger": "#B24A4A", "ok": "#3F7A62",
        "overlay": "#18202A",
    },
    "sakura": {
        "name": "樱灰", "tag": "柔粉 · 低饱和", "dark": False,
        "bg": "#F7F0F1", "surface": "#FDFBFC", "surface2": "#F2E8EA",
        "border": "#EADDE0", "border2": "#DCC8CD",
        "text": "#2C2326", "sub": "#857175",
        "accent": "#A8506A", "danger": "#B0454C", "ok": "#5B7A63",
        "overlay": "#241A1E",
    },
    "ink": {
        "name": "墨夜", "tag": "深色 · 靛蓝", "dark": True,
        "bg": "#16181B", "surface": "#1D2024", "surface2": "#23272C",
        "border": "#2E333A", "border2": "#3C424A",
        "text": "#E9E7E3", "sub": "#9AA1AB",
        "accent": "#7FA3D9", "danger": "#E0716C", "ok": "#6FBF8F",
        "overlay": "#101215",
    },
    "dusk": {
        "name": "暮褐", "tag": "深色 · 暖棕", "dark": True,
        "bg": "#1A1714", "surface": "#221E19", "surface2": "#292319",
        "border": "#352D24", "border2": "#463A2C",
        "text": "#EDE5D9", "sub": "#A79A88",
        "accent": "#D2915C", "danger": "#D97064", "ok": "#7FAE72",
        "overlay": "#14110F",
    },
}

# 强调色覆盖（留空 = 跟随主题自带强调色）
ACCENTS: dict[str, dict] = {
    "": {"name": "跟随主题", "hex": ""},
    "pine": {"name": "松绿", "hex": "#3F6B5A"},
    "indigo": {"name": "靛蓝", "hex": "#4A63C8"},
    "clay": {"name": "赭石", "hex": "#B06A3B"},
    "wine": {"name": "绛红", "hex": "#A44A5E"},
    "violet": {"name": "紫棠", "hex": "#7A5BA8"},
    "slate": {"name": "青灰", "hex": "#4E6B72"},
}

RADII = {6: "紧凑", 10: "标准", 14: "圆润"}
SCALES = {0.92: "小", 1.0: "标准", 1.08: "大", 1.16: "特大"}


# ---------------------------------------------------------------- 颜色工具
def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(c))) for c in rgb)


def mix(a: str, b: str, t: float) -> str:
    """a 与 b 按 t（0=a，1=b）混合。"""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {int(max(0.0, min(1.0, alpha)) * 255)})"


def luminance(hex_color: str) -> float:
    r, g, b = (c / 255 for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------- 运行时状态
class _Bus(QObject):
    changed = Signal()


bus = _Bus()
_STATE = {"theme": DEFAULT_THEME, "accent": "", "radius": DEFAULT_RADIUS, "scale": DEFAULT_SCALE}
TOK: dict[str, str] = {}
_REG: list[tuple[weakref.ref, str]] = []      # 内联样式登记表（主题切换时重刷）


def _cfg(key: str, default):
    try:
        from .store import STORE
        return STORE.cfg(f"theme.{key}", default)
    except Exception:
        return default


def init() -> None:
    """从配置读入个性化设置并解析 token（在创建 QApplication 后调用）。"""
    _STATE["theme"] = str(_cfg("name", DEFAULT_THEME) or DEFAULT_THEME)
    if _STATE["theme"] not in THEMES:
        _STATE["theme"] = DEFAULT_THEME
    acc = str(_cfg("accent", "") or "")
    _STATE["accent"] = acc if acc in ACCENTS else ""
    try:
        _STATE["radius"] = int(_cfg("radius", DEFAULT_RADIUS) or DEFAULT_RADIUS)
    except Exception:
        _STATE["radius"] = DEFAULT_RADIUS
    if _STATE["radius"] not in (6, 10, 14):
        _STATE["radius"] = DEFAULT_RADIUS
    try:
        _STATE["scale"] = float(_cfg("scale", DEFAULT_SCALE) or DEFAULT_SCALE)
    except Exception:
        _STATE["scale"] = DEFAULT_SCALE
    if not 0.85 <= _STATE["scale"] <= 1.3:
        _STATE["scale"] = DEFAULT_SCALE
    _resolve()


def _resolve() -> None:
    t = dict(THEMES.get(_STATE["theme"], THEMES[DEFAULT_THEME]))
    dark = bool(t["dark"])
    acc = t["accent"]
    if _STATE["accent"]:
        acc = ACCENTS[_STATE["accent"]]["hex"]
    surface = t["surface"]

    tok = {k: t[k] for k in ("bg", "surface", "surface2", "border", "text", "sub",
                             "danger", "ok", "overlay")}
    tok["dark"] = "1" if dark else "0"
    tok["border2"] = t.get("border2", mix(t["border"], t["text"], 0.18))
    tok["surface3"] = mix(surface, t["text"], 0.04 if not dark else 0.06)
    tok["accent"] = acc
    tok["accent_h"] = mix(acc, "#FFFFFF" if dark else "#000000", 0.14 if dark else 0.16)
    tok["accent_soft"] = mix(acc, surface, 0.86 if not dark else 0.78)
    tok["accent_line"] = mix(acc, surface, 0.55)
    tok["accent_text"] = "#FFFFFF" if luminance(acc) < 0.62 else "#1B1E23"
    tok["danger_soft"] = mix(t["danger"], surface, 0.88)
    tok["ok_soft"] = mix(t["ok"], surface, 0.88)
    tok["overlay2"] = mix(t["overlay"], "#FFFFFF", 0.07)
    tok["overlay_text"] = "#F1EDE6"
    tok["overlay_sub"] = "#B9B3A8"
    tok["overlay_line"] = mix(t["overlay"], "#FFFFFF", 0.16)
    tok["overlay_glass"] = rgba(t["overlay"], 0.78)

    r = _STATE["radius"]
    tok["r1"] = f"{max(4, r - 5)}px"
    tok["r2"] = f"{max(6, r - 2)}px"
    tok["r3"] = f"{r + 2}px"
    tok["r4"] = f"{r + 8}px"

    s = _STATE["scale"]
    for n in range(9, 23):
        tok[f"f{n}"] = f"{max(9, round(n * s))}px"
    TOK.clear()
    TOK.update(tok)


# 对外读取
def c(key: str) -> str:
    return TOK.get(key, "#000000")


def px(n: int) -> str:
    return TOK.get(f"f{n}", f"{n}px")


def radius_px() -> int:
    return _STATE["radius"] + 2


def now(widget, tmpl: str) -> None:
    """立即应用内联样式（不登记）。用于每次刷新都会重建的控件。"""
    widget.setStyleSheet(Template(tmpl).safe_substitute(TOK))


def current() -> dict:
    return dict(_STATE)


def meta(tid: str | None = None) -> dict:
    return THEMES.get(tid or _STATE["theme"], THEMES[DEFAULT_THEME])


def is_dark() -> bool:
    return bool(meta().get("dark"))


# ---------------------------------------------------------------- 内联样式
def style(widget, tmpl: str) -> None:
    """按当前 token 应用内联样式，并登记；主题切换时自动重刷。"""
    try:
        _REG.append((weakref.ref(widget), tmpl))
    except TypeError:
        pass
    widget.setStyleSheet(Template(tmpl).safe_substitute(TOK))


def _restyle() -> None:
    alive = []
    for ref, tmpl in _REG:
        w = ref()
        if w is None:
            continue
        try:
            w.setStyleSheet(Template(tmpl).safe_substitute(TOK))
            alive.append((ref, tmpl))
        except RuntimeError:
            pass
    _REG[:] = alive


# ---------------------------------------------------------------- 切换
def _persist() -> None:
    try:
        from .store import STORE
        STORE.set_cfg("theme.name", _STATE["theme"])
        STORE.set_cfg("theme.accent", _STATE["accent"])
        STORE.set_cfg("theme.radius", _STATE["radius"])
        STORE.set_cfg("theme.scale", _STATE["scale"])
        STORE.save_config()
    except Exception:
        pass


def set_theme(tid: str) -> None:
    if tid in THEMES:
        _STATE["theme"] = tid
        apply(persist=True)


def set_accent(aid: str) -> None:
    if aid in ACCENTS:
        _STATE["accent"] = aid
        apply(persist=True)


def set_radius(r: int) -> None:
    if r in RADII:
        _STATE["radius"] = r
        apply(persist=True)


def set_scale(s: float) -> None:
    if any(abs(s - k) < 1e-6 for k in SCALES):
        _STATE["scale"] = s
        apply(persist=True)


def reset() -> None:
    _STATE.update({"theme": DEFAULT_THEME, "accent": "", "radius": DEFAULT_RADIUS,
                   "scale": DEFAULT_SCALE})
    apply(persist=True)


def apply(persist: bool = False) -> None:
    """重新解析 token → 全局 QSS → 内联样式 → 通知自绘控件。"""
    _resolve()
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(build_qss())
    _restyle()
    if persist:
        _persist()
    bus.changed.emit()


# ---------------------------------------------------------------- QSS
def build_qss() -> str:
    t = Template("""
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; }

#Root { background: $bg; border: 1px solid $border; border-radius: $r3; }
#Content { background: transparent; }
#TitleBar { background: transparent; }
#AppTitle { color: $text; font-size: $f13; font-weight: 600; }
#AppSub { color: $sub; font-size: $f11; }
#TitleBtn {
    background: transparent; border: none; border-radius: $r1;
    color: $sub; font-size: $f13; padding: 0px;
}
#TitleBtn:hover { background: $surface2; color: $text; }
#TitleBtn:pressed { background: $border; }
#CloseBtn { font-size: $f14; }
#CloseBtn:hover { background: $danger; color: #FFFFFF; }

#NavRail { background: $surface; border-right: 1px solid $border;
           border-top-left-radius: 0px; border-bottom-left-radius: $r3; }
#NavBtn {
    background: transparent; border: none; border-left: 3px solid transparent;
    border-radius: $r2; color: $sub; font-size: $f10; padding: 6px 2px;
}
#NavBtn:hover { background: $surface2; color: $text; }
#NavBtn:checked { background: $accent_soft; border-left: 3px solid $accent;
                  color: $accent; font-weight: 600; }
#RailFoot { color: $sub; font-size: $f9; }

#Page { background: $bg; }
#SectionTitle { color: $text; font-size: $f15; font-weight: 700; }
#CardTitle { color: $text; font-size: $f12; font-weight: 700; }
#GroupTitle { color: $text; font-size: $f13; font-weight: 700; }
#FormLabel { color: $text; font-size: $f12; }
#BookTitle { color: $text; font-size: $f19; font-weight: 700; }
#ReaderTitle { color: $overlay_text; font-size: $f12; font-weight: 600; }
#PageSub { color: $sub; font-size: $f11; }
#Muted { color: $sub; font-size: $f11; }
#EmptyState { color: $sub; font-size: $f13; }
#Divider { background: $border; }

QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }

#SearchBox {
    background: $surface; border: 1px solid $border; border-radius: $r2;
    padding: 6px 10px; color: $text; font-size: $f12;
}
#SearchBox:focus { border: 1px solid $accent; background: $surface; }

QPushButton#Primary {
    background: $accent; color: $accent_text; border: none; border-radius: $r2;
    padding: 7px 16px; font-size: $f12; font-weight: 600;
}
QPushButton#Primary:hover { background: $accent_h; }
QPushButton#Primary:disabled { background: $border; color: $sub; }

QPushButton#Ghost {
    background: $surface; color: $text; border: 1px solid $border;
    border-radius: $r2; padding: 7px 13px; font-size: $f12;
}
QPushButton#Ghost:hover { background: $surface2; border-color: $border2; }
QPushButton#Ghost:pressed { background: $surface3; }

QPushButton#Danger {
    background: transparent; color: $danger; border: 1px solid $danger;
    border-radius: $r2; padding: 7px 13px; font-size: $f12;
}
QPushButton#Danger:hover { background: $danger_soft; }

#Card { background: $surface; border: 1px solid $border; border-radius: $r3; }
#CardFlat { background: $surface2; border: 1px solid $border; border-radius: $r2; }
#StatNum { color: $text; font-size: $f20; font-weight: 700; }
#StatLbl { color: $sub; font-size: $f11; }

#BookTile { background: transparent; border: none; }
#TileMeta { color: $text; font-size: $f11; font-weight: 600; }
#CoverBox { background: $surface2; border: 1px solid $border; border-radius: $r2;
            color: $sub; font-size: $f11; }

#RecentCard { background: $surface2; border: 1px solid transparent; border-radius: $r2; }
#RecentCard:hover { border-color: $accent; background: $accent_soft; }
#RecentName { color: $text; font-size: $f12; font-weight: 600; }
#RecentSub { color: $sub; font-size: $f10; }

QListWidget { background: $surface; border: 1px solid $border; border-radius: $r3; outline: none; }
QListWidget::item { padding: 9px 12px; border: none; color: $text; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QListWidget::item:hover { background: $surface2; }

QComboBox, QLineEdit, QSpinBox {
    background: $surface; border: 1px solid $border; border-radius: $r2;
    padding: 5px 8px; color: $text; font-size: $f12; min-height: 18px;
    selection-background-color: $accent; selection-color: $accent_text;
}
QComboBox:focus, QLineEdit:focus { border-color: $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border; selection-background-color: $accent_soft;
    selection-color: $text; color: $text; outline: none;
}

QCheckBox { color: $text; font-size: $f12; spacing: 8px; }
QCheckBox::indicator { width: 0px; height: 0px; border: none; background: transparent; }

QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0;
    background: $surface; border: 2px solid $accent; border-radius: 6px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border2; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $sub; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border2; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: $sub; }

QMenuBar { background: transparent; }
QDialog { background: $bg; }
QMenu { background: $surface; border: 1px solid $border; border-radius: $r2;
        padding: 5px; color: $text; }
QMenu::item { padding: 6px 18px; border-radius: $r1; font-size: $f12; }
QMenu::item:selected { background: $accent_soft; color: $text; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }

QToolTip { background: $overlay; color: $overlay_text; border: 1px solid $overlay_line;
           padding: 5px 8px; border-radius: $r1; font-size: $f11; }

#Toast { background: $overlay; color: $overlay_text; border-radius: $r2;
         padding: 9px 16px; font-size: $f12; }

#ReaderBar { background: $overlay; border: 1px solid $overlay_line; border-radius: $r3; }
#ReaderBar QPushButton {
    background: transparent; border: none; color: $overlay_text; font-size: $f12;
    min-height: 20px; padding: 4px 9px; border-radius: $r1;
}
#ReaderBar QPushButton:hover { background: $overlay2; }
#ReaderBar QPushButton:checked { background: $accent; color: $accent_text; }
#ReaderBar QLabel { color: $overlay_sub; font-size: $f12; }
#ReaderBar #BarLabel { color: $overlay_sub; font-size: $f11; }
#BarSep { background: $overlay_line; }
#ReaderBar QSlider::groove:horizontal { background: $overlay2; }
#ReaderBar QSlider::sub-page:horizontal { background: $accent; }
#ReaderBar QSlider::handle:horizontal { background: $overlay_text; border: 2px solid $accent; }
#PageBadge { background: $overlay; color: $overlay_text; border-radius: $r2;
             padding: 4px 10px; font-size: $f12; }

#BarGrip { background: $overlay_glass; color: $overlay_text;
           border: 1px solid $overlay_line; border-radius: 13px;
           font-size: $f11; padding: 0 10px; }
#BarGrip:hover { background: $overlay; }

#SegBox { background: $surface2; border: 1px solid $border; border-radius: $r2; }
#SegBtn { background: transparent; border: none; color: $sub; font-size: $f12;
          padding: 6px 14px; border-radius: $r1; }
#SegBtn:hover { color: $text; }
#SegBtn:checked { background: $surface; color: $text; font-weight: 600; }

#Chip { background: $accent_soft; color: $accent; border-radius: 9px;
        padding: 2px 9px; font-size: $f10; }
#HintCard { background: $surface2; border: 1px dashed $border2; border-radius: $r2; }
""")
    return t.safe_substitute(TOK)
