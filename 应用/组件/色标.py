# -*- coding: utf-8 -*-
"""
涨跌色标：贴在热力图右侧的一条竖渐变，告诉用户「多红算涨多少」。

没有这个东西，热力图上深浅不同的红绿只是相对的，用户没法知道
深红到底是涨 1% 还是涨 8%。色标把颜色和具体的百分比对上。
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from 应用 import 主题
from 应用.组件.热力图 import _混色, 颜色上限


class 涨跌色标(QWidget):
    """竖直渐变色条 + 右侧刻度，刻度从 +上限 到 -上限。"""

    def __init__(self, 父=None):
        super().__init__(父)
        self.setFixedWidth(62)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def paintEvent(self, 事件):
        画 = QPainter(self)
        画.setRenderHint(QPainter.Antialiasing, True)
        画.setRenderHint(QPainter.TextAntialiasing, True)

        盘 = 主题.当前调色板()
        底 = QColor(盘["卡片"])
        涨色 = QColor(盘["涨"])
        跌色 = QColor(盘["跌"])
        画.fillRect(self.rect(), 底)

        标题字体 = QFont(self.font())
        标题字体.setPixelSize(10)
        刻度字体 = QFont(self.font())
        刻度字体.setPixelSize(10)

        条宽 = 14
        条左 = 2
        顶 = 20
        条高 = self.height() - 顶 - 6
        if 条高 < 40:
            return

        画.setPen(QColor(盘["文字3"]))
        画.setFont(标题字体)
        画.drawText(QRectF(0, 3, self.width(), 14),
                    Qt.AlignLeft | Qt.AlignVCenter, "涨跌幅")

        # 渐变：顶部是涨到上限的最深红，中间接近底色，底部是跌到上限的最深绿
        渐变 = QLinearGradient(条左, 顶, 条左, 顶 + 条高)
        段数 = 24
        for 序 in range(段数 + 1):
            比例 = 序 / 段数                      # 0 在顶部
            涨跌 = 颜色上限 * (1 - 2 * 比例)
            强度 = min(abs(涨跌) / 颜色上限, 1.0)
            基色 = 涨色 if 涨跌 >= 0 else 跌色
            渐变.setColorAt(比例, _混色(底, 基色, 0.14 + 0.80 * 强度))
        画.setPen(Qt.NoPen)
        画.setBrush(渐变)
        画.drawRoundedRect(QRectF(条左, 顶, 条宽, 条高), 3, 3)

        # 刻度：上下两端是 ±上限，中间是 0
        画.setFont(刻度字体)
        画.setPen(QColor(盘["文字2"]))
        刻 = [
            (1.0, "+%.0f%%" % 颜色上限),
            (0.5, "+%.1f%%" % (颜色上限 / 2)),
            (0.0, "0%"),
            (-0.5, "-%.1f%%" % (颜色上限 / 2)),
            (-1.0, "-%.0f%%" % 颜色上限),
        ]
        for 位置, 文本 in 刻:
            y = 顶 + 条高 * (1 - 位置) / 2
            画.drawText(QRectF(条左 + 条宽 + 4, y - 7, self.width() - 条宽 - 6, 14),
                        Qt.AlignLeft | Qt.AlignVCenter, 文本)

        # 零轴那一档画一条极细的参考线，方便一眼找到「不涨不跌」的位置
        零线 = 顶 + 条高 / 2
        画.setPen(QColor(盘["边框深"]))
        画.drawLine(QRectF(条左, 零线, 条宽, 0).topLeft(),
                    QRectF(条左 + 条宽, 零线, 0, 0).topLeft())