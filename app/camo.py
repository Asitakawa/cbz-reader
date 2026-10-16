"""桌面伪装层：一键把窗口变成 Excel / Word / CMD 的外观（全窗口覆盖绘制）。"""
from __future__ import annotations

import random
import time

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

EXCEL_GREEN = QColor("#217346")
EXCEL_GREEN_D = QColor("#17532F")
WORD_BLUE = QColor("#2B579A")
CMD_BG = QColor("#0C0C0C")

MENUS = ["文件", "开始", "插入", "绘图", "页面布局", "公式", "数据", "审阅", "视图", "帮助"]
RIBBON_GROUPS = [
    ("剪贴板", ["粘贴", "剪切", "复制", "格式刷"]),
    ("字体", ["等线", "11", "B", "I", "U", "边框"]),
    ("对齐方式", ["左", "中", "右", "自动换行", "合并"]),
    ("数字", ["常规", "¥", "%", "0.00"]),
    ("样式", ["条件格式", "套用表格"]),
    ("单元格", ["插入", "删除", "格式"]),
]

HEADERS = ["名称", "负责人", "数量", "单价(元)", "金额(元)", "状态", "备注"]
WORDS = ["A", "B", "C", "D", "E", "F"]
NAMES = ["显示器支架", "机械键盘", "无线鼠标", "办公座椅", "打印纸", "路由器", "移动硬盘",
         "笔记本电源", "HDMI 线", "散热硅脂", "U 盘 64G", "网线 5m"]
PEOPLE = ["张伟", "李娜", "王芳", "刘洋", "陈静", "赵磊", "周敏"]
STATUS = ["已完成", "待审核", "进行中", "已驳回"]

CMD_LINES = [
    "$ npm run build",
    "> project@2.4.1 build",
    "> webpack --mode production",
    "",
    "assets by status 1.24 MiB [cached] 12 assets",
    "  asset main.7f3c1a.js 612 KiB [emitted] [immutable] [minimized] (name: main)",
    "  asset vendor.91ab04.js 498 KiB [emitted] [immutable] [minimized] (name: vendor)",
    "  asset index.html 1.6 KiB [emitted]",
    "orphan modules 214 KiB [orphan] 61 modules",
    "runtime modules 3.1 KiB 12 modules",
    "cacheable modules 1.9 MiB",
    "  modules by path ./src/ 512 KiB 78 modules",
    "  modules by path ./node_modules/ 1.38 MiB 214 modules",
    "webpack 5.89.0 compiled successfully in 8.42 s",
    "",
    "$ npm test",
    " PASS  src/utils/format.test.ts",
    " PASS  src/api/client.test.ts",
    " PASS  src/store/index.test.ts",
    "",
    "Test Suites: 3 passed, 3 total",
    "Tests:       27 passed, 27 total",
    "Snapshots:   0 total",
    "Time:        3.284 s",
    "",
    "$ git status",
    "On branch main",
    "Your branch is up to date with 'origin/main'.",
    "nothing to commit, working tree clean",
    "$ ",
]


class CamoOverlay(QWidget):
    """全窗口伪装层；再次按热键 / 右下角三连击解锁。"""

    unlock_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.skin = "excel"
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._clicks = 0
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(lambda: setattr(self, "_clicks", 0))
        self._blink = True
        self._caret = QTimer(self)
        self._caret.setInterval(520)
        self._caret.timeout.connect(self._toggle_caret)
        self._seed = random.Random(20261016)

    def apply_skin(self, skin: str):
        self.skin = skin
        self.update()

    def _toggle_caret(self):
        self._blink = not self._blink
        self.update()

    def showEvent(self, e):
        self._caret.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._caret.stop()
        super().hideEvent(e)

    # ---------- 交互 ----------
    def mousePressEvent(self, e):
        # 右下角 30x30 区域连点 3 次解锁
        if e.button() == Qt.LeftButton and e.position().x() > self.width() - 30 \
                and e.position().y() > self.height() - 30:
            self._clicks += 1
            if self._clicks >= 3:
                self._clicks = 0
                self.unlock_requested.emit()
                return
            self._click_timer.start(700)
        e.accept()

    def mouseMoveEvent(self, e):
        e.accept()

    # ---------- 绘制 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.skin == "word":
            self._paint_word(p)
        elif self.skin == "term":
            self._paint_term(p)
        else:
            self._paint_excel(p)
        p.end()

    # ---- 通用：假窗口控制按钮（从右到左：关闭 / 最大化 / 最小化）----
    def _paint_win_buttons(self, p: QPainter, y: int, color: QColor, bg: QColor | None):
        w = self.width()
        p.setPen(QPen(color, 1.2))
        for i, kind in enumerate(("close", "max", "min")):
            cx = w - 24 - i * 46
            cy = y + 11
            if kind == "min":
                p.drawLine(cx - 6, cy + 5, cx + 6, cy + 5)
            elif kind == "max":
                p.drawRect(cx - 6, cy - 5, 12, 12)
            else:
                if bg is not None:
                    p.fillRect(QRect(cx - 22, y, 46, 24), QColor("#C42B1C"))
                    p.setPen(QPen(QColor("#FFFFFF"), 1.3))
                p.drawLine(cx - 6, cy - 5, cx + 6, cy + 6)
                p.drawLine(cx - 6, cy + 6, cx + 6, cy - 5)
                if bg is not None:
                    p.setPen(QPen(color, 1.2))

    # ---- Excel ----
    def _paint_excel(self, p: QPainter):
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#F3F3F3"))
        # 标题栏
        p.fillRect(QRect(0, 0, w, 32), EXCEL_GREEN)
        p.setPen(QPen(QColor("#FFFFFF")))
        f = QFont("Microsoft YaHei UI", 9)
        p.setFont(f)
        p.drawText(QRect(12, 0, 300, 32), Qt.AlignVCenter | Qt.AlignLeft,
                   "工作簿1.xlsx - Excel")
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.1))
        self._paint_win_buttons(p, 4, QColor("#FFFFFF"), EXCEL_GREEN)
        # 菜单
        y = 32
        p.fillRect(QRect(0, y, w, 26), EXCEL_GREEN_D)
        p.setPen(QPen(QColor("#EAF3EE")))
        x = 14
        for i, m in enumerate(MENUS):
            tw = p.fontMetrics().horizontalAdvance(m)
            if i == 1:
                p.fillRect(QRect(x - 8, y + 3, tw + 16, 20), QColor(255, 255, 255, 38))
            p.drawText(x, y + 18, m)
            x += tw + 22
        y += 26
        # 功能区
        rh = 78
        p.fillRect(QRect(0, y, w, rh), QColor("#F7F9F8"))
        p.setPen(QPen(QColor("#D8DEDB")))
        p.drawLine(0, y + rh, w, y + rh)
        gx = 16
        p.setPen(QPen(QColor("#3B4440")))
        for name, btns in RIBBON_GROUPS:
            bx = gx
            for j, b in enumerate(btns):
                col, row = j % 3, j // 3
                bw, bh = 62, 20
                rect = QRect(bx, y + 8 + row * 23, bw, bh)
                if j == 1 and name == "字体":
                    p.fillRect(rect, QColor("#FFFFFF"))
                    p.setPen(QPen(QColor("#B9C2BD")))
                    p.drawRect(rect)
                    p.setPen(QPen(QColor("#3B4440")))
                p.drawText(rect, Qt.AlignCenter, b)
                bx += bw + 6
            gw = max(150, bx - gx)
            p.setPen(QPen(QColor("#C6CFCA")))
            p.drawLine(gx + gw + 4, y + 6, gx + gw + 4, y + rh - 18)
            p.setPen(QPen(QColor("#6C7671")))
            p.drawText(QRect(gx, y + rh - 16, gw, 14), Qt.AlignCenter, name)
            p.setPen(QPen(QColor("#3B4440")))
            gx += gw + 16
            if gx > w - 120:
                break
        y += rh
        # 公式栏
        p.fillRect(QRect(0, y, w, 24), QColor("#FFFFFF"))
        p.setPen(QPen(QColor("#D8DEDB")))
        p.drawLine(0, y + 24, w, y + 24)
        p.drawLine(62, y, 62, y + 24)
        p.setPen(QPen(QColor("#3B4440")))
        p.drawText(QRect(0, y, 62, 24), Qt.AlignCenter, "A1")
        p.drawText(QRect(74, y, w - 90, 24), Qt.AlignVCenter | Qt.AlignLeft, "fx   =SUM(D2:D13)")
        y += 24
        # 表格（列宽自适应铺满可用宽度）
        rh2 = 20
        col0 = 46
        ncols = max(6, int((w - col0) // 92) + 1)
        cw = max(56, int((w - col0) / ncols))
        xs = [col0 + i * cw for i in range(ncols + 1)]
        xs[-1] = w
        p.fillRect(QRect(0, y, w, h - y), QColor("#FFFFFF"))
        # 列头
        p.fillRect(QRect(0, y, w, rh2), QColor("#E8EEEA"))
        p.setPen(QPen(QColor("#CDD5D1")))
        p.drawLine(0, y + rh2, w, y + rh2)
        p.setPen(QPen(QColor("#3B4440")))
        p.drawText(QRect(0, y, col0, rh2), Qt.AlignCenter, "◤")
        for i in range(ncols):
            p.drawText(QRect(xs[i], y, cw, rh2), Qt.AlignCenter,
                       HEADERS[i] if i < len(HEADERS) else "")
        yy = y + rh2
        rows = max(1, (h - yy - 26) // rh2)
        for r in range(rows):
            row_y = yy + r * rh2
            if r % 2 == 0:
                p.fillRect(QRect(0, row_y, w, rh2), QColor("#FBFCFB"))
            p.setPen(QPen(QColor("#EFF2F0")))
            p.drawLine(0, row_y + rh2, w, row_y + rh2)
            p.setPen(QPen(QColor("#7A837E")))
            p.drawText(QRect(0, row_y, col0, rh2), Qt.AlignCenter, str(r + 1))
            if r == 0:
                p.fillRect(QRect(col0, row_y, w - col0, rh2), QColor("#E4F0E8"))
            p.setPen(QPen(QColor("#2C342F")))
            qty = self._seed.randint(3, 260)
            price = round(self._seed.uniform(12, 899), 2)
            vals = [
                NAMES[r % len(NAMES)],
                PEOPLE[r % len(PEOPLE)],
                str(qty),
                f"{price:,.2f}",
                f"{qty * price:,.2f}",
                STATUS[r % len(STATUS)],
                "Q3 采购",
            ]
            for c, v in enumerate(vals[:ncols]):
                align = Qt.AlignCenter if c in (2, 3, 4) else Qt.AlignVCenter | Qt.AlignLeft
                p.drawText(QRect(xs[c] + 8, row_y, cw - 10, rh2), align, v)
        p.setPen(QPen(QColor("#CDD5D1")))
        for x in xs:
            p.drawLine(x, y, x, h - 26)
        # 选中框
        p.setPen(QPen(EXCEL_GREEN, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRect(col0, yy, cw, rh2))
        # 底部
        p.fillRect(QRect(0, h - 26, w, 26), QColor("#F3F3F3"))
        p.setPen(QPen(QColor("#D8DEDB")))
        p.drawLine(0, h - 26, w, h - 26)
        p.setPen(QPen(QColor("#3B4440")))
        for i, tab in enumerate(("Sheet1", "Sheet2", "Sheet3")):
            tx = 16 + i * 74
            if i == 0:
                p.fillRect(QRect(tx - 6, h - 24, 68, 22), QColor("#FFFFFF"))
                p.setPen(QPen(EXCEL_GREEN, 2))
                p.drawLine(tx - 6, h - 24, tx + 62, h - 24)
                p.setPen(QPen(QColor("#217346")))
            p.drawText(QRect(tx, h - 24, 68, 22), Qt.AlignCenter, tab)
        p.setPen(QPen(QColor("#4A544F")))
        p.drawText(QRect(w - 300, h - 26, 290, 26), Qt.AlignVCenter | Qt.AlignRight,
                   "就绪    平均值: 128.44    计数: 26    求和: 1,842,310.55")

    # ---- Word ----
    def _paint_word(self, p: QPainter):
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#F3F3F3"))
        p.fillRect(QRect(0, 0, w, 32), WORD_BLUE)
        p.setPen(QPen(QColor("#FFFFFF")))
        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.drawText(QRect(12, 0, 400, 32), Qt.AlignVCenter, "工作报告.docx - Word")
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.1))
        self._paint_win_buttons(p, 4, QColor("#FFFFFF"), WORD_BLUE)
        y = 32
        p.fillRect(QRect(0, y, w, 26), WORD_BLUE.lighter(112))
        p.setPen(QPen(QColor("#E8EEF8")))
        x = 14
        for i, m in enumerate(["文件", "开始", "插入", "设计", "布局", "引用", "邮件", "审阅", "视图"]):
            tw = p.fontMetrics().horizontalAdvance(m)
            if i == 1:
                p.fillRect(QRect(x - 8, y + 3, tw + 16, 20), QColor(255, 255, 255, 40))
            p.drawText(x, y + 18, m)
            x += tw + 22
        y += 26
        rh = 78
        p.fillRect(QRect(0, y, w, rh), QColor("#F7F8FA"))
        p.setPen(QPen(QColor("#D9DEE5")))
        p.drawLine(0, y + rh, w, y + rh)
        p.setPen(QPen(QColor("#3B4440")))
        gx = 16
        for name, btns in (("粘贴", ["粘贴", "剪切", "复制"]),
                           ("字体", ["等线", "12", "B", "I", "U"]),
                           ("段落", ["左", "中", "右", "项目符号", "行距"]),
                           ("样式", ["标题", "标题 1", "正文", "强调"])):
            bx = gx
            for j, b in enumerate(btns):
                col, row = j // 2, j % 2
                rect = QRect(bx + col * 60, y + 8 + row * 22, 56, 20)
                p.drawText(rect, Qt.AlignCenter, b)
            gw = max(120, bx + ((len(btns) - 1) // 2 + 1) * 60 - gx)
            p.setPen(QPen(QColor("#C6CFCA")))
            p.drawLine(gx + gw, y + 6, gx + gw, y + rh - 18)
            p.setPen(QPen(QColor("#6C7671")))
            p.drawText(QRect(gx, y + rh - 16, gw, 14), Qt.AlignCenter, name)
            p.setPen(QPen(QColor("#3B4440")))
            gx += gw + 14
            if gx > w - 100:
                break
        y += rh
        # 页面
        pw = min(720, w - 160)
        px = (w - pw) // 2
        p.fillRect(QRect(px, y + 16, pw, h - y - 34), QColor("#FFFFFF"))
        p.setPen(QPen(QColor("#E2E6EA")))
        p.drawRect(QRect(px, y + 16, pw, h - y - 34))
        p.setPen(QPen(QColor("#2B3038")))
        p.setFont(QFont("Microsoft YaHei UI", 15, QFont.Bold))
        p.drawText(QRect(px + 56, y + 44, pw - 112, 32), Qt.AlignLeft | Qt.AlignVCenter,
                   "2026 年第三季度项目进展报告")
        p.setFont(QFont("Microsoft YaHei UI", 10))
        yy = y + 96
        lines = [1.0, 0.94, 0.98, 0.62, 0.0, 0.9, 0.97, 0.88, 1.0, 0.55, 0.0,
                 0.93, 0.96, 0.72, 0.0, 0.87, 0.99, 0.44]
        for frac in lines:
            if yy > h - 60:
                break
            if frac == 0:
                yy += 14
                continue
            p.setPen(QPen(QColor("#D5D9DE")))
            p.drawRoundedRect(QRect(px + 56, yy, int((pw - 112) * frac), 9), 4, 4)
            yy += 22
        p.setPen(QPen(QColor("#9AA1A9")))
        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.drawText(QRect(0, h - 24, w, 22), Qt.AlignCenter, "第 1 页，共 6 页    1,842 个字    中文(中国)")

    # ---- CMD ----
    def _paint_term(self, p: QPainter):
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), CMD_BG)
        p.fillRect(QRect(0, 0, w, 30), QColor("#1F1F1F"))
        p.setPen(QPen(QColor("#E6E6E6")))
        p.setFont(QFont("Consolas", 9))
        p.drawText(QRect(12, 0, w - 200, 30), Qt.AlignVCenter,
                   "C:\\Windows\\System32\\cmd.exe")
        self._paint_win_buttons(p, 3, QColor("#E6E6E6"), None)
        p.setFont(QFont("Consolas", 10))
        y = 42
        lh = 17
        max_lines = max(1, (h - 60) // lh)
        visible = CMD_LINES[-max_lines:]
        for i, line in enumerate(visible):
            if "PASS" in line:
                p.setPen(QPen(QColor("#16C60C")))
            elif line.startswith("$"):
                p.setPen(QPen(QColor("#F9F1A5")))
            elif "error" in line.lower() or "FAIL" in line:
                p.setPen(QPen(QColor("#E74856")))
            else:
                p.setPen(QPen(QColor("#CCCCCC")))
            p.drawText(18, y + i * lh, line)
        if self._blink and len(visible) < max_lines + 1:
            last = visible[-1] if visible else ""
            cx = 18 + p.fontMetrics().horizontalAdvance(last)
            if last.strip() == "$":
                p.fillRect(QRect(cx + 4, y + (len(visible) - 1) * lh - 12, 9, 15),
                           QColor("#CCCCCC"))
