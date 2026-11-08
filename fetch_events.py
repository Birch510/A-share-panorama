# -*- coding: utf-8 -*-
"""
fetch_events.py —— 事件日历模块取数

实测可用接口（2026-10-30，akshare 1.18.96）：
    stock_yjyg_em(date='20260930')           531 行  业绩预告
    stock_yysj_em(symbol='沪深A股', date=..)  5222 行 业绩预约披露时间
    stock_restricted_release_summary_em()             限售股解禁汇总（需合法 symbol）

说明：
    业绩预告按「报告期」查（如 20260930 表示三季报），不是按公告日；
    预约披露时间按「报告期」查，返回每只股票的预约/变更/实际披露日。
    限售解禁接口的 symbol 参数取值要合法（近一月/近三月/近半年/近一年），
    传「近一年」以外的字符串会报 KeyError。
"""

import pandas as pd

import config
from data_fetcher import (
    缓存, 重试请求, 数值, 规范日期, 紧凑日期, 北京时间, 最近交易日,
    有AK, ak, _无AK错误,
)


def _报告期(日期: str) -> str:
    """把日期规范成报告期 YYYYMMDD；空则用最近一个季度末。"""
    if 日期:
        s = 紧凑日期(日期)
        if s and len(s) == 8 and s.isdigit():
            return s
    今 = 北京时间()
    # 取最近一个已过去的季度末
    for 月日 in ("1231", "0930", "0630", "0331"):
        候选 = "%d%s" % (今.year, 月日)
        if 候选 <= 今.strftime("%Y%m%d"):
            return 候选
    return "%d1231" % (今.year - 1)


def 业绩预告(报告期: str = "") -> tuple:
    """业绩预告。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    目标 = _报告期(报告期)
    缓存键 = "业绩预告_%s" % 目标
    命中 = 缓存.取(缓存键, config.缓存时长["事件"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_yjyg_em, date=目标, 说明="业绩预告", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or ("报告期 %s 无业绩预告数据" % 目标), "东方财富"
    框 = df.copy()
    if "公告日期" in 框.columns:
        框["公告日期"] = 框["公告日期"].map(规范日期)
    for 列 in ["预测数值", "业绩变动幅度", "上年同期值"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    if "股票代码" in 框.columns:
        框["股票代码"] = 框["股票代码"].astype(str).str.zfill(6)
    缓存.存(缓存键, 框)
    return 框.reset_index(drop=True), "", "东方财富"


def 预约披露(报告期: str = "", 市场: str = "沪深A股") -> tuple:
    """业绩预约披露时间表。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    目标 = _报告期(报告期)
    缓存键 = "预约披露_%s_%s" % (目标, 市场)
    命中 = 缓存.取(缓存键, config.缓存时长["事件"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_yysj_em, symbol=市场, date=目标, 说明="预约披露", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or ("报告期 %s 无预约披露数据" % 目标), "东方财富"
    框 = df.copy()
    for 列 in 框.columns:
        if "日期" in 列 or "时间" in 列:
            框[列] = 框[列].astype(str).str.slice(0, 10)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 限售解禁(范围: str = "近三月") -> tuple:
    """限售股解禁汇总。范围：近一月/近三月/近半年/近一年。返回 (DataFrame, 错误, 来源)。

    东财这个接口的 symbol 是「市场」而不是「时间跨度」（全部股票/沪市A股/科创板…），
    时间跨度得靠 start_date/end_date 自己算，传 symbol='近三月' 会直接 KeyError。
    """
    合法 = {"近一月": 31, "近三月": 92, "近半年": 183, "近一年": 366}
    目标 = 范围 if 范围 in 合法 else "近三月"
    缓存键 = "限售解禁_%s" % 目标
    命中 = 缓存.取(缓存键, config.缓存时长["事件"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"

    import datetime as _dt

    # 这个接口只吃紧凑日期（20261023），传带横线的会被 akshare 切片切坏，
    # 底层直接返回 null，然后在 akshare 里抛 'NoneType' object is not subscriptable。
    今天 = 最近交易日()
    起 = 紧凑日期(今天)
    止 = 起
    try:
        末 = _dt.datetime.strptime(今天, "%Y-%m-%d")
        起 = (末 - _dt.timedelta(days=7)).strftime("%Y%m%d")
        止 = (末 + _dt.timedelta(days=合法[目标])).strftime("%Y%m%d")
    except Exception:
        pass

    df, 错 = 重试请求(ak.stock_restricted_release_summary_em,
                    symbol="全部股票", start_date=起, end_date=止,
                    说明="限售解禁", 次数=2)
    if df is None:
        return None, 错 or "限售解禁无数据", "东方财富"
    if len(df) == 0:
        return None, "所选区间内没有解禁安排", "东方财富"
    框 = df.copy()
    for 列 in 框.columns:
        if "日期" in str(列) or "DATE" in str(列).upper():
            try:
                框[列] = 框[列].astype(str).str.slice(0, 10)
            except Exception:
                pass
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 事件概览() -> tuple:
    """事件模块顶部卡片。返回 (dict, 错误列表)。"""
    结果 = {"报告期": 规范日期(_报告期())}
    错误 = []
    for 名称, 函数 in (("业绩预告", 业绩预告), ("预约披露", 预约披露), ("限售解禁", 限售解禁)):
        try:
            df, 错, _ = 函数()
            if df is None:
                错误.append("%s：%s" % (名称, 错))
                结果[名称] = None
                continue
            结果[名称] = len(df)
        except Exception as e:
            错误.append("%s异常：%s" % (名称, str(e)[:60]))
            结果[名称] = None
    return 结果, 错误