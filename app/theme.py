"""主题色 + QSS。"""

# 浅色壳层
BG = "#F4F5F7"
SURFACE = "#FFFFFF"
SURFACE_2 = "#FAFBFC"
BORDER = "#E3E6EA"
TEXT = "#1B1E23"
SUB = "#71787F"
ACCENT = "#3B6FE0"
ACCENT_HOVER = "#2F5FCB"
ACCENT_SOFT = "#E8EFFC"
DANGER = "#E5484D"
OK = "#2E9E5B"

QSS = f"""
* {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif; }}

#Root {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 10px; }}
#TitleBar {{ background: transparent; }}
#AppTitle {{ color: {TEXT}; font-size: 13px; font-weight: 600; }}
#AppSub {{ color: {SUB}; font-size: 11px; }}
#TitleBtn {{
    background: transparent; border: none; border-radius: 6px;
    color: {SUB}; font-size: 14px; padding: 0px;
}}
#TitleBtn:hover {{ background: #E9EBEF; color: {TEXT}; }}
#TitleBtn:pressed {{ background: #DFE3E8; }}
#CloseBtn {{ font-size: 15px; }}
#CloseBtn:hover {{ background: {DANGER}; color: white; }}

#NavRail {{ background: {SURFACE}; border-right: 1px solid {BORDER};
            border-top-left-radius: 0px; border-bottom-left-radius: 10px; }}
#NavBtn {{
    background: transparent; border: none; border-radius: 8px;
    color: {SUB}; font-size: 11px; padding: 8px 2px;
}}
#NavBtn:hover {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
#NavBtn:checked {{ background: {ACCENT}; color: white; }}

#Page {{ background: {BG}; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

#SearchBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; color: {TEXT}; font-size: 12px;
}}
#SearchBox:focus {{ border: 1px solid {ACCENT}; }}

QPushButton#Primary {{
    background: {ACCENT}; color: white; border: none; border-radius: 8px;
    padding: 7px 14px; font-size: 12px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Ghost {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 12px; font-size: 12px;
}}
QPushButton#Ghost:hover {{ background: {SURFACE_2}; border-color: #CFD5DC; }}
QPushButton#Danger {{
    background: transparent; color: {DANGER}; border: 1px solid #F2C4C6;
    border-radius: 8px; padding: 7px 12px; font-size: 12px;
}}
QPushButton#Danger:hover {{ background: #FDF0F0; }}

#SectionTitle {{ color: {TEXT}; font-size: 14px; font-weight: 700; }}
#Muted {{ color: {SUB}; font-size: 11px; }}
#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#StatNum {{ color: {TEXT}; font-size: 20px; font-weight: 700; }}
#StatLbl {{ color: {SUB}; font-size: 11px; }}

#BookTile {{ background: transparent; border: none; }}
#TileMeta {{ color: {TEXT}; font-size: 11px; }}

#RecentCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#RecentCard:hover {{ border-color: {ACCENT}; background: {ACCENT_SOFT}; }}
#RecentName {{ color: {TEXT}; font-size: 12px; font-weight: 600; }}
#RecentSub {{ color: {SUB}; font-size: 10px; }}

QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; outline: none; }}
QListWidget::item {{ padding: 10px 12px; border-bottom: 1px solid #F0F2F4; color: {TEXT}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QListWidget::item:hover {{ background: #F7F9FC; }}

QComboBox, QLineEdit, QSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 8px; color: {TEXT}; font-size: 12px; min-height: 18px;
}}
QComboBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT}; color: {TEXT}; outline: none;
}}

QCheckBox {{ color: {TEXT}; font-size: 12px; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #C6CCD3; background: white; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};
    image: none; }}

QSlider::groove:horizontal {{ height: 4px; background: #DDE1E6; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0;
    background: white; border: 2px solid {ACCENT}; border-radius: 6px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C9CFD6; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #AEB6BF; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C9CFD6; border-radius: 4px; min-width: 30px; }}

QMenuBar {{ background: transparent; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px; color: {TEXT}; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; font-size: 12px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolTip {{ background: #22262C; color: #F2F4F7; border: none; padding: 5px 8px;
            border-radius: 6px; font-size: 11px; }}

#Toast {{ background: rgba(30,34,40,235); color: white; border-radius: 8px;
          padding: 9px 16px; font-size: 12px; }}
#ReaderBar {{ background: rgba(24,27,33,242); border-radius: 10px; }}
#ReaderBar QPushButton {{
    background: transparent; border: none; color: #E6E9EE; font-size: 12px;
    padding: 5px 9px; border-radius: 5px;
}}
#ReaderBar QPushButton:hover {{ background: rgba(255,255,255,0.14); }}
#ReaderBar QPushButton:checked {{ background: {ACCENT}; color: white; }}
#ReaderBar QLabel {{ color: #C9CFD8; font-size: 12px; }}
#ReaderBar QSlider::groove:horizontal {{ background: #3A4048; }}
#ReaderBar QSlider::sub-page:horizontal {{ background: {ACCENT}; }}
#ReaderBar QSlider::handle:horizontal {{ background: white; border: 2px solid {ACCENT}; }}
#PageBadge {{ background: rgba(20,22,27,200); color: #E6E9EE; border-radius: 7px;
              padding: 4px 10px; font-size: 12px; }}
"""
