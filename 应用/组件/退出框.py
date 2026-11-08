# -*- coding: utf-8 -*-
"""
退出确认框。

系统自带的 QMessageBox 是方角、灰底、默认字号，跟整个界面的设计令牌
（圆角 12、字号 11/12/13/18、间距 4/8/12/16/24）完全不搭，弹出来像另一个
程序。这里自己做一个小窗：圆角 + 细描边 + 品牌图标 + 两行说明；
主按钮是「继续使用」（实心），次按钮是「退出」（描边 + 警示色文字），
按 Esc 或回车都落在「继续使用」上，防手滑。
"""

import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

import config
from 应用 import 主题

框宽 = 428
圆角 = 12
内边距 = 24


class _卡片(QWidget):
    """圆角白底 + 1 像素描边的卡片；无边框窗体的背景默认是方的，得自己画。"""

    def paintEvent(self, 事件):
        盘 = 主题.当前调色板()
        画 = QPainter(self)
        画.setRenderHint(QPainter.Antialiasing, True)
        路 = QPainterPath()
        路.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 圆角, 圆角)
        画.fillPath(路, QColor(盘["卡片"]))
        画.setPen(QColor(盘["边框"]))
        画.drawPath(路)
        画.end()


class 退出框(QDialog):
    """带品牌感的退出确认窗。用 询问() 一句就能拿到 True / False。"""

    def __init__(self, 父=None, 标题: str = "", 正文: str = "", 补充: str = ""):
        super().__init__(父)
        self.setObjectName("退出框")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setWindowTitle("退出")

        self._标题 = 标题 or ("退出 %s" % getattr(config, "应用名称", "A股全景看板"))
        self._正文 = 正文 or "正在拉取的行情会中断，未完成的导出也一并取消。"
        self._补充 = 补充 or "已经缓存的数据下次打开还在，不用重新下载。"
        self._拖动起点 = None

        self._搭建()
        self._淡入()

    # ---------------------------------------------------------------- 搭建

    def _搭建(self):
        盘 = 主题.当前调色板()

        外 = QVBoxLayout(self)
        外.setContentsMargins(0, 0, 0, 0)
        外.setSpacing(0)
        self._卡片 = _卡片(self)
        self._卡片.setObjectName("退出卡片")
        外.addWidget(self._卡片)

        栏 = QVBoxLayout(self._卡片)
        栏.setContentsMargins(内边距, 内边距, 内边距, 内边距)
        栏.setSpacing(0)

        # —— 标题行：品牌图标 + 一句话 ——
        头 = QHBoxLayout()
        头.setContentsMargins(0, 0, 0, 0)
        头.setSpacing(12)
        self._图标位 = QLabel(self._卡片)
        self._图标位.setObjectName("退出图标")
        self._图标位.setFixedSize(36, 36)
        self._图标位.setPixmap(self._应用图标(36))
        头.addWidget(self._图标位, 0, Qt.AlignTop)

        题 = QLabel(self._标题, self._卡片)
        题.setObjectName("退出标题")
        题.setWordWrap(True)
        头.addWidget(题, 1, Qt.AlignVCenter)
        栏.addLayout(头)

        栏.addSpacing(16)

        自 = QLabel(self._正文, self._卡片)
        自.setObjectName("退出正文")
        自.setWordWrap(True)
        栏.addWidget(自)

        栏.addSpacing(8)

        补 = QLabel(self._补充, self._卡片)
        补.setObjectName("退出补充")
        补.setWordWrap(True)
        栏.addWidget(补)

        栏.addSpacing(24)

        分隔 = QWidget(self._卡片)
        分隔.setObjectName("退出分隔")
        分隔.setFixedHeight(1)
        栏.addWidget(分隔)

        栏.addSpacing(16)

        # —— 按钮行：次按钮在左、主按钮在右 ——
        钮行 = QHBoxLayout()
        钮行.setContentsMargins(0, 0, 0, 0)
        钮行.setSpacing(8)
        钮行.addStretch(1)

        self._退出钮 = QPushButton("退出", self._卡片)
        self._退出钮.setObjectName("退出次按钮")
        self._退出钮.setCursor(Qt.PointingHandCursor)
        self._退出钮.setToolTip("关闭程序，正在拉取的行情会中断")
        self._退出钮.clicked.connect(self.accept)
        钮行.addWidget(self._退出钮)

        self._继续钮 = QPushButton("继续使用", self._卡片)
        self._继续钮.setObjectName("退出主按钮")
        self._继续钮.setCursor(Qt.PointingHandCursor)
        self._继续钮.setToolTip("回到看板继续看；按 Esc 或回车也是这个")
        self._继续钮.clicked.connect(self.reject)
        self._继续钮.setDefault(True)
        self._继续钮.setAutoDefault(True)
        钮行.addWidget(self._继续钮)
        栏.addLayout(钮行)

        self.setStyleSheet(self._样式(盘))
        self.setFixedWidth(框宽)
        self.adjustSize()

    def _应用图标(self, 尺寸: int) -> QPixmap:
        路径 = getattr(config, "页面图标", "")
        try:
            if 路径 and os.path.exists(路径):
                return QIcon(路径).pixmap(尺寸, 尺寸)
        except Exception:
            pass
        空 = QPixmap(尺寸, 尺寸)
        空.fill(Qt.transparent)
        return 空

    def _样式(self, 盘) -> str:
        return """
        /* 卡片底色与圆角由 _卡片.paintEvent 画：走样式表的话圆角只切背景、四个角
           仍然是方的，透出底下的页面底色。这里只声明透明，避免样式表再铺一层。 */
        #退出卡片 { background: transparent; border: none; }
        #退出标题 { color: %(文1)s; font-size: 18px; font-weight: 600; }
        /* 全局样式给所有 QWidget 铺了一层底色，标签必须显式透明，否则白卡片上会
           出现一块块页面底色的方块 */
        #退出卡片 QLabel { background: transparent; border: none; }
        #退出正文 { color: %(文2)s; font-size: 13px; }
        #退出补充 { color: %(文3)s; font-size: 12px; }
        #退出分隔 { background: %(边)s; border: none; }
        QPushButton {
            font-size: 13px;
            min-height: 30px;
            padding: 4px 18px;
            border-radius: 8px;
        }
        #退出主按钮 {
            color: %(实心文)s;
            background: %(实心)s;
            border: 1px solid %(实心)s;
        }
        #退出主按钮:hover { background: %(悬停深)s; border-color: %(悬停深)s; }
        #退出次按钮 {
            color: %(警示)s;
            background: transparent;
            border: 1px solid %(边深)s;
        }
        #退出次按钮:hover { background: %(悬停)s; }
        """ % {
            "卡": 盘["卡片"], "圆": 圆角,
            "文1": 盘["文字1"], "文2": 盘["文字2"], "文3": 盘["文字3"],
            "边": 盘["边框"], "边深": 盘["边框深"],
            "实心": 盘["实心"], "实心文": 盘["实心文字"],
            "悬停": 盘["悬停"], "悬停深": 盘["边框深"], "警示": 盘["涨"],
        }

    # ---------------------------------------------------------------- 动效

    def _淡入(self):
        self._效果 = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._效果)
        self._动画 = QPropertyAnimation(self._效果, b"opacity", self)
        self._动画.setDuration(130)
        self._动画.setStartValue(0.0)
        self._动画.setEndValue(1.0)
        self._动画.setEasingCurve(QEasingCurve.OutCubic)
        self._动画.finished.connect(self._清效果)
        self._动画.start(QPropertyAnimation.DeleteWhenStopped)

    def _清效果(self):
        try:
            self.setGraphicsEffect(None)
        except RuntimeError:
            pass

    # ---------------------------------------------------------------- 交互

    def 按钮文字(self):
        return [self._退出钮.text(), self._继续钮.text()]

    def keyPressEvent(self, 事件):
        # Esc / 回车都当「继续使用」，防手滑退出
        if 事件.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.reject()
            return
        super().keyPressEvent(事件)

    def mousePressEvent(self, 事件):
        if 事件.button() == Qt.LeftButton:
            self._拖动起点 = 事件.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(事件)

    def mouseMoveEvent(self, 事件):
        if self._拖动起点 is not None and (事件.buttons() & Qt.LeftButton):
            self.move(事件.globalPosition().toPoint() - self._拖动起点)
            return
        super().mouseMoveEvent(事件)

    def mouseReleaseEvent(self, 事件):
        self._拖动起点 = None
        super().mouseReleaseEvent(事件)

    def showEvent(self, 事件):
        super().showEvent(事件)
        父 = self.parentWidget()
        if 父 is not None:
            中 = 父.geometry().center()
            self.move(中.x() - self.width() // 2, 中.y() - self.height() // 2)
        self._继续钮.setFocus(Qt.OtherFocusReason)


def 询问(父=None, 标题: str = "", 正文: str = "", 补充: str = "") -> bool:
    """弹一次确认框：点「退出」返回 True，点「继续使用」/ Esc 返回 False。"""
    框 = 退出框(父, 标题, 正文, 补充)
    return 框.exec() == QDialog.Accepted