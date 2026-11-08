# -*- coding: utf-8 -*-
"""
fetch_sentiment.py —— 情绪复盘模块取数

实测可用接口（2026-10-30，akshare 1.18.96）：
    stock_zt_pool_em(date)              涨停股池     20261030→43 行
    stock_zt_pool_strong_em(date)       强势股池
    stock_zt_pool_zbgc_em(date)         炸板股池
    stock_zt_pool_dtgc_em(date)         跌停股池
    stock_lhb_detail_em(start, end)     龙虎榜详情   1490 行
    stock_lhb_stock_statistic_em(symbol) 个股上榜统计 539 行

注意：
    涨停池等接口必须传「交易日」，非交易日返回空表；
    所以内部统一走 最近交易日() 兜底，页面不要直接传当天日期。
"""

import pandas as pd

import config
from data_fetcher import (
    缓存, 重试请求, 数值, 规范日期, 紧凑日期, 北京时间, 最近交易日,
    有AK, ak, _无AK错误,
)

# 涨停池/跌停池/炸板池的字段中文名统一
_池字段 = ["序号", "代码", "名称", "涨跌幅", "最新价", "成交额", "流通市值", "总市值",
           "换手率", "封板资金", "首次封板时间", "最后封板时间", "炸板次数", "涨停统计",
           "连板数", "所属行业"]


def _取日期(日期: str) -> str:
    """把用户传入的日期规范成 YYYYMMDD；空则用最近交易日。

    东财这几个池子接口只认紧凑日期（20261030）。传带横线的不会被报错，
    而是安静地返回空表，看起来像"今天没有涨停股"——这个坑踩过一次。
    """
    if 日期:
        s = 紧凑日期(日期)
        if s and len(s) == 8 and s.isdigit():
            return s
    return 紧凑日期(最近交易日())


def _抓池(函数名: str, 日期: str, 说明: str) -> tuple:
    """抓涨停/跌停/炸板/强势股池的通用逻辑。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    目标 = _取日期(日期)
    缓存键 = "%s_%s" % (说明, 目标)
    命中 = 缓存.取(缓存键, config.缓存时长["情绪"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    函数 = getattr(ak, 函数名, None)
    if 函数 is None:
        return None, "当前 akshare 版本没有接口 %s" % 函数名, "无"
    df, 错 = 重试请求(函数, date=目标, 说明=说明, 次数=2)
    if df is None:
        return None, 错 or ("%s无数据" % 说明), "东方财富"
    if len(df) == 0:
        return pd.DataFrame(), "%s 在 %s 无数据（非交易日或当日无此类股票）" % (说明, 目标), "东方财富"
    框 = df.copy()
    框 = 框[[c for c in 框.columns]]
    for 列 in ["涨跌幅", "最新价", "成交额", "流通市值", "总市值", "换手率", "封板资金", "连板数", "炸板次数"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    if "代码" in 框.columns:
        框["代码"] = 框["代码"].astype(str).str.zfill(6)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 涨停池(日期: str = "") -> tuple:
    """涨停股池。返回 (DataFrame, 错误, 来源)。"""
    return _抓池("stock_zt_pool_em", 日期, "涨停股池")


def 强势股池(日期: str = "") -> tuple:
    """强势股池（近期多次涨停等）。返回 (DataFrame, 错误, 来源)。"""
    return _抓池("stock_zt_pool_strong_em", 日期, "强势股池")


def 炸板池(日期: str = "") -> tuple:
    """炸板股池（曾涨停后打开）。返回 (DataFrame, 错误, 来源)。"""
    return _抓池("stock_zt_pool_zbgc_em", 日期, "炸板股池")


def 跌停池(日期: str = "") -> tuple:
    """跌停股池。返回 (DataFrame, 错误, 来源)。"""
    return _抓池("stock_zt_pool_dtgc_em", 日期, "跌停股池")


def 龙虎榜(开始日期: str = "", 结束日期: str = "") -> tuple:
    """龙虎榜详情。默认取最近 10 个自然日。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    终 = 紧凑日期(结束日期) if 结束日期 else 紧凑日期(最近交易日())
    始 = 紧凑日期(开始日期) if 开始日期 else 紧凑日期(
        规范日期((pd.Timestamp(终) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")))
    缓存键 = "龙虎榜_%s_%s" % (始, 终)
    命中 = 缓存.取(缓存键, config.缓存时长["情绪"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_lhb_detail_em, start_date=始, end_date=终,
                    说明="龙虎榜", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "龙虎榜无数据（区间内可能非交易日）", "东方财富"
    框 = df.copy()
    if "上榜日" in 框.columns:
        框["上榜日"] = 框["上榜日"].map(规范日期)
    for 列 in ["收盘价", "涨跌幅", "龙虎榜净买额", "龙虎榜买入额", "龙虎榜卖出额", "市场总成交额", "净买额占总成交比"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 龙虎榜统计(周期: str = "近一月") -> tuple:
    """个股上榜统计。周期取值：近一月 / 近三月 / 近六月 / 近一年。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    缓存键 = "龙虎榜统计_%s" % 周期
    命中 = 缓存.取(缓存键, config.缓存时长["情绪"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_lhb_stock_statistic_em, symbol=周期,
                    说明="龙虎榜统计", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "龙虎榜统计无数据", "东方财富"
    缓存.存(缓存键, df)
    return df, "", "东方财富"


def 情绪概览(日期: str = "") -> tuple:
    """情绪模块顶部汇总。返回 (dict, 错误列表)。"""
    目标 = _取日期(日期)
    结果 = {"交易日": 规范日期(目标)}
    错误 = []
    for 名称, 函数 in (("涨停", 涨停池), ("跌停", 跌停池), ("炸板", 炸板池), ("强势", 强势股池)):
        try:
            df, 错, _ = 函数(目标)
            if df is None:
                错误.append("%s池：%s" % (名称, 错))
                结果[名称] = None
                continue
            结果[名称] = len(df)
        except Exception as e:
            错误.append("%s池异常：%s" % (名称, str(e)[:60]))
            结果[名称] = None
    # 连板高度：涨停池里 连板数 最大值
    try:
        涨, _, _ = 涨停池(目标)
        if 涨 is not None and "连板数" in 涨.columns:
            有效 = 涨["连板数"].dropna()
            结果["最高连板"] = int(有效.max()) if len(有效) else None
        else:
            结果["最高连板"] = None
    except Exception:
        结果["最高连板"] = None
    return 结果, 错误