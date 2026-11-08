# -*- coding: utf-8 -*-
"""
宏观数据：大盘的地基。

PMI 看制造业景气度（50 是荣枯线），CPI/PPI 看通胀，
M0/M1/M2 看货币松紧，国债收益率看无风险利率。
这些东西不直接影响某只股票，但决定了整个市场的估值中枢。

数据都来自国家统计局和财政部，每月更新一次，不快但准。
"""

import pandas as pd
from PySide6.QtWidgets import QVBoxLayout, QWidget

import fetch_macro
from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 分区, 来源标注
from 应用.组件.图块 import 图块
from 应用.组件.折线图 import 折线图
from 应用.页面.助手 import 加载柱状, 加载折线, 加载表格
from 应用.页面.多子页 import 多子页

# 折线图看最近五年（60 个月），再往前的形状参考价值不大
PMI_月数 = 60


def _PMI() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(8)

    图 = 折线图("最近五年 PMI", 高度=300)
    图来源 = 来源标注("正在获取 PMI 数据…")
    布局.addWidget(图块(
        "PMI 走势",
        "50 是荣枯线，站上去说明制造业在扩张、掉下来说明在收缩。"
        "制造业与非制造业两条线对照着看，能分出是生产端弱还是需求端弱。"
        "鼠标移上去能读出那个月两条线的具体数值；点右上「放大」可铺满整页看细节。",
        图, 尾注=图来源))

    布局.addWidget(分区("PMI 明细", "表格按时间倒序，最近几个月在最上面。"))
    布局.addWidget(加载表格(fetch_macro.PMI, (), "PMI", 420, "国家统计局"))

    def 到了(结果):
        try:
            框 = 结果[0] if isinstance(结果, (tuple, list)) else 结果
            来源文字 = 结果[2] if isinstance(结果, (tuple, list)) and len(结果) > 2 else "国家统计局"
            错误 = 结果[1] if isinstance(结果, (tuple, list)) and len(结果) > 1 else ""
        except Exception:
            return
        if 框 is None or not hasattr(框, "empty") or 框.empty:
            图.清空("PMI 数据没取到：%s" % (错误 or "接口返回为空"))
            图来源.setText("取数失败：%s" % (错误 or "接口返回为空"))
            return

        try:
            表 = 框.copy()
            if "日期" in 表.columns:
                表["_日"] = pd.to_datetime(表["日期"], errors="coerce")
            elif "月份" in 表.columns:
                # 「2026年09月份」这种中文月份，扒出年月再补成当月 1 号
                抽 = 表["月份"].astype(str).str.extract(r"(\d{4})\D+(\d{1,2})")
                表["_日"] = pd.to_datetime(
                    抽[0].fillna("1970") + "-" + 抽[1].fillna("1") + "-01", errors="coerce")
            else:
                图.清空("PMI 数据里没有日期列")
                return

            表 = 表.dropna(subset=["_日"]).sort_values("_日").tail(PMI_月数)
            if 表.empty:
                图.清空("PMI 数据里没有可用日期")
                return

            类别 = [d.strftime("%Y-%m") for d in 表["_日"]]
            系列 = []
            for 列名, 显示名 in (("制造业-指数", "制造业"), ("非制造业-指数", "非制造业")):
                if 列名 in 表.columns:
                    值 = pd.to_numeric(表[列名], errors="coerce").tolist()
                    if any(v == v for v in 值):
                        系列.append((显示名, [None if v != v else float(v) for v in 值], None))
            if not 系列:
                图.清空("PMI 数据里没有指数列")
                return

            图.换数据(系列, 类别, 参考线=(50.0, "荣枯线 50"), Y轴标题="指数（50 为荣枯线）", 小数位=1)
            图来源.setText("数据来源：%s ｜ 显示最近 %d 个月 ｜ 虚线为 50 荣枯线" % (
                来源文字 or "国家统计局", len(类别)))
        except Exception as 错:
            图.清空("PMI 折线画不出来：%s" % 错)

    def 失败(错误文本: str):
        图.清空("PMI 数据没取到：%s" % 错误文本)
        try:
            图来源.setText("取数失败：%s" % 错误文本)
        except Exception:
            pass

    def 拉():
        图来源.setText("正在获取 PMI 数据…")
        后台运行(fetch_macro.PMI, 完成=到了, 失败=失败)

    外.重取 = 拉
    拉()
    return 外


def _同比取值(列名: str, 名称: str, 月数: int = 60, 参考线=None):
    """做「按月的同比折线」用的取值函数。"""

    def 取值(框):
        尾 = 框.tail(月数)
        类别 = [str(x)[:7] for x in 尾["日期"]]
        值 = pd.to_numeric(尾[列名], errors="coerce")
        return 类别, [(名称, [None if v != v else round(float(v), 2) for v in 值], None)], 参考线

    return 取值


def _货币取值(框):
    """M2 与 M1 的同比增速对照，两条线剪个差就是剪刀差。"""
    尾 = 框.tail(60)
    类别 = [str(x)[:7] for x in 尾["日期"]]
    M2 = pd.to_numeric(尾["货币和准货币(M2)-同比增长"], errors="coerce")
    M1 = pd.to_numeric(尾["货币(M1)-同比增长"], errors="coerce")
    系列 = [
        ("M2 同比", [None if v != v else round(float(v), 2) for v in M2], "#2f6bd8"),
        ("M1 同比", [None if v != v else round(float(v), 2) for v in M1], "#d18700"),
    ]
    return 类别, 系列, None


def _社融取值(框):
    """社融月度增量，柱状看单月多寡。"""
    尾 = 框.tail(36)
    类别 = [str(x)[:7] for x in 尾["日期"]]
    值 = pd.to_numeric(尾["社会融资规模增量"], errors="coerce")
    return 类别, [None if v != v else round(float(v), 2) for v in 值], None, "增量（亿元）"


def _国债取值(框):
    """10 年期、2 年期与期限利差（10 年 - 2 年）。"""
    尾 = 框.tail(500)
    类别 = [str(x)[:10] for x in 尾["日期"]]
    系列 = []
    for 列, 名, 色 in (
        ("中国国债收益率10年", "中国 10 年期", "#d32029"),
        ("中国国债收益率2年", "中国 2 年期", "#2f6fd0"),
        ("中国国债收益率10年-2年", "期限利差（10年-2年）", "#0f766e"),
    ):
        if 列 in 尾.columns:
            值 = pd.to_numeric(尾[列], errors="coerce")
            系列.append((名, [None if v != v else round(float(v), 3) for v in 值], 色))
    return 类别, 系列, None


def _曲线取值(框):
    """国债收益率曲线：横轴是期限（2 年 / 5 年 / 10 年 / 30 年），
    纵轴是那一天的收益率。同一天几个期限连起来就是市场对未来的定价。"""
    期限 = [("2年", "中国国债收益率2年"), ("5年", "中国国债收益率5年"),
            ("10年", "中国国债收益率10年"), ("30年", "中国国债收益率30年")]
    有 = [(名, 列) for 名, 列 in 期限 if 列 in 框.columns]
    if not 有:
        return [], [], None
    类别 = [名 for 名, _ in 有]
    有效 = 框.dropna(subset=[列 for _, 列 in 有])
    if 有效.empty:
        return [], [], None

    def 取一行(行):
        return [None if pd.isna(行.get(列)) else round(float(行.get(列)), 3)
                for _, 列 in 有]

    末 = 有效.iloc[-1]
    系列 = [("最新（%s）" % str(末.get("日期", ""))[:10], 取一行(末), "#d32029")]
    # 再叠一条约一个月前的曲线，一眼能看出曲线是整体上移还是走陡
    for 回看, 名, 色 in ((21, "一个月前", "#2f6bd8"), (252, "一年前", "#8b95a3")):
        if len(有效) > 回看:
            旧 = 有效.iloc[-1 - 回看]
            系列.append(("%s（%s）" % (名, str(旧.get("日期", ""))[:10]),
                         取一行(旧), 色))
    return 类别, 系列, None


def _国库券期限说明(框) -> str:
    """一句话点出曲线形态：正常向上 / 平坦 / 倒挂。"""
    列 = ["中国国债收益率2年", "中国国债收益率10年"]
    if any(c not in 框.columns for c in 列):
        return ""
    尾 = 框.dropna(subset=列)
    if 尾.empty:
        return ""
    行 = 尾.iloc[-1]
    短 = float(行[列[0]])
    长 = float(行[列[1]])
    if 长 > 短 + 0.2:
        形 = "陡峭向上，长端要求更高的补偿"
    elif 长 >= 短:
        形 = "小幅向上，属于常态"
    else:
        形 = "倒挂，短端比长端还贵，通常是资金面很紧的信号"
    return "曲线 %s（2 年 %.2f%% → 10 年 %.2f%%，相差 %+.2f 个百分点）" % (
        形, 短, 长, 长 - 短)


def _物价() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(图块(
        "CPI 同比走势", "反映消费端通胀，同比转负意味着通缩压力。"
                     "鼠标移上去读月度数值，点「放大」可铺满整页。",
        加载折线(
            fetch_macro.CPI, (), 取值=_同比取值("全国-同比增长", "CPI 同比", 参考线=(0.0, "零轴")),
            标题="CPI 同比（%）", 高度=270, 来源文字="国家统计局")))
    布局.addWidget(加载表格(fetch_macro.CPI, (), "CPI", 260, "国家统计局"))
    布局.addWidget(图块(
        "PPI 同比走势", "反映生产端价格，PPI 转正通常利好上游周期股。"
                     "鼠标移上去读月度数值，点「放大」可铺满整页。",
        加载折线(
            fetch_macro.PPI, (), 取值=_同比取值("当月同比增长", "PPI 同比", 参考线=(0.0, "零轴")),
            标题="PPI 同比（%）", 高度=270, 来源文字="国家统计局")))
    布局.addWidget(加载表格(fetch_macro.PPI, (), "PPI", 260, "国家统计局"))
    return 外


def _货币() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(图块(
        "货币供应量同比",
        "M1 增速回升往往领先于股市见底，M2-M1 剪刀差收窄是资金活化的信号。"
        "鼠标移上去读月度数值，点「放大」可铺满整页。",
        加载折线(
            fetch_macro.货币供应, (), 取值=_货币取值,
            标题="M2 与 M1 同比（%）", 高度=290, 来源文字="中国人民银行")))
    布局.addWidget(加载表格(fetch_macro.货币供应, (), "货币供应", 280, "中国人民银行"))
    布局.addWidget(图块(
        "社会融资规模增量", "社融是实体经济的血液，单月增量超预期对市场是利好。"
                       "柱子上的数字就是单月增量，点「放大」可铺满整页。",
        加载柱状(
            fetch_macro.社会融资, (), 取值=_社融取值,
            标题="社融月度增量（亿元）", 高度=280, 来源文字="中国人民银行", 小数位=0)))
    布局.addWidget(加载表格(fetch_macro.社会融资, (), "社会融资", 280, "中国人民银行"))
    return 外


def _利率() -> QWidget:
    外 = QWidget()
    布局 = QVBoxLayout(外)
    布局.setContentsMargins(0, 8, 0, 0)
    布局.setSpacing(12)
    布局.addWidget(图块(
        "国债收益率与期限利差",
        "10 年期是无风险利率的锚。期限利差走阔常对应宽货币、"
        "走平甚至倒挂则要留个心眼。鼠标移上去读某一天的收益率，点「放大」铺满整页。",
        加载折线(
            fetch_macro.国债收益率, (), 取值=_国债取值,
            标题="中国国债收益率（%）", 高度=320, 来源文字="新浪")))

    曲线图 = 折线图("国债收益率曲线（%）", 高度=280)
    曲线说明 = 来源标注("正在获取国债收益率…")
    布局.addWidget(图块(
        "国债收益率曲线",
        "横轴是期限、纵轴是收益率，把同一天的各期限连起来，"
        "就是市场对资金价格的整体定价。曲线越陡，说明市场预期未来更贵。"
        "鼠标移上去能读出每个期限的具体收益率。",
        曲线图, 尾注=曲线说明))

    布局.addWidget(加载表格(fetch_macro.国债收益率, (), "国债收益率", 420, "新浪"))

    def 曲线到了(结果):
        try:
            框 = 结果[0] if isinstance(结果, (tuple, list)) else 结果
        except Exception:
            框 = None
        if 框 is None or len(框) == 0:
            曲线图.清空("没有取到国债收益率数据")
            曲线说明.setText("取数失败：接口返回为空")
            return
        类别, 系列, _ = _曲线取值(框)
        if not 类别 or not 系列:
            曲线图.清空("国债收益率数据里没有期限列")
            return
        曲线图.换数据(系列, 类别, Y轴标题="到期收益率（%）", 小数位=3)
        曲线说明.setText("%s ｜ 数据来源：新浪" % _国库券期限说明(框))

    def 拉曲线():
        曲线说明.setText("正在获取国债收益率…")
        后台运行(fetch_macro.国债收益率, 完成=曲线到了,
                 失败=lambda 错: (曲线图.清空("没取到国债收益率：%s" % 错),
                               曲线说明.setText("取数失败：%s" % 错)))

    外.重取 = 拉曲线
    拉曲线()
    return 外


class 宏观数据(多子页):
    def __init__(self):
        super().__init__(
            "宏观数据",
            "PMI、物价、货币、社融与利率，决定市场整体估值中枢的那几个变量。",
            [
                ("PMI 景气", _PMI),
                ("CPI 与 PPI", _物价),
                ("货币与社融", _货币),
                ("国债收益率", _利率),
            ],
        )


def 页面() -> QWidget:
    return 宏观数据()