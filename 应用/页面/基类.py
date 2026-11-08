# -*- coding: utf-8 -*-
"""
页面基类：统一的标题区 + 竖向滚动容器。

十个页面结构一样：上面一行页面标题和说明，下面是各自的内容。
把这些共同部分收在这里，页面文件里只写「这个页面有什么」。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget


class 页面基(QScrollArea):
    def __init__(self, 标题: str, 说明: str = "", 父=None):
        super().__init__(父)
        self._标题文字 = 标题
        self._说明文字 = 说明

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)

        内容 = QWidget()
        内容.setObjectName("内容区")
        self.布局 = QVBoxLayout(内容)
        self.布局.setContentsMargins(32, 16, 32, 32)
        self.布局.setSpacing(12)

        # ---- 页面头 ----
        头 = QWidget(内容)
        头布局 = QVBoxLayout(头)
        头布局.setContentsMargins(0, 0, 0, 16)
        头布局.setSpacing(4)

        标 = QLabel(标题, 头)
        标.setObjectName("页面标题")
        头布局.addWidget(标)

        if 说明:
            副 = QLabel(说明, 头)
            副.setObjectName("页面说明")
            副.setWordWrap(True)
            头布局.addWidget(副)
        self.布局.addWidget(头)

        self.setWidget(内容)

        # 滚轮一格默认只滚 3 行，长页面翻起来很费手；调到 30px 快一档。
        self.verticalScrollBar().setSingleStep(30)
        self.horizontalScrollBar().setSingleStep(30)

    # ------------------------------------------------------------ 便捷方法

    def 加(self, 控件):
        if 控件 is not None:
            self.布局.addWidget(控件)
        return 控件

    def 加间隙(self, 像素: int = 8):
        间隔 = QWidget()
        间隔.setFixedHeight(像素)
        self.布局.addWidget(间隔)

    def 加伸缩(self):
        self.布局.addStretch(1)

    def 应用主题变化(self):
        """主题切换后，子类需要重画的东西在这里处理（默认什么也不做）。"""
        pass

    def 刷新(self) -> int:
        """
        重新取一遍本页的数据，返回发起的取数次数。

        做法是找「带 重取 的块」：助手搭出来的表、折线、柱状、指标卡都有，
        页面里自己搭的区块（比如估值页的三块图）也会挂一个 重取 上去。
        重取 会原样重放上一次的参数 —— 涨停股池停在 10 月 31 日，
        全局刷新之后还应该停在 10 月 31 日，不能悄悄跳回默认日期。

        页面上有自己那套取数（首页的指数/全市场、板块页的列表/热力、
        个股页的查询、期货页的主力合约）的，子类覆盖 刷新，
        先调 super().刷新() 再补自己的那几次。
        """
        次数 = 0
        已包 = []
        for 块 in self.findChildren(QWidget):
            # 外层区块已经重取过，里面的子块就别再取一遍，
            # 否则同一份数据会被拉两次。
            if any(爸 is 块 or 爸.isAncestorOf(块) for 爸 in 已包):
                continue
            方法 = getattr(块, "重取", None)
            if not callable(方法):
                continue
            try:
                方法()
            except Exception as 错:
                print("页面刷新失败：%r" % (错,))
                continue
            已包.append(块)
            次数 += 1
        return 次数

    @property
    def 标题(self) -> str:
        return self._标题文字