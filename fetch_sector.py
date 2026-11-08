# -*- coding: utf-8 -*-
"""
data_fetcher.py 第二部分：板块体系与成分股

板块来源与实测结论（2026-10-30）：
    行业板块   → 申万三级体系（一级 31 / 二级 131 / 三级 335），本地离线库
                 接口：sw_index_first_info / sw_index_second_info / sw_index_third_info
    概念板块   → 中证指数（index_csindex_all，2388 个指数，可筛主题）+ 同花顺概念（375 个）
    地域板块   → 巨潮资讯注册地离线库（build_region.py 生成），无则降级为提示

成分股：
    行业  → sw_index_third_cons(symbol='801081.SI')，离线建库，1.2 秒/个
    概念  → index_stock_cons_csindex(symbol='930851')，在线拉，0.8 秒/个
    地域  → stock_profile_cninfo 的注册地址聚类，离线建库
"""

import io
import json
import os
import time

import pandas as pd

import config
from data_fetcher import (
    缓存, 重试请求, 规范股票代码, 规范日期, 数值, 读本地JSON, 写本地JSON,
    有AK, ak, _无AK错误, 北京时间, 全市场快照,
)


# ============================================================ 二、离线板块库 ====
# build_sector.py 的产物：一份「板块 → 成分股」映射，来源为新浪股票分类接口。
# 这是本项目最可靠的板块通道（实测：申万官网间歇失败、中证返回 403 拦截页、
# 东财 clist 路径被确定性阻断，只有新浪分类稳定）。

板块库文件 = {
    "申万一级": "板块_申万一级.json",
    "申万二级": "板块_申万二级.json",
    "申万三级": "板块_申万三级.json",
    "热门概念": "板块_热门概念.json",
    "概念板块": "板块_概念板块.json",
    "地域板块": "板块_地域板块.json",
    "证监会行业": "板块_证监会行业.json",
    "新浪行业": "板块_新浪行业.json",
    "分类": "板块_市场分类.json",
}


def 读板块库(分类: str):
    """读 build_sector.py 生成的离线板块库，没有则返回 None。"""
    return 读本地JSON(os.path.join(config.数据目录, 板块库文件[分类]), None)


def _板块库成分(分类: str, 名称: str):
    """按板块名称从离线库取成分股，返回 DataFrame 或 None。

    离线库里「总市值」的单位是万元（创达新材 226416.09 万 = 22.64 亿），
    直接显示会被格式化成「22.64 万」，差了一万倍。这里统一换成元，
    下游的表格格式化就会正确显示成「22.64 亿」。
    """
    if not 名称:
        return None
    库 = 读板块库(分类)
    if not 库:
        return None
    股票 = (库.get("成分股") or {}).get(str(名称).strip())
    if not 股票:
        return None
    框 = pd.DataFrame(股票)
    if len(框) == 0:
        return None
    if "总市值" in 框.columns:
        框["总市值"] = pd.to_numeric(框["总市值"], errors="coerce") * 10000.0
    框["所属板块"] = str(名称).strip()
    return 框


def _板块库列表(分类: str) -> list:
    """把离线库的板块清单转成列表，无库返回空列表。"""
    库 = 读板块库(分类)
    if not 库:
        return []
    return list(库.get("板块列表") or [])


def _板块库时间(分类: str) -> str:
    """离线库的抓取时间（用于界面溯源）。"""
    库 = 读板块库(分类)
    return (库 or {}).get("抓取时间", "")


# ============================================================ 三、板块体系 ====

def 行业板块列表(层级: str = "") -> tuple:
    """行业板块列表。优先用 build_sector.py 的离线库，其次申万离线库。
    返回 (DataFrame, 错误, 来源)。

    层级留空返回三级全部（一级 31 / 二级 129 / 三级 332 混在一起，共 492 行）；
    传「一级行业」这类具体层级就只返回那一层。
    """
    缓存键 = "行业板块列表|%s" % (层级 or "全部")
    命中 = 缓存.取(缓存键, config.缓存时长["板块列表"])
    if 命中 is not None:
        return 命中, "", "本地离线库"

    错误列表 = []

    # ---- 通道一：build_sector.py 生成的离线板块库（最可靠）----
    记录 = []
    循环 = [(层级, 行业层级.get(层级, ""))] if 层级 in 行业层级 else [
        ("一级行业", "申万一级"), ("二级行业", "申万二级"), ("三级行业", "申万三级")]
    for 层名, 分类 in 循环:
        清单 = _板块库列表(分类)
        if not 清单:
            continue
        for 项 in 清单:
            记录.append({
                "板块代码": 项.get("名称", ""),   # 离线库以名称为主键
                "板块名称": 项.get("名称", ""),
                "层级": 层名,
                "上级": "申万",
                "成分数": 项.get("成分股数量"),
                "静态市盈率": None,
                "滚动市盈率": None,
                "市净率": None,
                "股息率": None,
            })
        if 清单:
            错误列表.append("%s 离线库抓取于 %s" % (层名, _板块库时间(分类)))

    if 记录:
        框 = pd.DataFrame(记录)
        # 若申万行业估值库存在，补充市盈率/市净率
        树 = 读本地JSON(config.申万行业文件, {}) or {}
        估值表 = {}
        for 层 in ("一级", "二级", "三级"):
            for 项 in 树.get(层, []):
                估值表[项.get("名称", "")] = 项
        if 估值表:
            for 列 in ("静态市盈率", "滚动市盈率", "市净率", "股息率"):
                框[列] = 框["板块名称"].map(
                    lambda 名: (估值表.get(名) or {}).get(列))
        缓存.存(缓存键, 框)
        return 框, "；".join(错误列表), "离线板块库（新浪分类）"

    # ---- 通道二：申万离线库（build_index.py 产物）----
    树 = 读本地JSON(config.申万行业文件)
    if not 树:
        return None, ("尚未建库。请先在项目目录执行：python build_sector.py\n"
                      "（约 1.5 分钟，建一次长期离线可用）"), "本地离线库"

    记录 = []
    层循环 = [(层级, 树.get(层级.replace("行业", ""), []))] if 层级 in 行业层级 else [
        ("一级行业", 树.get("一级", [])),
        ("二级行业", 树.get("二级", [])),
        ("三级行业", 树.get("三级", []))]
    for 层, 项列表 in 层循环:
        for 项 in 项列表:
            记录.append({
                "板块代码": 项.get("代码", ""),
                "板块名称": 项.get("名称", ""),
                "层级": 层,
                "上级": 项.get("上级", ""),
                "成分数": 项.get("成份数"),
                "静态市盈率": 项.get("静态市盈率"),
                "滚动市盈率": 项.get("滚动市盈率"),
                "市净率": 项.get("市净率"),
                "股息率": 项.get("股息率"),
            })
    框 = pd.DataFrame(记录)
    if len(框) == 0:
        return None, "本地行业库为空，请重新执行 python build_sector.py", "本地离线库"
    缓存.存(缓存键, 框)
    return 框, "", "本地离线库"


def 概念板块列表(只用本地: bool = False) -> tuple:
    """概念板块列表：离线概念库 + 中证主题指数 + 同花顺概念。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "概念板块列表"
    命中 = 缓存.取(缓存键, config.缓存时长["板块列表"])
    if 命中 is not None:
        return 命中, "", "本地缓存"

    记录 = []
    错误列表 = []

    # 1) 离线概念库（build_sector.py --类别 热门概念，最可靠）
    清单 = _板块库列表("热门概念")
    for 项 in 清单:
        名称 = 项.get("名称", "")
        if not 名称:
            continue
        记录.append({"板块代码": 名称, "板块名称": 名称,
                     "层级": "热门概念", "上级": "新浪分类",
                     "成分数": 项.get("成分股数量"), "来源": "新浪分类"})
    if 清单:
        错误列表.append("离线概念库抓取于 %s" % _板块库时间("热门概念"))

    # 2) 中证主题指数（已登记的重点指数，离线可读）
    for 码, 名 in config.中证主题指数.items():
        记录.append({"板块代码": 码, "板块名称": 名, "层级": "中证主题指数",
                     "上级": "中证指数", "成分数": None, "来源": "中证"})

    # 3) 同花顺概念板块全量（在线，失败不影响前两项）
    if 有AK and not 只用本地:
        df, 错 = 重试请求(ak.stock_board_concept_name_ths, 说明="同花顺概念板块")
        if df is not None and len(df):
            列名 = [c for c in df.columns if "name" in str(c).lower() or "名称" in str(c)]
            代码列 = [c for c in df.columns if "code" in str(c).lower() or "代码" in str(c)]
            名 = 列名[0] if 列名 else df.columns[0]
            码 = 代码列[0] if 代码列 else None
            for _, 行 in df.iterrows():
                记录.append({
                    "板块代码": str(行[码]) if 码 else "",
                    "板块名称": str(行[名]),
                    "层级": "同花顺概念",
                    "上级": "同花顺",
                    "成分数": None,
                    "来源": "同花顺",
                })
        else:
            错误列表.append("同花顺概念：" + (错 or "无数据"))

    if not 记录:
        return None, "；".join(错误列表) or "概念板块无数据", "无"

    框 = pd.DataFrame(记录).drop_duplicates(subset=["板块名称"]).reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "；".join(错误列表), "离线概念库 + 中证 + 同花顺"


def 地域板块列表() -> tuple:
    """地域板块。优先用离线地域库，其次旧的地域成分库。"""
    记录 = []
    for 项 in _板块库列表("地域板块"):
        名称 = 项.get("名称", "")
        if not 名称:
            continue
        记录.append({"板块代码": 名称, "板块名称": 名称, "层级": "省/直辖市",
                     "上级": "中国", "成分数": 项.get("成分股数量")})
    if 记录:
        return pd.DataFrame(记录), "抓取于 %s" % _板块库时间("地域板块"), "离线板块库（新浪分类）"

    数据 = 读本地JSON(config.地域成分文件)
    if not 数据:
        return None, ("尚无地域库。请执行：python build_sector.py --类别 地域板块\n"
                      "（约 20 秒，一次建库长期可用）"), "本地离线库"
    记录 = []
    for 省, 股票 in 数据.items():
        记录.append({"板块代码": 省, "板块名称": 省, "层级": "省/直辖市",
                     "上级": "中国", "成分数": len(股票)})
    if not 记录:
        return None, "地域库为空", "本地离线库"
    return pd.DataFrame(记录), "", "本地离线库"


def 板块列表(类型: str = "行业板块", 层级: str = "") -> tuple:
    """统一入口。返回 (DataFrame, 错误, 来源)。

    类型取「行业板块 / 概念板块 / 地域板块」；
    层级只在行业板块下有意义，取「一级行业 / 二级行业 / 三级行业」，留空表示全部层级。
    """
    if 类型 == "行业板块":
        return 行业板块列表(层级)
    if 类型 == "概念板块":
        return 概念板块列表()
    if 类型 == "地域板块":
        return 地域板块列表()
    return None, "未知板块类型：%s" % 类型, "无"


# ============================================================ 四、板块成分股 ====

def 行业成分股(板块代码: str, 板块名称: str = "") -> tuple:
    """行业成分股。优先用离线板块库（按名称），其次申万离线库（按代码）。
    返回 (DataFrame, 错误, 来源)。
    """
    # ---- 通道一：离线板块库（申万一级 / 二级，按名称匹配）----
    for 分类 in ("申万二级", "申万一级"):
        名 = 板块名称 or 板块代码
        框 = _板块库成分(分类, 名)
        if 框 is not None and len(框):
            return 框, "", "离线板块库（新浪分类·%s）" % 分类

    # ---- 通道二：申万离线库（build_index.py 产物，按代码匹配）----
    库 = 读本地JSON(config.申万成分股文件, {})
    if not 库:
        return None, ("本地库中没有行业「%s」。请先执行：python build_sector.py\n"
                      "（约 1.5 分钟，可建立全部行业成分股）"
                      % (板块名称 or 板块代码)), "本地离线库"
    项 = 库.get(板块代码)
    if not 项:
        return None, ("本地库中没有行业 %s。可重新执行 python build_index.py 补齐，"
                      "或执行 python build_sector.py 用更快的通道建库"
                      % (板块名称 or 板块代码)), "本地离线库"
    股票 = 项.get("股票") or []
    if not 股票:
        return None, "行业「%s」在本地库中没有任何成分股" % 项.get("名称", 板块代码), "本地离线库"
    框 = pd.DataFrame(股票)
    if len(框) == 0:
        return None, "行业「%s」成分股为空" % 项.get("名称", 板块代码), "本地离线库"
    框["所属板块"] = 项.get("名称", 板块名称 or 板块代码)
    return 框, "", "本地离线库（申万）"


def 概念成分股(指数代码: str, 指数名称: str = "") -> tuple:
    """概念成分股。查找顺序：离线概念库（按名称）→ 中证落盘库 → 中证在线。
    返回 (DataFrame, 错误, 来源)。

    为什么优先离线库：实测本机对 oss-ch.csindex.com.cn 会返回 403 拦截页，
    中证通道随时可能不可用；离线概念库来自新浪分类接口，稳定且自带行情的。
    """
    # ---- 通道一：离线概念库（按板块名称匹配）----
    名 = 指数名称 or 指数代码
    框 = _板块库成分("热门概念", 名)
    if 框 is not None and len(框):
        return 框, "", "离线概念库（新浪分类，抓取于 %s）" % _板块库时间("热门概念")

    # ---- 通道二 / 三：中证（先落盘、再在线）----
    缓存键 = "概念成分股_%s" % 指数代码
    命中 = 缓存.取(缓存键, config.缓存时长["成分股"])
    if 命中 is not None:
        return 命中, "", "内存缓存（中证）"

    落盘文件 = os.path.join(config.数据目录, "中证成分股.json")
    本地库 = 读本地JSON(落盘文件, {}) or {}
    已有 = 本地库.get(指数代码)
    if 已有 and 已有.get("股票"):
        框 = pd.DataFrame(已有["股票"])
        if len(框):
            框["所属板块"] = 指数名称 or 已有.get("名称") or 指数代码
            缓存.存(缓存键, 框)
            return 框, "", "本地落盘（中证，抓取于 %s）" % 已有.get("抓取时间", "未知")

    if not 有AK:
        return None, _无AK错误(), "中证"

    df, 错 = 重试请求(ak.index_stock_cons_csindex, symbol=指数代码,
                   说明="中证指数 %s 成分股" % 指数代码, 次数=2)
    if df is None or len(df) == 0:
        提示 = 错 or ("中证指数 %s 无成分股数据" % 指数代码)
        if "Excel file format" in str(提示) or "403" in str(提示):
            提示 = ("中证指数 %s 通道不可用（返回的是 HTML 拦截页而不是 Excel）。"
                   "这不是限流，是本机网络对该域名做了拦截。"
                   "建议改用离线概念库：python build_sector.py --类别 热门概念"
                   % 指数代码)
        return None, 提示, "中证"
    try:
        名称列 = "成分券名称" if "成分券名称" in df.columns else df.columns[-1]
        代码列 = "成分券代码" if "成分券代码" in df.columns else df.columns[-2]
        记录 = []
        for _, 行 in df.iterrows():
            记录.append({
                "代码": 规范股票代码(行[代码列]),
                "名称": str(行[名称列]),
            })
        框 = pd.DataFrame(记录)
        框 = 框[框["代码"].str.isdigit()].reset_index(drop=True)
        if len(框) == 0:
            return None, "中证指数 %s 成分股解析后为空" % 指数代码, "中证"
        框["所属板块"] = 指数名称 or 指数代码
        缓存.存(缓存键, 框)

        # 落盘，成功后即使接口限流也永久可用
        框无板块 = 框.drop(columns=["所属板块"], errors="ignore")
        本地库[指数代码] = {
            "名称": 指数名称 or 指数代码,
            "抓取时间": 北京时间(),
            "股票": 框无板块.to_dict("records"),
        }
        写本地JSON(落盘文件, 本地库)
        return 框, "", "中证指数（在线）"
    except Exception as e:
        return None, "中证成分股解析失败：%s" % str(e)[:150], "中证"


def 地域成分股(省份: str) -> tuple:
    """地域成分股。优先离线板块库，其次旧地域库。"""
    框 = _板块库成分("地域板块", 省份)
    if 框 is not None and len(框):
        return 框, "", "离线板块库（新浪分类）"

    库 = 读本地JSON(config.地域成分文件, {})
    股票 = (库 or {}).get(省份)
    if not 股票:
        return None, ("离线库里没有「%s」。请执行：python build_sector.py --类别 地域板块"
                      % 省份), "本地离线库"
    框 = pd.DataFrame(股票)
    框["所属板块"] = 省份
    return 框, "", "本地离线库（巨潮）"


def 板块成分股(板块类型: str, 板块代码: str, 板块名称: str = "") -> tuple:
    """统一入口。返回 (DataFrame, 错误, 来源)。"""
    if 板块类型 == "行业板块":
        return 行业成分股(板块代码, 板块名称)
    if 板块类型 == "概念板块":
        return 概念成分股(板块代码, 板块名称)
    if 板块类型 == "地域板块":
        return 地域成分股(板块代码 or 板块名称)
    return None, "未知板块类型：%s" % 板块类型, "无"


def 合并成分股(板块列表: list) -> tuple:
    """把多个板块的成分股合并去重（如「电子」= 5 个二级行业合并）。
    板块列表格式：[(板块类型, 板块代码, 板块名称), ...]
    """
    if not 板块列表:
        return None, "未指定板块", "无"
    全部 = []
    错误 = []
    来源 = set()
    for 类型, 代码, 名称 in 板块列表:
        df, 错, 源 = 板块成分股(类型, 代码, 名称)
        来源.add(源)
        if df is None:
            错误.append("%s：%s" % (名称 or 代码, 错))
            continue
        全部.append(df)
    if not 全部:
        return None, "；".join(错误) or "所有板块都取不到成分股", "、".join(来源)
    框 = pd.concat(全部, ignore_index=True)
    # 同一只股票出现在多个板块里时，合并「所属板块」文本
    分组 = 框.groupby("代码", as_index=False).agg({
        "名称": "first",
        "所属板块": lambda s: "、".join(sorted(set(str(x) for x in s))),
        **{c: "first" for c in 框.columns if c not in ("代码", "名称", "所属板块")},
    })
    return 分组, "；".join(错误), "、".join(sorted(来源))


# ============================================================ 五、板块汇总行情 ====

def 行业汇总() -> tuple:
    """同花顺行业板块实时汇总（90 个细分行业，带涨跌幅/资金流/领涨股）。
    返回 (DataFrame, 错误, 来源)。这是「板块红绿榜」的主数据源。
    """
    缓存键 = "同花顺行业汇总"
    命中 = 缓存.取(缓存键, config.缓存时长["资金流"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_board_industry_summary_ths, 说明="同花顺行业汇总", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "同花顺行业汇总无数据", "同花顺"
    框 = df.copy()
    for 列 in ["涨跌幅", "总成交量", "总成交额", "净流入", "上涨家数", "下跌家数",
               "均价", "领涨股-最新价", "领涨股-涨跌幅"]:
        if 列 in 框.columns:
            框[列] = 框[列].map(数值)
    if "涨跌幅" in 框.columns:
        框 = 框.sort_values("涨跌幅", ascending=False, na_position="last").reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "同花顺"


def 概念汇总() -> tuple:
    """同花顺概念板块事件汇总（50 行：概念名称/驱动事件/龙头股/成分股数量）。
    返回 (DataFrame, 错误, 来源)。
    """
    缓存键 = "同花顺概念汇总"
    命中 = 缓存.取(缓存键, config.缓存时长["板块列表"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_board_concept_summary_ths, 说明="同花顺概念汇总", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "同花顺概念汇总无数据", "同花顺"
    缓存.存(缓存键, df)
    return df, "", "同花顺"


def 重点板块成分股(显示名: str, 口径: str = "合并") -> tuple:
    """按 config.重点板块 的配置合并成分股。
    返回 (DataFrame, 错误, 来源)。

    口径参数（同一板块在两种口径下数量可能差好几倍，界面必须让用户看得见）：
        "行业" 只取申万行业分类，最精准（如半导体 189 只）
        "概念" 只取新浪概念板块，覆盖更广（如半导体+芯片概念 800+ 只）
        "合并" 两者合并去重（默认，最全）

    查找顺序（按本机实测可用性排定）：
      一、申万板块：读 build_sector.py 的离线库，按「层级 + 名称」直接取，最稳。
      二、新浪概念：读离线「热门概念 / 概念板块」库，按名称取。
          用于申万没有对应分类的板块（如「人工智能」「稀土永磁」）。
      三、中证指数：前两条全空时才尝试，本机对中证域名有拦截，仅作兜底。
    """
    项 = config.重点板块字典.get(显示名)
    if not 项:
        return None, "未在 config.重点板块 中登记：%s" % 显示名, "无"

    口径 = 口径 if 口径 in ("行业", "概念", "合并") else "合并"
    层级映射 = {"一级": "申万一级", "二级": "申万二级", "三级": "申万三级"}
    片段表 = []
    来源集 = set()
    缺失 = []

    # ---- 一、申万板块（离线库按名称）----
    if 口径 in ("行业", "合并"):
        for 条 in 项.get("申万板块") or []:
            分类 = 层级映射.get(str(条.get("层级", "")).strip())
            名 = str(条.get("名称", "")).strip()
            if not 分类 or not 名:
                continue
            框 = _板块库成分(分类, 名)
            if 框 is None or len(框) == 0:
                缺失.append("%s/%s" % (分类, 名))
                continue
            片段表.append(框)
            来源集.add("申万离线库（%s）" % 分类)

    # ---- 二、新浪概念（离线库按名称）----
    # 优先「概念板块」库（新浪 gn_ 节点）：成分股数量合理、口径准确
    # （新能源 71 只、5G概念 47 只、智能电网 38 只）。
    # 其次「热门概念」库（新浪 chgn_ 节点）：概念名更现代，但一份概念动辄
    # 几百上千只（如芯片概念 922 只），口径明显偏宽，仅作补充。
    if 口径 in ("概念", "合并"):
        for 名 in 项.get("同花顺概念") or []:
            名 = str(名).strip()
            if not 名:
                continue
            框 = _板块库成分("概念板块", 名)
            标签 = "新浪概念库（概念板块）"
            if 框 is None or len(框) == 0:
                框 = _板块库成分("热门概念", 名)
                标签 = "新浪概念库（热门概念·口径宽）"
            if 框 is None or len(框) == 0:
                缺失.append("概念/%s" % 名)
                continue
            片段表.append(框)
            来源集.add(标签)

    # ---- 三、中证指数（只有前两条全空才走）----
    if not 片段表:
        中证组合 = [("概念板块", 码, config.中证主题指数.get(码, 码))
                    for 码 in 项.get("中证代码", [])]
        if 中证组合:
            框, 错, 源 = 合并成分股(中证组合)
            if 框 is not None and len(框):
                框["所属板块"] = 显示名
                return 框, 错, 源

    if not 片段表:
        return None, ("板块「%s」（%s口径）在离线库中没有匹配到任何成分股。"
                      "未命中：%s。请执行 python build_sector.py 建库后重试。"
                      % (显示名, 口径, "、".join(缺失) or "无配置")), "无"

    # ---- 合并去重，保留「所属板块」为细分来源 ----
    全部 = pd.concat(片段表, ignore_index=True)
    其他列 = [c for c in 全部.columns if c not in ("代码", "名称", "所属板块")]
    聚合 = {"名称": "first",
            "所属板块": lambda s: "、".join(sorted(set(str(x) for x in s)))}
    聚合.update({c: "first" for c in 其他列})
    合并 = 全部.groupby("代码", as_index=False).agg(聚合)
    合并["所属板块"] = 显示名
    # 把细分来源另存一列，界面上可看到「这只股票来自哪个申万行业 / 哪个概念」
    try:
        细分 = (全部.groupby("代码")["所属板块"]
              .apply(lambda s: "、".join(sorted(set(str(x) for x in s))))
              .rename("细分来源").reset_index())
        合并 = 合并.merge(细分, on="代码", how="left")
    except Exception:
        pass

    提示 = "离线库未命中：%s" % "、".join(缺失) if 缺失 else ""
    return 合并.reset_index(drop=True), 提示, "、".join(sorted(来源集))


def 重点板块口径统计(显示名: str) -> dict:
    """返回三种口径下的成分股数量，用于界面提示口径差异。
    只读本地库，不联网。返回 {"行业": n, "概念": n, "合并": n}。
    """
    结果 = {}
    for 口径 in ("行业", "概念", "合并"):
        框, _, _ = 重点板块成分股(显示名, 口径)
        结果[口径] = 0 if 框 is None else len(框)
    return 结果


# ============================================================ 六、板块热力图 ====

# 热力图用哪一层板块库：三类各自取一个不重叠的层级，避免同一只股票被算两遍
热力分类 = {
    "行业板块": "申万二级",
    "概念板块": "概念板块",
    "地域板块": "地域板块",
}

# 行业层级 → 离线库分类。行业板块允许再细分一级/二级/三级（申万口径）
行业层级 = {
    "一级行业": "申万一级",
    "二级行业": "申万二级",
    "三级行业": "申万三级",
}
默认行业层级 = "二级行业"


def 板块涨跌一览(类型: str = "行业板块", 层级: str = "") -> tuple:
    """
    板块热力图的数据源：每个板块的涨跌幅、成交额、涨跌家数。

    返回 (DataFrame[板块名称, 涨跌幅, 成交额, 成分数, 上涨家数, 下跌家数], 错误, 来源)。

    为什么不直接用同花顺的「行业板块实时汇总」：那个只有 90 个细分行业，
    覆盖面太窄，而且概念和地域两类它根本没有。这里改用
    「离线库成分股 + 全市场快照」本地算 —— 成分股清单已经在磁盘上，
    快照一次就够，几百个板块算下来只要几十毫秒，还能保证三类口径统一。

    涨跌幅取成分股等权平均（和交易所公布的板块指数口径接近，不会因为
    一两只巨无霸把整个板块拉偏）。
    """
    分类 = 热力分类.get(类型)
    if 类型 == "行业板块" and 层级 in 行业层级:
        分类 = 行业层级[层级]
    if not 分类:
        return None, "未知的板块类型：%s" % 类型, "无"

    缓存键 = "板块涨跌一览|%s|%s" % (类型, 层级 if 类型 == "行业板块" else "")
    命中 = 缓存.取(缓存键, min(config.缓存时长.get("资金流", 60), 60))
    if 命中 is not None:
        return 命中, "", "内存缓存"

    库 = 读板块库(分类)
    if not 库:
        return None, "离线库缺失（%s），请执行 python build_sector.py 建库" % 分类, "无"
    成分 = 库.get("成分股") or {}
    if not 成分:
        return None, "离线库里没有成分股数据（%s）" % 分类, "无"

    快照, 错, 源 = 全市场快照()
    if 快照 is None or 快照.empty:
        return None, "拿不到全市场快照：%s" % (错 or "接口返回为空"), "无"

    快照 = 快照.drop_duplicates(subset=["代码"]).set_index("代码")
    if "涨跌幅" not in 快照.columns:
        return None, "全市场快照缺少涨跌幅列", "无"
    涨 = pd.to_numeric(快照["涨跌幅"], errors="coerce")
    额 = (pd.to_numeric(快照["成交额"], errors="coerce")
          if "成交额" in 快照.columns else pd.Series(0.0, index=快照.index))

    记录 = []
    for 板块名, 股列表 in 成分.items():
        if not 股列表:
            continue
        代码表 = [str((只 or {}).get("代码", "")).strip() for 只 in 股列表]
        代码表 = [码 for 码 in 代码表 if 码 in 涨.index]
        if not 代码表:
            continue
        值 = 涨.reindex(代码表).dropna()
        if len(值) == 0:
            continue
        金额 = 额.reindex(代码表).fillna(0.0)
        记录.append({
            "板块名称": str(板块名),
            "涨跌幅": round(float(值.mean()), 2),
            "成交额": float(金额.sum()),
            "成分数": len(代码表),
            "上涨家数": int((值 > 0).sum()),
            "下跌家数": int((值 < 0).sum()),
        })

    if not 记录:
        return None, "板块成分股与全市场快照没有匹配上，可能是离线库过期", "无"

    框 = pd.DataFrame(记录).sort_values("涨跌幅", ascending=False).reset_index(drop=True)
    缓存.存(缓存键, 框)
    return 框, "", "离线成分股 + 新浪全市场快照（%s）" % 分类