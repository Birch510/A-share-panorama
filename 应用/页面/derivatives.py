# -*- coding: utf-8 -*-
"""
衍生品与其他品种：股债商汇一起看。

期货主力 —— 挑一个品种看主力连续合约的 K 线
期货实时 —— 全部品种的实时报价
ETF 净值 —— 场内基金的最新净值
可转债 —— 债性与股性的分界

顺手看一眼商品和可转债，能提前感受到资金在往哪个方向挪。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget)

import fetch_derivatives
from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 分区, 分段选择器, 来源标注, 指标卡
from 应用.组件.K线图 import K线图
from 应用.页面.助手 import 加载表格
from 应用.页面.多子页 import 多子页

# 主力连续合约品种：代码 -> 中文名，都是新浪的主力连续（数字 0 结尾）
品种表 = [
    ("V0", "螺纹钢"), ("I0", "铁矿石"), ("CU0", "沪铜"), ("AL0", "沪铝"),
    ("AU0", "沪金"), ("AG0", "沪银"), ("SC0", "原油"), ("M0", "豆粕"),
    ("TA0", "精对苯二甲酸"), ("IF0", "沪深300股指"),
    ("IC0", "中证500股指"), ("IH0", "上证50股指"),
]

周期选项 = ["日K", "周K", "月K"]

天数选项 = ["半年", "1年", "2年", "3年"]
天数表 = {"半年": 500, "1年": 1000, "2年": 2000, "3年": 3000}


def _期货主力() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)

    布局.addWidget(分区("主力连续 K 线",
                        "挑一个品种看它的主力连续合约走势。滚轮缩放，左键拖动，双击复位。"))

    栏 = QWidget()
    栏行 = QHBoxLayout(栏)
    栏行.setContentsMargins(0, 0, 0, 0)
    栏行.setSpacing(8)
    栏行.addWidget(QLabel("品种"))
    品种框 = QComboBox()
    for 代, 名 in 品种表:
        品种框.addItem("%s（%s）" % (名, 代), 代)
    品种框.setMinimumWidth(158)
    栏行.addWidget(品种框)
    栏行.addSpacing(12)
    栏行.addWidget(QLabel("回看"))
    天数框 = QComboBox()
    天数框.addItems(天数选项)
    天数框.setCurrentText("1年")
    天数框.setMinimumWidth(86)
    栏行.addWidget(天数框)
    栏行.addStretch(1)
    周期钮 = 分段选择器(周期选项, 当前="日K")
    栏行.addWidget(周期钮, 0, Qt.AlignTop)
    布局.addWidget(栏)

    图 = K线图(标题="主力连续", 周期="日K")
    图.setMinimumHeight(460)
    布局.addWidget(图)
    提示 = 来源标注("正在获取主力连续行情…")
    布局.addWidget(提示)

    指标 = QWidget()
    指标布局 = QHBoxLayout(指标)
    指标布局.setContentsMargins(0, 0, 0, 0)
    指标布局.setSpacing(8)
    布局.addWidget(指标)

    def 填指标(框):
        while 指标布局.count():
            项 = 指标布局.takeAt(0)
            if 项.widget():
                项.widget().deleteLater()
        try:
            数值 = 框["收盘"].astype(float)
            最新 = float(数值.iloc[-1])
            首 = float(数值.iloc[0])
            涨跌 = (最新 / 首 - 1) * 100 if 首 else 0.0
            方向 = 1 if 涨跌 > 0 else (-1 if 涨跌 < 0 else 0)
            最高 = float(框["最高"].astype(float).max())
            最低 = float(框["最低"].astype(float).min())
        except Exception:
            return
        for 名, 值, 注, 向 in [
            ("最新价", "%.2f" % 最新, "", 方向),
            ("区间涨跌", "%+.2f%%" % 涨跌, "%d 根" % len(框), 方向),
            ("区间最高", "%.2f" % 最高, "", 0),
            ("区间最低", "%.2f" % 最低, "", 0),
        ]:
            指标布局.addWidget(指标卡(名, 值, 注, 向))

    def 聚合(框):
        """期货接口只给日线，周/月线在本地按自然周、自然月重采样。"""
        周期 = 周期钮.当前()
        if 周期 == "日K" or "日期" not in 框.columns:
            return 框
        try:
            import pandas as pd

            合 = 框.copy()
            合["日期"] = pd.to_datetime(合["日期"])
            合 = 合.set_index("日期")
            规则 = "W-FRI" if 周期 == "周K" else "ME"
            表 = {"开盘": "first", "最高": "max", "最低": "min", "收盘": "last"}
            for 列 in ("成交量", "持仓量"):
                if 列 in 合.columns:
                    表[列] = "sum"
            return 合.resample(规则).agg(表).dropna(subset=["收盘"]).reset_index()
        except Exception:
            return 框

    def 拉(*_):
        代 = 品种框.currentData() or "V0"
        名 = dict(品种表).get(代, 代)
        提示.setText("正在获取 %s 的%s数据…" % (名, 周期钮.当前()))
        后台运行(fetch_derivatives.期货主力日线, 完成=到了, 失败=失败,
                 参数=(代, 天数表.get(天数框.currentText(), 1000)))

    def 到了(结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or 框.empty:
            图.清空("暂无数据")
            提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        代 = 品种框.currentData() or "V0"
        名 = dict(品种表).get(代, 代)
        周期 = 周期钮.当前()
        整理 = 聚合(框)
        图.换数据(整理, 标题="%s %s" % (名, 周期), 周期=周期)
        填指标(整理)
        提示.setText("数据来源：%s ｜ %s %s ｜ 共 %d 根 ｜ 滚轮缩放，左键拖动，双击复位"
                     % (来源 or "新浪", 名, 周期, len(整理)))

    def 失败(错误文本):
        图.清空("取数失败")
        提示.setText("取数失败：%s" % 错误文本)

    品种框.currentIndexChanged.connect(拉)
    天数框.currentTextChanged.connect(拉)
    周期钮.选择变化.connect(拉)
    外.重取 = 拉
    拉()
    return 外


def _期货实时() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("期货实时行情", "全部品种的最新价、涨跌幅、成交量与持仓量。"))
    布局.addWidget(加载表格(fetch_derivatives.期货实时总表, (), "期货实时行情", 520, "新浪"))
    return 外


def _ETF() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("ETF 基金净值", "场内基金的最新单位净值与累计净值。"))
    布局.addWidget(加载表格(fetch_derivatives.ETF净值, (), "ETF 净值", 500, "东方财富"))
    return 外


def _可转债() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("可转债实时行情", "价格高于 130 偏股性，低于 100 偏债性。"))
    布局.addWidget(加载表格(fetch_derivatives.可转债实时, (), "可转债行情", 500, "新浪"))
    return 外


class 衍生品(多子页):
    def __init__(self):
        super().__init__(
            "衍生品",
            "期货、ETF 与可转债，看商品和债券市场在给股票什么信号。",
            [
                ("期货主力", _期货主力),
                ("期货实时", _期货实时),
                ("ETF 基金", _ETF),
                ("可转债", _可转债),
            ],
        )


def 页面() -> QWidget:
    return 衍生品()