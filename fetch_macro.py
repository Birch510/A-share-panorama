# -*- coding: utf-8 -*-
"""
fetch_macro.py —— 宏观数据模块取数

实测可用接口（2026-10-30，akshare 1.18.96）：
    macro_china_pmi()            225 行  制造业/非制造业 PMI
    macro_china_cpi()            225 行  居民消费价格指数
    macro_china_ppi()            249 行  工业生产者出厂价格指数
    macro_china_money_supply()   225 行  M0/M1/M2 货币供应
    macro_china_shrzgm()         136 行  社会融资规模增量
    bond_zh_us_rate(start_date)  484 行  中美国债收益率曲线

说明：
    宏观数据是月度频率，缓存 6 小时即可；
    「月份」列是「2026年09月份」这种中文字符串，需要单独解析成日期排序，
    不能直接当字符串排序（"2026年10月份" < "2026年9月份" 会排错）。
"""

import re

import pandas as pd

import config
from data_fetcher import 缓存, 重试请求, 数值, 规范日期, 有AK, ak, _无AK错误


def _解析月份(值) -> str:
    """把「2026年09月份」「202609」「201501」统一解析成 YYYY-MM-01。"""
    s = str(值).strip()
    匹配 = re.search(r"(\d{4})\D+(\d{1,2})", s)
    if 匹配:
        return "%s-%02d-01" % (匹配.group(1), int(匹配.group(2)))
    匹配 = re.search(r"^(\d{4})(\d{2})$", s)
    if 匹配:
        return "%s-%s-01" % (匹配.group(1), 匹配.group(2))
    return s


def _按月接口(函数名: str, 说明: str, 月份列: str = "月份") -> tuple:
    缓存键 = "宏观_%s" % 说明
    命中 = 缓存.取(缓存键, config.缓存时长["宏观"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    函数 = getattr(ak, 函数名, None)
    if 函数 is None:
        return None, "当前 akshare 版本没有接口 %s" % 函数名, "无"
    df, 错 = 重试请求(函数, 说明=说明, 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or ("%s无数据" % 说明), "国家统计局"
    框 = df.copy()
    if 月份列 in 框.columns:
        框["日期"] = 框[月份列].map(_解析月份)
        框 = 框.sort_values("日期").reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "国家统计局"


def PMI() -> tuple:
    """制造业与非制造业 PMI。返回 (DataFrame, 错误, 来源)。"""
    return _按月接口("macro_china_pmi", "PMI")


def CPI() -> tuple:
    """居民消费价格指数。返回 (DataFrame, 错误, 来源)。"""
    return _按月接口("macro_china_cpi", "CPI")


def PPI() -> tuple:
    """工业生产者出厂价格指数。返回 (DataFrame, 错误, 来源)。"""
    return _按月接口("macro_china_ppi", "PPI")


def 货币供应() -> tuple:
    """M0/M1/M2 货币供应量。返回 (DataFrame, 错误, 来源)。"""
    return _按月接口("macro_china_money_supply", "货币供应")


def 社会融资() -> tuple:
    """社会融资规模增量。返回 (DataFrame, 错误, 来源)。"""
    return _按月接口("macro_china_shrzgm", "社会融资")


def 国债收益率(开始日期: str = "") -> tuple:
    """中美国债收益率曲线（日频）。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "宏观_国债收益率"
    命中 = 缓存.取(缓存键, config.缓存时长["宏观"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    起始 = 开始日期 or (pd.Timestamp.now() - pd.Timedelta(days=365 * 3)).strftime("%Y%m%d")
    df, 错 = 重试请求(ak.bond_zh_us_rate, start_date=起始, 说明="国债收益率", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "国债收益率无数据", "东方财富"
    框 = df.copy()
    if "日期" in 框.columns:
        框["日期"] = 框["日期"].map(规范日期)
        框 = 框.sort_values("日期").reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "东方财富"


def 宏观概览() -> tuple:
    """宏观模块顶部卡片：每个指标取最新一期。返回 (dict, 错误列表)。"""
    结果 = {}
    错误 = []
    for 名称, 函数 in (("PMI", PMI), ("CPI", CPI), ("PPI", PPI), ("社融", 社会融资)):
        try:
            df, 错, _ = 函数()
            if df is None or len(df) == 0:
                错误.append("%s：%s" % (名称, 错))
                continue
            尾 = df.iloc[-1]
            项 = {"日期": 尾.get("日期", "")}
            for 列 in df.columns:
                if 列 in ("日期", "月份"):
                    continue
                if 列.startswith("制造业-指数") or 列 in ("全国-当月", "当月", "当月同比增长",
                                                         "社会融资规模增量", "制造业-同比增长"):
                    项[列] = 数值(尾.get(列))
            结果[名称] = 项
        except Exception as e:
            错误.append("%s异常：%s" % (名称, str(e)[:60]))
    return 结果, 错误