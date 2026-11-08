# -*- coding: utf-8 -*-
"""
情绪复盘：今天市场是亢奋还是冰点。

看几个数就够了：涨停多少、跌停多少、炸板率多高、连板梯队几层。
涨停家数远多于跌停，说明接力情绪好；炸板率高说明封不住。

每一页上方都有交易日选择，可以回看历史某一天的池子。
选到非交易日接口会返回空，这是正常的，换一天即可。
"""

import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QDateEdit, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

import fetch_sentiment
from data_fetcher import 最近交易日
from 应用.组件.基础 import 分区
from 应用.页面.助手 import 加载柱状, 加载表格, 加载指标, 可刷新表格
from 应用.页面.多子页 import 多子页

# 情绪概览返回的键固定是这六个，按这个顺序先把空卡摆出来
概览键 = ["交易日", "涨停", "跌停", "炸板", "强势", "最高连板"]


def _默认日期() -> str:
    """默认取最近一个交易日：打开就是有数据的一天，不用用户自己找。"""
    try:
        return str(最近交易日())[:10]
    except Exception:
        return QDate.currentDate().toString("yyyy-MM-dd")


def _日期条(标签: str = "交易日") -> tuple:
    """建一条「交易日 [日期] [查询]」的横条，返回 (控件, 日期框, 按钮)。"""
    条 = QWidget()
    横 = QHBoxLayout(条)
    横.setContentsMargins(0, 0, 0, 0)
    横.setSpacing(8)

    文字 = QLabel(标签)
    横.addWidget(文字)

    日期框 = QDateEdit()
    日期框.setCalendarPopup(True)
    日期框.setDisplayFormat("yyyy-MM-dd")
    日期框.setDate(QDate.fromString(_默认日期(), "yyyy-MM-dd"))
    日期框.setMinimumWidth(120)
    横.addWidget(日期框)

    按钮 = QPushButton("查询")
    按钮.setObjectName("主按钮")
    横.addWidget(按钮)
    横.addStretch(1)
    return 条, 日期框, 按钮


def _连板取值(框):
    """把涨停池按连板数分组，数每个高度有几家。"""
    数值 = pd.to_numeric(框.get("连板数"), errors="coerce").dropna()
    数值 = 数值[数值 >= 1]
    if 数值.empty:
        return [], [], None, "家数"
    分组 = 数值.astype(int).value_counts().sort_index()
    标签 = ["%d 连板" % 层 for 层 in 分组.index]
    return 标签, [int(v) for v in 分组.values], None, "家数"


def _概览() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(分区("市场情绪指标", "涨停、跌停、炸板、强势股数量与最高连板数。"))
    布局.addWidget(加载指标(fetch_sentiment.情绪概览, (), "正在统计当日情绪数据…",
                          每行=3, 骨架=概览键, 来源文字="东方财富"))
    布局.addWidget(分区("连板高度分布", "高度越高说明接力越猛；只剩一两个高度时代表情绪退潮。"))
    布局.addWidget(加载柱状(fetch_sentiment.涨停池, (), 取值=_连板取值,
                          标题="涨停股连板高度分布", 高度=300, 来源文字="东方财富",
                          小数位=0, 说明="按涨停池里的连板数分档统计"))
    return 外


def _涨停() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    条, 日期框, 按钮 = _日期条()
    布局.addWidget(条)
    布局.addWidget(分区("涨停股池", "含封板资金、首次/最后封板时间、连板数、所属行业。"))
    表 = 可刷新表格(fetch_sentiment.涨停池, "涨停股池", 460, "东方财富")
    布局.addWidget(表)

    def 查():
        表.刷新(日期框.date().toString("yyyy-MM-dd"))

    按钮.clicked.connect(查)
    日期框.dateChanged.connect(lambda _: 查())
    表.刷新(_默认日期())
    return 外


def _炸板() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    条, 日期框, 按钮 = _日期条()
    布局.addWidget(条)
    布局.addWidget(分区("炸板股池", "盘中触及涨停但没能封住，是情绪转弱的先行信号。"))
    表 = 可刷新表格(fetch_sentiment.炸板池, "炸板股池", 460, "东方财富")
    布局.addWidget(表)

    def 查():
        表.刷新(日期框.date().toString("yyyy-MM-dd"))

    按钮.clicked.connect(查)
    日期框.dateChanged.connect(lambda _: 查())
    表.刷新(_默认日期())
    return 外


def _跌停() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    条, 日期框, 按钮 = _日期条()
    布局.addWidget(条)
    布局.addWidget(分区("跌停股池", "跌停家数突然放大通常意味着恐慌情绪。"))
    表 = 可刷新表格(fetch_sentiment.跌停池, "跌停股池", 460, "东方财富")
    布局.addWidget(表)

    def 查():
        表.刷新(日期框.date().toString("yyyy-MM-dd"))

    按钮.clicked.connect(查)
    日期框.dateChanged.connect(lambda _: 查())
    表.刷新(_默认日期())
    return 外


def _龙虎榜() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)

    终 = QDate.fromString(_默认日期(), "yyyy-MM-dd")
    始 = 终.addDays(-10)

    条 = QWidget()
    横 = QHBoxLayout(条)
    横.setContentsMargins(0, 0, 0, 0)
    横.setSpacing(8)
    横.addWidget(QLabel("起始日期"))
    起框 = QDateEdit()
    起框.setCalendarPopup(True)
    起框.setDisplayFormat("yyyy-MM-dd")
    起框.setDate(始)
    起框.setMinimumWidth(120)
    横.addWidget(起框)
    横.addWidget(QLabel("结束日期"))
    终框 = QDateEdit()
    终框.setCalendarPopup(True)
    终框.setDisplayFormat("yyyy-MM-dd")
    终框.setDate(终)
    终框.setMinimumWidth(120)
    横.addWidget(终框)
    按钮 = QPushButton("查询")
    按钮.setObjectName("主按钮")
    横.addWidget(按钮)
    横.addStretch(1)
    布局.addWidget(条)

    布局.addWidget(分区("龙虎榜明细", "区间内每日上榜个股与席位净买卖额，默认最近 10 个自然日。"))
    表 = 可刷新表格(fetch_sentiment.龙虎榜, "龙虎榜", 500, "东方财富")
    布局.addWidget(表)

    def 查():
        表.刷新(起框.date().toString("yyyy-MM-dd"), 终框.date().toString("yyyy-MM-dd"))

    按钮.clicked.connect(查)
    表.刷新(始.toString("yyyy-MM-dd"), 终.toString("yyyy-MM-dd"))
    return 外


class 情绪复盘(多子页):
    def __init__(self):
        super().__init__(
            "情绪复盘",
            "用涨停、炸板、跌停、连板与龙虎榜判断短线情绪的温度。",
            [
                ("情绪概览", _概览),
                ("涨停股池", _涨停),
                ("炸板股池", _炸板),
                ("跌停股池", _跌停),
                ("龙虎榜", _龙虎榜),
            ],
        )


def 页面() -> QWidget:
    return 情绪复盘()