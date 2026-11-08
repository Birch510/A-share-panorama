# -*- coding: utf-8 -*-
"""
资金面：钱往哪儿跑。

四个子页：
    个股资金流 —— 主力净流入排行（图 + 表）
    概念资金流 —— 哪些概念在吸金（图 + 表）
    北向资金 —— 沪深港通当日概览与历史
    两融数据 —— 融资融券余额趋势（折线 + 表）

注意：北向资金 2024 年 8 月之后官方停止披露日度明细，
     所以「当日成交净买额」这类列近期全是空值，画不出折线，
     这一页就只给表，并在说明里写清楚原因，不硬画一条空图。
"""

import pandas as pd
from PySide6.QtWidgets import QVBoxLayout, QWidget

import fetch_capital
from 应用.组件.基础 import 分区
from 应用.页面.助手 import 加载柱状, 加载折线, 加载表格
from 应用.页面.多子页 import 多子页

# 排行榜取前多少名画图：横条太多会挤成一团，20 条刚好一屏看得清
条形条数 = 20


def _净额排行(框, 名称列: str, 净额列: str = "净额"):
    """把资金流表整理成「净额最大的前 N 名」，单位换算成亿元。"""
    框 = 框.copy()
    数值 = pd.to_numeric(框[净额列], errors="coerce")
    框 = 框.assign(_值=数值).dropna(subset=["_值"])
    if 框.empty:
        return [], [], None, "净额（亿元）"
    前 = 框.nlargest(条形条数, "_值")
    标签 = [str(x) for x in 前[名称列]]
    值 = [round(float(v) / 1e8, 2) for v in 前["_值"]]
    # 返回降序，柱状图组件的横条会自己倒过来，最大的排在最上面
    return 标签, 值, None, "净额（亿元）"


def _个股取值(框):
    return _净额排行(框, "股票简称")


def _概念取值(框):
    # 概念表的列名是「行业」不是「板块」，净额列同个股
    return _净额排行(框, "行业")


def _沪市两融取值(框):
    """沪市融资余额走势，单位从元换成年。"""
    框 = 框.copy()
    余额 = pd.to_numeric(框["融资余额"], errors="coerce") / 1e8
    日期 = [str(x) for x in 框["日期"]]
    return 日期, [("融资余额", [None if v != v else round(float(v), 2) for v in 余额], None)], None


def _两融账户取值(框):
    """全市场融资/融券余额走势，原始单位就是亿元，只取最近三年。"""
    框 = 框.tail(750).copy()
    融资 = pd.to_numeric(框["融资余额"], errors="coerce")
    融券 = pd.to_numeric(框["融券余额"], errors="coerce")
    日期 = [str(x) for x in 框["日期"]]
    系列 = [
        ("融资余额", [None if v != v else round(float(v), 2) for v in 融资], "#d32029"),
        ("融券余额", [None if v != v else round(float(v), 2) for v in 融券], "#2f6fd0"),
    ]
    return 日期, 系列, None


def _个股() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(分区("主力净流入前 20 名", "按当日净流入金额排序，红条是流入、绿条是流出。"))
    布局.addWidget(加载柱状(
        fetch_capital.个股资金流, (200,), 取值=_个股取值,
        标题="净流入（亿元）", 高度=440, 来源文字="新浪", 横向=True,
        说明="数值为正代表主力净买入"))
    布局.addWidget(分区("个股资金流明细", "按当日净流入金额从高到低，取前 200 只。"))
    布局.addWidget(加载表格(fetch_capital.个股资金流, (200,), "个股资金流排行", 420, "新浪"))
    return 外


def _概念() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(分区("概念板块净流入前 20 名", "看当天资金往哪些概念里扎堆。"))
    布局.addWidget(加载柱状(
        fetch_capital.概念资金流, (), 取值=_概念取值,
        标题="净流入（亿元）", 高度=440, 来源文字="新浪", 横向=True,
        说明="数值为正代表概念板块整体净流入"))
    布局.addWidget(分区("概念资金流明细", "含领涨股与公司家数，按净额排序看更直观。"))
    布局.addWidget(加载表格(fetch_capital.概念资金流, (), "概念资金流", 420, "新浪"))
    return 外


def _北向() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(分区("北向资金当日概览", "沪股通与深股通的成交净买额、涨跌家数。"))
    布局.addWidget(加载表格(fetch_capital.北向概览, (), "北向资金概览", 160, "东方财富"))
    布局.addWidget(分区("北向资金历史",
                         "2024 年 8 月后官方停止披露日度净买额，这一列近期为空，"
                         "只能看沪深300 与领涨股，历史累计净买额请回看早年数据。"))
    布局.addWidget(加载表格(fetch_capital.北向历史, (250,), "北向资金历史", 360, "东方财富"))
    return 外


def _两融() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(分区("沪市融资余额走势", "最近 60 个交易日的融资余额，单位亿元。"))
    布局.addWidget(加载折线(
        fetch_capital.两融沪市, (60,), 取值=_沪市两融取值,
        标题="沪市融资余额（亿元）", 高度=280, 来源文字="上交所"))
    布局.addWidget(加载表格(fetch_capital.两融沪市, (60,), "沪市两融", 280, "上交所"))
    布局.addWidget(分区("全市场两融余额走势", "融资余额与融券余额对比，最近三年。"))
    布局.addWidget(加载折线(
        fetch_capital.两融账户历史, (), 取值=_两融账户取值,
        标题="两融余额（亿元）", 高度=280, 来源文字="东方财富"))
    布局.addWidget(加载表格(fetch_capital.两融账户历史, (), "两融账户历史", 300, "东方财富"))
    return 外


class 资金面(多子页):
    def __init__(self):
        super().__init__(
            "资金面",
            "追踪主力、概念、北向与两融资金的方向，判断市场是在进还是在出。",
            [
                ("个股资金流", _个股),
                ("概念资金流", _概念),
                ("北向资金", _北向),
                ("两融数据", _两融),
            ],
        )


def 页面() -> QWidget:
    return 资金面()