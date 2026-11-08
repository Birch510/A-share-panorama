# -*- coding: utf-8 -*-
"""
多子页基类：一个页面里分几块内容，用一排按钮切换。

和网页里的标签页不同，这里**只创建当前这一页**，
点到别的子页时才现建。理由很简单：一个页面里往往要打好几个接口，
全建出来就等于一次拉一堆数据，白白拖慢首屏。
"""

from PySide6.QtWidgets import QStackedWidget, QWidget

from 应用.组件.基础 import 分段选择器
from 应用.页面.基类 import 页面基


class 多子页(页面基):
    """
    子页定义写成 [(名称, 工厂函数), (名称, 工厂函数), ...]，
    工厂函数不带参数、返回一个 QWidget。
    """

    def __init__(self, 标题: str, 说明: str, 子页定义: list):
        super().__init__(标题, 说明)
        self._定义 = list(子页定义)
        self._缓存 = {}

        self._选择器 = 分段选择器([名 for 名, _ in self._定义])
        self.加(self._选择器)

        self._堆 = QStackedWidget()
        self.加(self._堆)
        self.加伸缩()

        self._选择器.选择变化.connect(self.切)
        if self._定义:
            self.切(self._定义[0][0])

    def 切(self, 名: str):
        for 页名, 工厂 in self._定义:
            if 页名 != 名:
                continue
            if 名 not in self._缓存:
                控件 = 工厂()
                控件.setObjectName("内容区")
                self._缓存[名] = 控件
                self._堆.addWidget(控件)
            self._堆.setCurrentWidget(self._缓存[名])
            self._选择器.设当前(名)
            return

    def 应用主题变化(self):
        for 控件 in self._缓存.values():
            处理 = getattr(控件, "应用主题变化", None)
            if callable(处理):
                try:
                    处理()
                except Exception as 错:
                    print("子页主题刷新失败：", 错)