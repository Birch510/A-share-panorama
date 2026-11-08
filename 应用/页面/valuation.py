# -*- coding: utf-8 -*-
"""
估值水平：现在的价格贵不贵。

四个子页：
    重点板块估值 —— 13 个重点板块的滚动市盈率横向对比
    行业估值排行 —— 申万二级 127 个行业，可排序找最贵最便宜
    个股估值走势 —— 单只股票的 PE/PB 历史
    证监会行业参考 —— 官方口径的行业静态市盈率

口径说明：滚动市盈率（PE-TTM）用最近四个季度利润，比静态市盈率更贴近当下。
"""

import pandas as pd
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

import fetch_valuation
from 应用.组件.基础 import 分区, 来源标注, 指标行
from 应用.组件.柱状图 import 柱状图
from 应用.组件.数据表 import 数据表
from 应用.组件.图块 import 图块
from 应用.后台任务 import 后台运行
from 应用.页面.助手 import 可刷新柱状, 可刷新折线, 加载表格
from 应用.页面.多子页 import 多子页

# 估值不是涨跌，柱状图用中性的蓝色，不用红绿
估值柱色 = "#2f6bd8"

# 行业排行一次画多少个：横向条形太多会挤到看不清字
行业条数 = 20

# 可以拿来排序的字段，都是「越小越便宜」的口径
行业字段 = ["滚动市盈率", "静态市盈率", "市净率", "市销率", "市现率", "总市值(亿)", "成份个数"]


def _市盈率取值(框):
    类别 = [str(x)[:10] for x in 框["日期"]]
    系列 = []
    for 列, 名, 色 in (("市盈率(TTM)", "市盈率 TTM", "#d32029"),
                       ("市盈率(静态)", "市盈率 静态", "#2f6fd0")):
        if 列 in 框.columns:
            值 = pd.to_numeric(框[列], errors="coerce")
            系列.append((名, [None if v != v else round(float(v), 2) for v in 值], 色))
    return 类别, 系列, None


def _市净率取值(框):
    类别 = [str(x)[:10] for x in 框["日期"]]
    系列 = []
    for 列, 名, 色 in (("市净率", "市净率", "#0f766e"),
                       ("市销率", "市销率", "#7c3aed")):
        if 列 in 框.columns:
            值 = pd.to_numeric(框[列], errors="coerce")
            系列.append((名, [None if v != v else round(float(v), 2) for v in 值], 色))
    return 类别, 系列, None


def _板块() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)

    布局.addWidget(分区(
        "重点板块滚动市盈率",
        "13 个重点板块横着比，条越长说明估值越贵。"
        "滚动市盈率用最近四个季度的利润算，比静态市盈率更贴近当下。"))
    图 = 柱状图("滚动市盈率（倍）", 高度=380, 横向=True)
    布局.addWidget(图)
    图来源 = 来源标注("正在获取估值数据…")
    布局.addWidget(图来源)

    布局.addWidget(分区("13 个重点板块估值", "按滚动市盈率排序，同口径横向对比。"))
    布局.addWidget(加载表格(fetch_valuation.板块估值一览, (), "重点板块估值", 380, "东财数据中心"))
    布局.addWidget(分区("行业估值总表", "申万二级行业 127 个，含市净率、市销率、总市值与亏损家数。"))
    布局.addWidget(加载表格(fetch_valuation.行业估值表, (), "行业估值总表", 380, "东财数据中心"))

    def 到了(结果):
        try:
            框, 错误, 来源文字 = 结果
        except Exception:
            return
        if 框 is None or getattr(框, "empty", True):
            图.清空("估值数据没取到：%s" % (错误 or "接口返回为空"))
            图来源.setText("取数失败：%s" % (错误 or "接口返回为空"))
            return
        try:
            列 = "滚动市盈率" if "滚动市盈率" in 框.columns else None
            if 列 is None or "板块" not in 框.columns:
                图.清空("估值数据里没有板块或市盈率列")
                return
            表 = 框.copy()
            表["_值"] = pd.to_numeric(表[列], errors="coerce")
            表 = 表.dropna(subset=["_值"]).sort_values("_值")
            if 表.empty:
                图.清空("估值数据全是空值")
                return
            图.换数据(表["板块"].astype(str).tolist(), 表["_值"].astype(float).tolist(),
                     正向色=估值柱色, 小数位=1, 轴标题="滚动市盈率（倍）")
            最贵 = 表.iloc[-1]
            最便宜 = 表.iloc[0]
            图来源.setText("数据来源：%s ｜ %d 个板块 ｜ 最贵 %s %.1f 倍，最便宜 %s %.1f 倍" % (
                来源文字 or "东财数据中心", len(表),
                最贵["板块"], float(最贵["_值"]), 最便宜["板块"], float(最便宜["_值"])))
        except Exception as 错:
            图.清空("估值柱状图画不出来：%s" % 错)

    def 失败(错误文本: str):
        图.清空("估值数据没取到：%s" % 错误文本)
        try:
            图来源.setText("取数失败：%s" % 错误文本)
        except Exception:
            pass

    def 拉():
        图来源.setText("正在获取估值数据…")
        后台运行(fetch_valuation.板块估值一览, 完成=到了, 失败=失败)

    外.重取 = 拉
    拉()
    return 外


def _行业() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)

    布局.addWidget(分区("申万二级行业估值排行",
                         "挑一个指标排个序，一眼看出哪几个行业最贵、哪几个最便宜。"))

    # 排序条件放在一个字典里，取值函数每次画的时候读它，这样下拉一变就能重画
    状态 = {"字段": "滚动市盈率", "方向": "从低到高"}

    def 取值(框):
        字段 = 状态["字段"]
        数值 = pd.to_numeric(框[字段], errors="coerce")
        干净 = 框.assign(_值=数值).dropna(subset=["_值"])
        if 干净.empty:
            return [], [], None, 字段
        升序 = 状态["方向"] == "从低到高"
        干净 = 干净.sort_values("_值", ascending=升序)
        if 升序:
            干净 = 干净.head(行业条数)
        else:
            干净 = 干净.head(行业条数)
        标签 = [str(x) for x in 干净["行业名称"]]
        值 = [round(float(v), 2) for v in 干净["_值"]]
        return 标签, 值, None, 字段

    栏 = QWidget()
    栏行 = QHBoxLayout(栏)
    栏行.setContentsMargins(0, 0, 0, 0)
    栏行.setSpacing(8)
    栏行.addWidget(QLabel("排序指标"))
    字段框 = QComboBox()
    字段框.addItems(行业字段)
    栏行.addWidget(字段框)
    栏行.addWidget(QLabel("顺序"))
    方向框 = QComboBox()
    方向框.addItems(["从低到高", "从高到低"])
    栏行.addWidget(方向框)
    栏行.addStretch(1)
    布局.addWidget(栏)

    图 = 可刷新柱状(fetch_valuation.行业估值表, 取值=取值,
                    标题="行业估值排行", 高度=460, 来源文字="东财数据中心",
                    横向=True, 说明="只画前 %d 个行业" % 行业条数)
    布局.addWidget(图)

    def 重画(_=None):
        状态["字段"] = 字段框.currentText()
        状态["方向"] = 方向框.currentText()
        图.图.清空("正在重排…")
        图.刷新()

    字段框.currentTextChanged.connect(重画)
    方向框.currentTextChanged.connect(重画)

    布局.addWidget(分区("行业估值总表", "点表头任意列也能排序，这里给全量 100 多个行业。"))
    布局.addWidget(加载表格(fetch_valuation.行业估值表, (), "行业估值排行", 460, "东财数据中心"))
    重画()
    return 外


def _个股() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("个股估值走势", "输入股票代码，看这只股票近年来的市盈率与市净率变化。"))

    栏 = QWidget()
    栏行 = QHBoxLayout(栏)
    栏行.setContentsMargins(0, 0, 0, 0)
    栏行.setSpacing(8)
    栏行.addWidget(QLabel("股票代码"))
    输入 = QLineEdit("600111")
    输入.setMaximumWidth(110)
    输入.setPlaceholderText("如 600111")
    栏行.addWidget(输入)

    栏行.addWidget(QLabel("天数"))
    天数 = QLineEdit("500")
    天数.setMaximumWidth(80)
    栏行.addWidget(天数)

    按钮 = QPushButton("查询")
    按钮.setObjectName("主按钮")
    栏行.addWidget(按钮)
    栏行.addStretch(1)
    布局.addWidget(栏)

    # ---- 市盈率曲线
    PE图 = 可刷新折线(fetch_valuation.个股估值, 取值=_市盈率取值,
                      标题="市盈率（倍）", 高度=280, 来源文字="东方财富")
    布局.addWidget(图块("市盈率走势",
                        "TTM 与静态两条线对照，突然抬高通常是业绩下滑而非股价上涨。"
                        "鼠标移上去能读出那天的数值；点「放大」可铺满整页。",
                        PE图))

    # ---- 市净率与市销率
    PB图 = 可刷新折线(fetch_valuation.个股估值, 取值=_市净率取值,
                      标题="市净率 / 市销率（倍）", 高度=280, 来源文字="东方财富")
    布局.addWidget(图块("市净率与市销率走势",
                        "市净率适合重资产行业，市销率适合还没盈利的成长股。"
                        "鼠标移上去能读出那天的数值；点「放大」可铺满整页。",
                        PB图))

    布局.addWidget(分区("估值明细", "逐日的市值、股本与各项估值倍数。"))
    表 = 数据表(None, 高度=420, 标题="个股估值")
    布局.addWidget(表)
    提示 = 来源标注("东方财富")
    布局.addWidget(提示)

    def 查():
        代码 = 输入.text().strip() or "600111"
        try:
            天 = max(30, int(天数.text().strip() or 500))
        except ValueError:
            天 = 500
        提示.setText("正在获取 %s 的估值数据…" % 代码)
        表.置加载(True, "正在获取 %s 的估值数据…" % 代码)
        PE图.刷新(代码, 天)
        PB图.刷新(代码, 天)
        后台运行(fetch_valuation.个股估值, 完成=到了, 失败=失败, 参数=(代码, 天))

    def 到了(结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            表.置加载(False)
            提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or 框.empty:
            表.换数据(None)
            提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        表.换数据(框)
        提示.setText("数据来源：%s ｜ %d 行" % (来源 or "东方财富", len(框)))

    def 失败(错误文本):
        表.置加载(False)
        提示.setText("取数失败：%s" % 错误文本)

    按钮.clicked.connect(查)
    输入.returnPressed.connect(查)
    外.重取 = 查
    查()
    return 外


def _证监会() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)
    布局.addWidget(分区("证监会行业静态市盈率", "官方行业分类口径，最近一个报告期。"))
    布局.addWidget(加载表格(fetch_valuation.证监会行业估值, (), "证监会行业估值", 480, "巨潮资讯"))
    return 外


class 估值水平(多子页):
    def __init__(self):
        super().__init__(
            "估值水平",
            "用滚动市盈率、市净率判断板块与个股现在的价格处在什么位置。",
            [
                ("重点板块估值", _板块),
                ("行业估值排行", _行业),
                ("个股估值走势", _个股),
                ("证监会行业", _证监会),
            ],
        )


def 页面() -> QWidget:
    return 估值水平()