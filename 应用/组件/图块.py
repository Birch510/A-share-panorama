# -*- coding: utf-8 -*-
"""
图块：给一张图配一个标题行（带「放大」按钮）和一行来源说明。

放大做的事很简单 —— 把它所在页面布局里除自己以外的块全部藏起来，
只留图块自己撑满整页；再点一次全部还原。不用给每张图单独写一遍逻辑，
也不用维护一份「放大时要藏谁」的清单：谁在同一个页面里就藏谁。

高度用补间动画改（默认 300 毫秒、先快后慢），所以看起来是「长开」而不是「跳开」。
"""

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from 应用.组件.基础 import 分区


class 图块(QWidget):
    """标题行 + 图 + 可选的尾注（来源说明）。"""

    def __init__(self, 标题: str, 说明: str, 图, 尾注=None, 父=None):
        super().__init__(父)
        self._图 = 图
        self._尾注 = 尾注
        self._放大中 = False
        self._放回高 = 0
        self._高动画 = None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(8)

        标题行 = QWidget(self)
        标题布局 = QHBoxLayout(标题行)
        标题布局.setContentsMargins(0, 0, 0, 0)
        标题布局.setSpacing(8)
        标题布局.addWidget(分区(标题, 说明), 1)

        self._按钮 = QPushButton("放大", 标题行)
        self._按钮.setObjectName("主题按钮")
        self._按钮.setCheckable(True)
        self._按钮.setCursor(Qt.PointingHandCursor)
        self._按钮.setToolTip("把这幅图铺满整页，鼠标移上去能读出每个位置的数值；再点一下收回")
        self._按钮.clicked.connect(self._切换展开)
        标题布局.addWidget(self._按钮, 0, Qt.AlignTop)

        self._标题行 = 标题行
        布局.addWidget(标题行)
        布局.addWidget(图, 1)
        if 尾注 is not None:
            布局.addWidget(尾注)

    # ---------------------------------------------------------------- 对外

    def 切换展开(self, 展开: bool = None):
        self._切换展开(展开)

    # ---------------------------------------------------------------- 放大

    def _所在页(self):
        """一路往上找，直到拿到有 .布局 的页面（页面基）。"""
        件 = self.parent()
        while 件 is not None:
            if hasattr(件, "布局") and hasattr(件, "viewport"):
                return 件
            件 = 件.parent()
        return None

    def _切换展开(self, 展开: bool = None):
        状态 = (not self._放大中) if 展开 is None else bool(展开)
        if 状态 == self._放大中:
            return
        self._放大中 = 状态
        self._按钮.setChecked(状态)
        self._按钮.setText("还原" if 状态 else "放大")

        页 = self._所在页()
        if 页 is not None:
            布局 = 页.布局
            for i in range(布局.count()):
                件 = 布局.itemAt(i).widget()
                if 件 is None or 件 is self:
                    continue
                件.setVisible(not 状态)

        if 状态:
            # 收回时的高度要记「真正在画的那张图」的高度，
            # 不能记外层容器 —— 容器比图高出一截（还有来源说明那一行），
            # 记错了收回就会越收越高。
            self._放回高 = max(180, int(self._目标图().height()))
            视口 = max(页.viewport().height(), 480) if 页 is not None else 720
            目标 = max(320, 视口 - 120)
            self._设高(目标, 300)
        else:
            self._设高(self._放回高 or 260, 260)

    def _目标图(self):
        """剥掉「可刷新折线 / 可刷新柱状」这层壳，拿到真正在画的那张图。

        壳比图高（还含一行来源说明），壳的高度不能当图的高度用 ——
        记错了收回时就会越收越高（实测 270 → 292）。
        """
        件 = self._图
        for _ in range(3):
            内 = getattr(件, "图", None)
            if 内 is None:
                break
            件 = 内
        return 件

    def _设高(self, 高: int, 毫秒: int):
        目标 = self._目标图()
        if hasattr(目标, "置高"):
            目标.置高(高, 毫秒)
            return
        目标.setMinimumHeight(高)
        目标.setMaximumHeight(高)