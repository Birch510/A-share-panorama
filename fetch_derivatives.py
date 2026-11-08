# -*- coding: utf-8 -*-
"""
fetch_derivatives.py —— 衍生品与固收模块取数

实测可用接口（2026-10-30，akshare 1.18.96）：
    futures_main_sina(symbol='V0', start_date, end_date)  4227 行 主力连续合约日线
    futures_zh_realtime(symbol='螺纹钢')                   13 行  期货实时行情
    fund_etf_fund_daily_em()                             1690 行 ETF 净值（元数据型）
    bond_zh_hs_cov_spot()                                 327 行 可转债实时

注意：
    futures_zh_realtime 的 symbol 用中文品种名（螺纹钢/沪铜/黄金…），
    不是合约代码；bond_zh_hs_cov_spot 的数值列是字符串 '0.000'，要转数字。
"""

import pandas as pd

import config
from data_fetcher import 缓存, 重试请求, 数值, 规范日期, 北京时间, 有AK, ak, _无AK错误

# 主力连续合约代码：V0 PVC / RB0 螺纹钢 / CU0 沪铜 / AU0 沪金 / IF0 沪深300股指
主力合约 = {
    "螺纹钢主连": "RB0",
    "沪铜主连": "CU0",
    "沪金主连": "AU0",
    "PVC主连": "V0",
    "沪深300股指主连": "IF0",
}

# 期货实时行情的品种中文名
实时品种 = ["螺纹钢", "沪铜", "沪金", "铁矿石", "豆粕", "原油"]


def 期货主力日线(合约代码: str = "V0", 天数: int = 500) -> tuple:
    """主力连续合约日线。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    结束 = 北京时间().strftime("%Y%m%d")
    起始 = (北京时间() - pd.Timedelta(days=int(天数 * 1.6))).strftime("%Y%m%d")
    缓存键 = "期货日线_%s_%s" % (合约代码, 结束)
    命中 = 缓存.取(缓存键, config.缓存时长["日K"])
    if 命中 is not None:
        return 命中.tail(天数).reset_index(drop=True), "", "内存缓存"
    df, 错 = 重试请求(ak.futures_main_sina, symbol=合约代码,
                    start_date=起始, end_date=结束, 说明="期货主力日线", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or ("合约 %s 无日线数据" % 合约代码), "新浪"
    框 = df.copy()
    if "日期" in 框.columns:
        框["日期"] = 框["日期"].map(规范日期)
        框 = 框.sort_values("日期").reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框.tail(天数).reset_index(drop=True), "", "新浪"


def 期货实时(品种: str = "螺纹钢") -> tuple:
    """单个期货品种实时行情。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    缓存键 = "期货实时_%s" % 品种
    命中 = 缓存.取(缓存键, config.缓存时长["衍生品"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.futures_zh_realtime, symbol=品种, 说明="期货实时", 次数=1)
    if df is None or len(df) == 0:
        return None, 错 or ("品种 %s 无实时行情" % 品种), "新浪"
    缓存.存(缓存键, df)
    return df, "", "新浪"


def 期货实时总表(品种列表=None) -> tuple:
    """多个品种实时行情合并。返回 (DataFrame, 错误列表, 来源)。"""
    列表 = 品种列表 or 实时品种
    错误 = []
    片段 = []
    for 品种 in 列表:
        try:
            df, 错, _ = 期货实时(品种)
            if df is None or len(df) == 0:
                错误.append("%s：%s" % (品种, 错))
                continue
            框 = df.copy()
            框.insert(0, "品种", 品种)
            片段.append(框)
        except Exception as e:
            错误.append("%s异常：%s" % (品种, str(e)[:50]))
    if not 片段:
        return None, 错误 or ["期货实时全部失败"], "新浪"
    return pd.concat(片段, ignore_index=True), 错误, "新浪"


def ETF净值() -> tuple:
    """ETF 每日净值（东财）。返回 (DataFrame, 错误, 来源)。
    注意：列名带日期（如 2026-10-29-单位净值），是宽表元数据。
    """
    if not 有AK:
        return None, _无AK错误(), "无"
    缓存键 = "ETF净值"
    命中 = 缓存.取(缓存键, config.缓存时长["估值指标"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.fund_etf_fund_daily_em, 说明="ETF净值", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "ETF净值无数据", "东方财富"
    缓存.存(缓存键, df)
    return df, "", "东方财富"


def 可转债实时() -> tuple:
    """沪深可转债实时行情。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    缓存键 = "可转债实时"
    命中 = 缓存.取(缓存键, config.缓存时长["衍生品"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    df, 错 = 重试请求(ak.bond_zh_hs_cov_spot, 说明="可转债实时", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "可转债实时无数据", "新浪"
    框 = df.copy()
    for 列 in ["trade", "pricechange", "changepercent", "buy", "sell",
               "settlement", "open", "high", "low", "volume", "amount"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    改名 = {"symbol": "代码", "name": "名称", "trade": "最新价",
            "changepercent": "涨跌幅", "volume": "成交量", "amount": "成交额",
            "open": "今开", "high": "最高", "low": "最低", "settlement": "昨收"}
    框 = 框.rename(columns={k: v for k, v in 改名.items() if k in 框.columns})
    if "涨跌幅" in 框.columns:
        框 = 框.sort_values("涨跌幅", ascending=False, na_position="last").reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "新浪"


def 衍生品概览() -> tuple:
    """衍生品模块顶部卡片。返回 (dict, 错误列表)。"""
    结果 = {}
    错误 = []
    try:
        df, 错, _ = 期货实时总表()
        if df is not None and len(df):
            结果["期货品种数"] = len(df)
            if "changepercent" in df.columns:
                有效 = df["changepercent"].dropna()
                结果["上涨品种"] = int((有效 > 0).sum())
                结果["下跌品种"] = int((有效 < 0).sum())
        elif 错:
            错误.extend(错)
    except Exception as e:
        错误.append("期货实时异常：%s" % str(e)[:60])
    try:
        df, 错, _ = 可转债实时()
        if df is not None and len(df):
            结果["可转债数量"] = len(df)
        elif 错:
            错误.append("可转债：%s" % 错)
    except Exception as e:
        错误.append("可转债异常：%s" % str(e)[:60])
    return 结果, 错误