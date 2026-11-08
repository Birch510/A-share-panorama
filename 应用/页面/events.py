# -*- coding: utf-8 -*-
"""
事件日历：接下来会发生什么。

业绩预告 —— 公司自己先说赚了多少，是行情的重要催化
预约披露 —— 什么时候出正式财报，提前知道好避雷
限售解禁 —— 大股东什么时候能卖，解禁前后往往有抛压

这三件事都不看技术面，但经常决定一只股票短期怎么走。
"""

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

import fetch_events
from 应用.组件.基础 import 分区, 来源标注
from 应用.页面.助手 import 可刷新表格
from 应用.页面.多子页 import 多子页

# 报告期选项：第一项是「交给程序自己找最近一期」
报告期选项 = ["自动（最近一期）", "2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31",
              "2025-09-30", "2025-06-30", "2025-03-31"]

# 预约披露的市场口径，和接口的 symbol 取值一一对应
市场选项 = ["沪深A股", "沪市A股", "深市A股", "科创板", "创业板", "京市A股"]

# 解禁的时间范围
解禁范围 = ["近一月", "近三月", "近半年", "近一年"]


def _按关键字(框, 词: str):
    """按股票代码或简称做包含匹配；词为空就原样返回。"""
    词 = (词 or "").strip()
    if not 词 or 框 is None or getattr(框, "empty", True):
        return 框
    for 列 in ("股票简称", "股票代码", "名称", "代码"):
        if 列 in 框.columns:
            return 框[框[列].astype(str).str.contains(词, case=False, na=False, regex=False)]
    return 框


def _预告() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("业绩预告", "选定报告期看各家说了什么。关键字可以搜代码或简称。"))

    栏 = QWidget()
    栏行 = QHBoxLayout(栏)
    栏行.setContentsMargins(0, 0, 0, 0)
    栏行.setSpacing(8)
    栏行.addWidget(QLabel("报告期"))
    期框 = QComboBox()
    期框.addItems(报告期选项)
    期框.setMinimumWidth(132)
    栏行.addWidget(期框)
    栏行.addSpacing(8)
    栏行.addWidget(QLabel("关键字"))
    词框 = QLineEdit()
    词框.setPlaceholderText("代码或简称，如 600519 或 茅台")
    词框.setMinimumWidth(190)
    栏行.addWidget(词框)
    栏行.addStretch(1)
    布局.addWidget(栏)

    块 = 可刷新表格(fetch_events.业绩预告, 标题="业绩预告", 高度=500, 来源文字="东方财富")
    布局.addWidget(块)

    def 取(*_):
        期 = 期框.currentText()
        块.刷新() if 期.startswith("自动") else 块.刷新(期)

    def 筛(*_):
        """在已经取回来的数据上过滤，不重新联网。"""
        if 块.原始 is None:
            return
        筛后 = _按关键字(块.原始, 词框.text())
        块._显示(筛后, "东方财富（关键字筛选后 %d 行）" % len(筛后) if 词框.text().strip()
              else "东方财富")

    期框.currentTextChanged.connect(取)
    词框.textChanged.connect(筛)
    # 全局刷新重取回来的是全量数据，关键字还得再套一遍，
    # 否则输入框里还有字、表里却冒出没筛过的行
    块.刷新后 = 筛
    取()
    return 外


def _预约() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("预约披露时间", "各家公司的财报披露计划，含首次预约、变更与实际披露时间。"))

    栏 = QWidget()
    栏行 = QHBoxLayout(栏)
    栏行.setContentsMargins(0, 0, 0, 0)
    栏行.setSpacing(8)
    栏行.addWidget(QLabel("报告期"))
    期框 = QComboBox()
    期框.addItems(报告期选项)
    期框.setMinimumWidth(132)
    栏行.addWidget(期框)
    栏行.addSpacing(8)
    栏行.addWidget(QLabel("市场"))
    市框 = QComboBox()
    市框.addItems(市场选项)
    市框.setMinimumWidth(96)
    栏行.addWidget(市框)
    栏行.addStretch(1)
    布局.addWidget(栏)

    块 = 可刷新表格(fetch_events.预约披露, 标题="预约披露", 高度=500, 来源文字="东方财富")
    布局.addWidget(块)

    def 取(*_):
        期 = 期框.currentText()
        期参 = "" if 期.startswith("自动") else 期
        块.刷新(期参, 市框.currentText())

    期框.currentTextChanged.connect(取)
    市框.currentTextChanged.connect(取)
    取()
    return 外


def _解禁() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("限售股解禁", "解禁市值越大、占流通比越高，抛压越重。"))

    栏 = QWidget()
    栏行 = QHBoxLayout(栏)
    栏行.setContentsMargins(0, 0, 0, 0)
    栏行.setSpacing(8)
    栏行.addWidget(QLabel("范围"))
    范框 = QComboBox()
    范框.addItems(解禁范围)
    范框.setCurrentText("近三月")
    范框.setMinimumWidth(96)
    栏行.addWidget(范框)
    栏行.addStretch(1)
    布局.addWidget(栏)

    块 = 可刷新表格(fetch_events.限售解禁, 标题="限售解禁", 高度=500, 来源文字="东方财富")
    布局.addWidget(块)

    范框.currentTextChanged.connect(lambda 名="": 块.刷新(名))
    块.刷新("近三月")
    return 外


class 事件日历(多子页):
    def __init__(self):
        super().__init__(
            "事件日历",
            "业绩预告、财报预约与解禁安排，提前知道接下来可能影响股价的事。",
            [
                ("业绩预告", _预告),
                ("预约披露", _预约),
                ("限售解禁", _解禁),
            ],
        )


def 页面() -> QWidget:
    return 事件日历()