# -*- coding: utf-8 -*-
"""
fetch_capital.py —— 资金面模块取数

实测可用接口（2026-10-30，akshare 1.18.96）：
    stock_fund_flow_individual(symbol='即时')   5217 行  个股资金流（新浪）
    stock_fund_flow_concept(symbol='即时')      387 行   概念资金流（新浪）
    stock_fund_flow_industry(symbol='即时')     行业资金流（新浪）
    stock_hsgt_fund_flow_summary_em()           4 行     北向资金当日概览（东财）
    stock_margin_sse(start_date, end_date)               上交所两融汇总
    stock_margin_szse(date)                     1 行     深交所两融汇总
    stock_margin_account_info()                 3417 行  两融账户历史
    datacenter-web RPT_DMSK_TS_STOCKNEW                  个股资金流明细（东财数据中心）

注意：
    北向资金日度净买入自 2024 年 8 月起停止披露，stock_hsgt_hist_em 近 5 日数值全为 NaN，
    所以只能做「历史回顾」，不能做「今日北向实时」。
"""

import pandas as pd

import config
from data_fetcher import (
    缓存, 重试请求, 数值, 规范日期, 紧凑日期, 北京时间, 东财数据中心,
    有AK, ak, _无AK错误,
)


def 个股资金流(取前: int = 200) -> tuple:
    """新浪个股资金流排行。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "个股资金流"
    命中 = 缓存.取(缓存键, config.缓存时长["资金流"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"

    df, 错 = 重试请求(ak.stock_fund_flow_individual, symbol="即时",
                    说明="个股资金流", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "个股资金流无数据", "新浪"
    框 = df.copy()
    # 数值列是带单位/百分号的字符串，统一转数字
    for 列 in ["最新价", "涨跌幅", "换手率", "流入资金", "流出资金", "净额", "成交额"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    if "净额" in 框.columns:
        框 = 框.sort_values("净额", ascending=False, na_position="last")
    框["股票代码"] = 框["股票代码"].astype(str).str.zfill(6)
    框 = 框.reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框.head(取前).reset_index(drop=True), "", "新浪"


def 概念资金流() -> tuple:
    """新浪概念板块资金流。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "概念资金流"
    命中 = 缓存.取(缓存键, config.缓存时长["资金流"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_fund_flow_concept, symbol="即时",
                    说明="概念资金流", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "概念资金流无数据", "新浪"
    框 = df.copy()
    for 列 in ["行业指数", "行业-涨跌幅", "流入资金", "流出资金", "净额", "公司家数", "领涨股-涨跌幅", "当前价"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    if "净额" in 框.columns:
        框 = 框.sort_values("净额", ascending=False, na_position="last")
    框 = 框.reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "新浪"


def 行业资金流() -> tuple:
    """新浪行业板块资金流。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    缓存键 = "行业资金流"
    命中 = 缓存.取(缓存键, config.缓存时长["资金流"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_fund_flow_industry, symbol="即时",
                    说明="行业资金流", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "行业资金流无数据", "新浪"
    框 = df.copy()
    for 列 in 框.columns:
        if 框[列].dtype == object and 列 not in ("行业", "领涨股"):
            try:
                框[列] = 框[列].map(数值)
            except Exception:
                pass
    缓存.存(缓存键, 框)
    return 框, "", "新浪"


def 北向概览() -> tuple:
    """北向资金当日概览（东财）。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "北向概览"
    命中 = 缓存.取(缓存键, config.缓存时长["北向两融"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_hsgt_fund_flow_summary_em, 说明="北向概览")
    if df is None or len(df) == 0:
        return None, 错 or "北向概览无数据", "东方财富"
    框 = df.copy()
    for 列 in ["成交净买额", "资金净流入", "当日资金余额", "上涨数", "持平数", "下跌数", "指数涨跌幅"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 北向历史(天数: int = 250) -> tuple:
    """北向资金历史（东财）。
    注意：2024-08 之后日度净买入停止披露，近期数值多为 NaN，页面必须提示。
    返回 (DataFrame, 错误, 来源)。
    """
    缓存键 = "北向历史"
    命中 = 缓存.取(缓存键, config.缓存时长["北向两融"])
    if 命中 is not None:
        return 命中.tail(天数).reset_index(drop=True), "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_hsgt_hist_em, symbol="北向资金", 说明="北向历史")
    if df is None or len(df) == 0:
        return None, 错 or "北向历史无数据", "东方财富"
    框 = df.copy()
    日期列 = "日期" if "日期" in 框.columns else 框.columns[0]
    框[日期列] = 框[日期列].map(规范日期)
    框 = 框.sort_values(日期列).reset_index(drop=True)
    缓存.存(缓存键, 框)
    提示 = ""
    if "当日成交净买额" in 框.columns:
        近5 = 框["当日成交净买额"].tail(5)
        if 近5.isna().all():
            提示 = "近 5 个交易日数值为空：北向日度净买入自 2024 年 8 月起停止披露，仅可作历史回顾。"
    return 框.tail(天数).reset_index(drop=True), 提示, "东方财富"


def 两融沪市(天数: int = 60) -> tuple:
    """上交所融资融券汇总。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    结束 = 北京时间().strftime("%Y%m%d")
    开始 = (北京时间() - pd.Timedelta(days=天数 * 2)).strftime("%Y%m%d")
    缓存键 = "两融沪市_%s" % 结束
    命中 = 缓存.取(缓存键, config.缓存时长["北向两融"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_margin_sse, start_date=开始, end_date=结束, 说明="沪市两融")
    if df is None or len(df) == 0:
        return None, 错 or "沪市两融无数据", "上交所"
    框 = df.copy()
    if "信用交易日期" in 框.columns:
        框["日期"] = 框["信用交易日期"].astype(str).map(规范日期)
    框 = 框.tail(天数).reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "上交所"


def 两融深市(日期: str = "") -> tuple:
    """深交所融资融券汇总（单日）。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    目标 = 紧凑日期(日期) if 日期 else 紧凑日期(规范日期(北京时间().strftime("%Y-%m-%d")))
    缓存键 = "两融深市_%s" % 目标
    命中 = 缓存.取(缓存键, config.缓存时长["北向两融"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.stock_margin_szse, date=目标, 说明="深市两融")
    if df is None or len(df) == 0:
        return None, 错 or "深市两融无数据（该日可能非交易日）", "深交所"
    缓存.存(缓存键, df)
    return df, "", "深交所"


def 两融账户历史() -> tuple:
    """两融账户与余额历史（3417 行）。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "两融账户历史"
    命中 = 缓存.取(缓存键, config.缓存时长["北向两融"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_margin_account_info, 说明="两融账户历史")
    if df is None or len(df) == 0:
        return None, 错 or "两融账户历史无数据", "东方财富"
    框 = df.copy()
    if "日期" in 框.columns:
        框["日期"] = 框["日期"].map(规范日期)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 东财个股资金流明细(页大小: int = 100) -> tuple:
    """东方财富数据中心：个股当日资金流明细（实测可用）。
    返回 (DataFrame, 错误, 来源)。
    """
    缓存键 = "东财个股资金流"
    命中 = 缓存.取(缓存键, config.缓存时长["资金流"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    数据, 错 = 东财数据中心("RPT_DMSK_TS_STOCKNEW", 每页=页大小, 排序="NET_INFLOW")
    if 数据 is None or len(数据) == 0:
        return None, 错 or "东财个股资金流无数据", "东方财富数据中心"
    框 = pd.DataFrame(数据)
    改名 = {
        "SECURITY_CODE": "股票代码", "SECURITY_NAME_ABBR": "股票简称",
        "TRADE_DATE": "交易日期", "CLOSE_PRICE": "最新价",
        "CHANGE_RATE": "涨跌幅", "SUPERDEAL_INFLOW": "超大单流入",
        "SUPERDEAL_OUTFLOW": "超大单流出", "PRIME_INFLOW": "主力流入",
    }
    框 = 框.rename(columns={k: v for k, v in 改名.items() if k in 框.columns})
    if "交易日期" in 框.columns:
        框["交易日期"] = 框["交易日期"].astype(str).str.slice(0, 10)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富数据中心"


def 资金流概览() -> tuple:
    """资金面模块顶部汇总卡片用。返回 (dict, 错误列表)。"""
    结果 = {}
    错误 = []
    for 键, 函数 in (("个股", 个股资金流), ("概念", 概念资金流), ("行业", 行业资金流)):
        try:
            df, 错, _ = 函数()
            if df is None or len(df) == 0:
                错误.append("%s资金流：%s" % (键, 错))
                continue
            净额列 = "净额" if "净额" in df.columns else None
            if 净额列:
                有效 = df[净额列].dropna()
                结果[键] = {
                    "条数": len(df),
                    "净流入家数": int((有效 > 0).sum()),
                    "净流出家数": int((有效 < 0).sum()),
                    "净额合计": float(有效.sum()),
                }
            else:
                结果[键] = {"条数": len(df)}
        except Exception as e:
            错误.append("%s资金流异常：%s" % (键, str(e)[:80]))
    return 结果, 错误