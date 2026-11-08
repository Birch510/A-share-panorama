# -*- coding: utf-8 -*-
"""
fetch_valuation.py —— 估值水平模块取数

实测结论（2026-10-30，akshare 1.18.96，本机网络环境）：

    已确认不可用，全部弃用：
        1. 乐咕乐股 legulegu 整站 504 —— stock_index_pe_lg / stock_a_ttm_lyr /
           stock_a_all_pb / stock_market_pe_lg / stock_market_pb_lg 全挂。
        2. 中证指数官网 oss-ch.csindex.com.cn —— 静态文件一律返回 403 拦截页，
           stock_zh_index_value_csindex（指数估值）与 index_stock_cons_csindex
           （指数成分股）都走这个域名，整条中证通道不可用。
        3. 申万 sw_index_first_info / second_info / third_info —— 本机被限流，
           连续 15 次调用全部报 AttributeError: 'NoneType' object has no attribute
           'find_all'，不能作为估值主通道。

    实测可用（当前唯一稳定的行业估值来源）：
        东方财富数据中心报表 RPT_VALUEINDUSTRY_DET
        一次返回 127 个申万二级行业的当日估值：
            [BOARD_NAME 行业名 / BOARD_CODE / TRADE_DATE / PE_TTM / PE_LAR /
             PB_MRQ / PCF_OCF_TTM / PS_TTM / PEG_CAR / TOTAL_MARKET_CAP / NUM / LOSS_COUNT]
        0.7 秒返回，走 datacenter-web.eastmoney.com（本机可通）。
        行业名与 config.重点板块 的「申万板块」字段完全对得上
        （半导体 / 通信设备 / 软件开发 / 光伏设备 / 电网设备 / IT服务Ⅱ /
          航天装备Ⅱ / 小金属 / 能源金属 / 贵金属 / 电池 …）。

    个股估值：ak.stock_value_em(symbol='600111') ——》2139 行八年历史，
        列 [数据日期/当日收盘价/总市值/流通市值/PE(TTM)/PE(静)/市净率/PEG值/
            市现率/市销率]，同样走 datacenter，稳定。

    巨潮资讯 stock_industry_pe_ratio_cninfo ——》证监会行业口径静态市盈率，
        仅作交叉参考。
"""

import pandas as pd

import config
from data_fetcher import (缓存, 重试请求, 规范日期, 有AK, ak, _无AK错误,
                          东财数据中心)

# 东财行业估值报表名
行业估值报表 = "RPT_VALUEINDUSTRY_DET"

# 申万层级 → 接口名（仅作补充通道，限流时自动跳过）
申万层级接口 = {
    "一级行业": "sw_index_first_info",
    "二级行业": "sw_index_second_info",
    "三级行业": "sw_index_third_info",
}

# 13 个重点板块在行业估值表里找不到同名行业时的近似口径
近似口径 = {
    "稀土永磁": ["小金属", "能源金属", "贵金属"],
    "有色金属": ["工业金属", "贵金属", "小金属", "能源金属", "金属新材料"],
    "电子": ["半导体", "元件", "光学光电子", "消费电子", "电子化学品Ⅱ", "其他电子Ⅱ"],
    "新能源": ["光伏设备", "风电设备", "电池"],
    "稀有金属": ["小金属", "能源金属", "贵金属"],
    "人工智能": ["软件开发", "IT服务Ⅱ", "计算机设备"],
    "通讯/通信": ["通信设备", "通信服务"],
}


def _数(值):
    try:
        v = float(值)
        return None if v != v else v
    except Exception:
        return None


# ============================ 一、行业估值全表 ============================

def 行业估值表(日期: str = "") -> tuple:
    """东财 127 个申万二级行业的估值表。返回 (DataFrame, 错误, 来源)。

    日期留空则取最近一个交易日。
    """
    缓存键 = "行业估值表_%s" % (日期 or "最新")
    命中 = 缓存.取(缓存键, config.缓存时长["行业估值"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    过滤 = "(TRADE_DATE='%s')" % 日期 if 日期 else ""
    记录, 错 = 东财数据中心(行业估值报表, 每页=500, 过滤=过滤,
                            排序="-TRADE_DATE")
    if not 记录:
        return None, 错 or "东财行业估值没有返回数据", "东财数据中心"

    框 = pd.DataFrame(记录)
    # 只要最近一个交易日，避免混入历史
    if "TRADE_DATE" in 框.columns:
        框["TRADE_DATE"] = 框["TRADE_DATE"].map(lambda x: str(x)[:10])
        最近 = 框["TRADE_DATE"].max()
        框 = 框[框["TRADE_DATE"] == 最近].copy()
        框 = 框.rename(columns={"TRADE_DATE": "日期"})

    重命名 = {
        "BOARD_NAME": "行业名称",
        "BOARD_CODE": "行业代码",
        "PE_TTM": "滚动市盈率",
        "PE_LAR": "静态市盈率",
        "PB_MRQ": "市净率",
        "PS_TTM": "市销率",
        "PCF_OCF_TTM": "市现率",
        "PEG_CAR": "PEG",
        "TOTAL_MARKET_CAP": "总市值",
        "NUM": "成份个数",
        "LOSS_COUNT": "亏损家数",
    }
    框 = 框.rename(columns={k: v for k, v in 重命名.items() if k in 框.columns})
    for 列 in ["滚动市盈率", "静态市盈率", "市净率", "市销率", "市现率",
              "PEG", "总市值", "成份个数", "亏损家数"]:
        if 列 in 框.columns:
            框[列] = pd.to_numeric(框[列], errors="coerce")
    if "总市值" in 框.columns:
        框["总市值(亿)"] = (框["总市值"] / 1e8).round(2)
        框 = 框.drop(columns=["总市值"])

    保留 = [c for c in ["行业代码", "行业名称", "日期", "滚动市盈率", "静态市盈率",
                        "市净率", "市销率", "市现率", "PEG", "总市值(亿)",
                        "成份个数", "亏损家数"] if c in 框.columns]
    框 = 框[保留].sort_values("滚动市盈率", ascending=True).reset_index(drop=True)

    缓存.存(缓存键, 框)
    return 框, "", "东财数据中心"


def 申万行业估值(层级: str = "二级行业") -> tuple:
    """保留旧接口名做兼容：现在统一走东财行业估值表。

    东财该报表的口径就是申万二级行业，所以「一级 / 三级」用本地库的
    行业名去汇总（一级按上级行业合并、三级无法直接映射时退化为二级）。
    """
    框, 错, 源 = 行业估值表()
    if 框 is None:
        return None, 错, 源
    if 层级 in ("二级行业", "二级"):
        return 框, "", 源
    if 层级 in ("一级行业", "一级"):
        # 用本地申万二级库里的「上级行业」把二级行业汇总成一级
        return _汇总一级(框)
    return 框, "东财行业估值只提供二级行业口径，三级行业请参考二级近似", 源


def _汇总一级(框):
    """把二级行业按上级行业加权汇总。返回 (DataFrame, 错误, 来源)。"""
    库 = None
    try:
        from data_fetcher import 读本地JSON
        库 = 读本地JSON(config.申万行业文件, None)
    except Exception:
        库 = None

    上级 = {}
    if isinstance(库, dict):
        for 项 in (库.get("板块列表") or []):
            if str(项.get("层级") or "") == "二级行业":
                上级[str(项.get("名称") or "")] = str(项.get("上级行业") or "")
    if not 上级:
        # 本地库缺失时，退化：直接用二级表，只是标记口径
        return 框, "本地申万行业库缺失，已按二级行业口径展示", "东财数据中心"

    框 = 框.copy()
    框["上级行业"] = 框["行业名称"].map(lambda x: 上级.get(str(x), ""))
    有效 = 框[框["上级行业"] != ""]
    if len(有效) == 0:
        return 框, "申万上级行业映射为空", "东财数据中心"

    聚合 = []
    for 名, 组 in 有效.groupby("上级行业"):
        权 = pd.to_numeric(组.get("成份个数"), errors="coerce").fillna(1.0)

        def 加权(列):
            v = pd.to_numeric(组.get(列), errors="coerce")
            有效值 = v.notna() & (权 > 0)
            if not 有效值.any():
                return None
            return round(float((v[有效值] * 权[有效值]).sum() / 权[有效值].sum()), 2)

        聚合.append({
            "行业名称": 名,
            "滚动市盈率": 加权("滚动市盈率"),
            "静态市盈率": 加权("静态市盈率"),
            "市净率": 加权("市净率"),
            "市销率": 加权("市销率"),
            "成份个数": int(权.sum()),
            "下级行业数": len(组),
        })
    结果 = pd.DataFrame(聚合).sort_values("滚动市盈率", ascending=True).reset_index(drop=True)
    return 结果, "", "东财数据中心（按申万一级汇总）"


# ============================ 二、重点板块估值 ============================

def 板块估值一览() -> tuple:
    """13 个重点板块的估值汇总。返回 (DataFrame, 错误列表, 来源)。

    做法：拿东财 127 个申万二级行业估值表，按每个板块在 config 里登记的
    「申万板块」名称逐一匹配；匹配不到就用「近似口径」里的行业组合，
    再按各行业成份个数加权平均。
    """
    框, 错, 源 = 行业估值表()
    if 框 is None or len(框) == 0:
        return None, [错 or "行业估值表为空"], 源

    名称到行 = {}
    for _, 行 in 框.iterrows():
        名称到行[str(行.get("行业名称") or "").strip()] = 行

    错误 = []
    行表 = []
    for 项 in config.重点板块:
        显示名 = 项.get("显示名", "")
        候选 = []
        for 段 in 项.get("申万板块") or []:
            名 = str(段.get("名称") or "").strip()
            if 名:
                候选.append(名)
        候选.extend(近似口径.get(显示名, []))

        命中 = []
        用过 = set()
        for 名 in 候选:
            if 名 in 用过:
                continue
            用过.add(名)
            if 名 in 名称到行:
                命中.append(名称到行[名])
        if not 命中:
            错误.append("%s：申万行业「%s」在估值表里都没有" % (显示名, "、".join(候选[:3])))
            continue

        权重 = []
        for 行 in 命中:
            w = _数(行.get("成份个数"))
            权重.append(w if w and w > 0 else 1.0)

        def 加权(列):
            数 = []
            权 = []
            for 行, w in zip(命中, 权重):
                v = _数(行.get(列))
                if v is not None:
                    数.append(v)
                    权.append(w)
            s = sum(权)
            return round(sum(v * w for v, w in zip(数, 权)) / s, 2) if s else None

        行表.append({
            "板块": 显示名,
            "滚动市盈率": 加权("滚动市盈率"),
            "静态市盈率": 加权("静态市盈率"),
            "市净率": 加权("市净率"),
            "市销率": 加权("市销率"),
            "成份个数": int(sum(权重)),
            "对应行业": "、".join(str(r.get("行业名称")) for r in 命中),
        })

    if not 行表:
        return None, 错误 or ["13 个重点板块都没匹配到行业估值"], 源
    结果 = pd.DataFrame(行表).sort_values("滚动市盈率", ascending=True).reset_index(drop=True)
    return 结果, 错误, 源


# ============================ 三、个股估值 ============================

def 个股估值(代码: str = "600111", 天数: int = 500) -> tuple:
    """单只股票的估值历史（东财数据中心）。返回 (DataFrame, 错误, 来源)。"""
    if not 有AK:
        return None, _无AK错误(), "无"
    代码 = str(代码).strip()
    if not 代码.isdigit() or len(代码) != 6:
        return None, "股票代码必须是 6 位数字：%s" % 代码, "无"

    缓存键 = "个股估值_%s_%s" % (代码, 天数)
    命中 = 缓存.取(缓存键, config.缓存时长["估值指标"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    df, 错 = 重试请求(ak.stock_value_em, symbol=代码,
                    说明="%s估值" % 代码, 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or ("%s 没有估值数据" % 代码), "东财数据中心"

    框 = df.copy()
    if "数据日期" in 框.columns:
        框["数据日期"] = 框["数据日期"].map(规范日期)
        框 = 框.sort_values("数据日期").reset_index(drop=True)
    for 列 in ["当日收盘价", "PE(TTM)", "PE(静)", "市净率", "PEG值",
              "市现率", "市销率"]:
        if 列 in 框.columns:
            框[列] = pd.to_numeric(框[列], errors="coerce")
    框 = 框.rename(columns={"数据日期": "日期", "PE(TTM)": "市盈率(TTM)",
                            "PE(静)": "市盈率(静态)"})
    if 天数 and len(框) > 天数:
        框 = 框.tail(天数).reset_index(drop=True)

    缓存.存(缓存键, 框)
    return 框, "", "东财数据中心"


# ============================ 四、证监会行业市盈率（交叉参考） ============================

def 证监会行业估值(报告期: str = "") -> tuple:
    """巨潮资讯披露的证监会行业静态市盈率。返回 (DataFrame, 错误, 来源)。

    注意：该接口必须传具体报告期，留空会用默认值 20210910，
    那一期巨潮只返回空表（pandas 抛 Length mismatch），实测必挂。
    因此这里自动往前找最近的报告期（3/31、6/30、9/30、12/31）。
    """
    if not 有AK:
        return None, _无AK错误(), "无"

    缓存键 = "证监会行业估值_%s" % (报告期 or "自动")
    命中 = 缓存.取(缓存键, config.缓存时长["行业估值"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    候选 = [报告期] if 报告期 else _最近报告期列表()
    错误 = []
    for 期 in 候选:
        df, 错 = 重试请求(ak.stock_industry_pe_ratio_cninfo,
                         说明="证监会行业市盈率 %s" % 期, 次数=2,
                         symbol="证监会行业分类", date=str(期))
        if df is not None and len(df):
            框 = df.copy()
            for 列 in ["总市值-静态", "净利润-静态", "静态市盈率-加权平均",
                      "静态市盈率-中位数", "静态市盈率-算术平均", "公司数量"]:
                if 列 in 框.columns:
                    框[列] = pd.to_numeric(框[列], errors="coerce")
            框 = 框.sort_values("静态市盈率-加权平均",
                               ascending=True).reset_index(drop=True)
            缓存.存(缓存键, 框)
            return 框, "", "巨潮资讯（%s）" % 期
        错误.append("%s：%s" % (期, (错 or "空表")[:50]))

    return None, "；".join(错误[-2:]) or "证监会行业市盈率无数据", "巨潮资讯"


def _最近报告期列表(个数: int = 6) -> list:
    """从今天往前列出最近的季度末报告期（YYYYMMDD）。"""
    import datetime as _dt

    今天 = _dt.date.today()
    结果 = []
    年, 季 = 今天.year, (今天.month - 1) // 3
    for _ in range(个数):
        月日 = ["0331", "0630", "0930", "1231"][季]
        结果.append("%d%s" % (年, 月日))
        季 -= 1
        if 季 < 0:
            季 = 3
            年 -= 1
    return 结果


# ============================ 五、概览 ============================

def 估值概览() -> tuple:
    """估值模块顶部卡片。返回 (dict, 错误列表)。"""
    结果 = {}
    错误 = []
    try:
        表, 错, _ = 板块估值一览()
        if 表 is not None and len(表):
            有效 = 表.dropna(subset=["滚动市盈率"])
            结果["覆盖板块数"] = len(表)
            if len(有效):
                最低 = 有效.loc[有效["滚动市盈率"].idxmin()]
                最高 = 有效.loc[有效["滚动市盈率"].idxmax()]
                结果["最便宜板块"] = "%s（%s 倍）" % (最低["板块"], 最低["滚动市盈率"])
                结果["最贵板块"] = "%s（%s 倍）" % (最高["板块"], 最高["滚动市盈率"])
                结果["中位市盈率"] = "%.2f 倍" % 有效["滚动市盈率"].median()
        elif 错:
            错误.extend(错[:3])
    except Exception as e:
        错误.append("板块估值汇总异常：%s" % str(e)[:60])
    return 结果, 错误