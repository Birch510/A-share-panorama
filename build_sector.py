# -*- coding: utf-8 -*-
"""
build_sector.py —— 板块成分股离线建库脚本（项目最关键的取数通道）

为什么需要它
------------
实测（2026-10-30）本项目所在网络环境存在内容级拦截：
    · 东方财富 clist / kline 路径被确定性阻断（10 次重试 0 次成功）
    · 中证 oss-ch.csindex.com.cn 返回 403 + HTML 拦截页（已不是 Excel）
    · 申万官网 sw_index_third_cons 间歇性 "No tables found"
只有新浪的「股票分类」接口稳定可用，而且它一次就能给出
「股票 → 所属板块」的完整映射，还自带价格、涨跌幅、市盈率、市净率、
市值、换手率，正好满足「全品类 + 全数据量」的要求。

接口
----
    板块清单：akshare 内部的 stock_classify_board()
              返回 DataFrame，列 code / name，键为分类名。
    成分股：  新浪 Market_Center.getHQNodeStockCount（取总数）
             新浪 Market_Center.getHQNodeData（分页取 80 条）

    注意：akshare 自带的 stock_classify_sina 没有做任何容错，
    某个板块分页返回非 JSON 就整批抛 "Expecting value: line 1 column 1"，
    实测热门概念 705 个板块跑到 88% 时整批失败。
    所以本脚本自己实现分页抓取：单板块失败只跳过该板块并记录，不影响整体。

可用分类与板块数量（实测 stock_classify_board()）
    申万一级   31      申万二级  131      申万三级  336
    热门概念  705      概念板块  214      地域板块   31
    证监会行业 19      新浪行业   48      市场分类   16

实测耗时（全量）
    申万一级  约 20 秒     申万二级  约 40 秒     申万三级  约 90 秒
    地域板块  约 18 秒     热门概念  约 300 秒    概念板块  约 90 秒

产物（写入 数据/ 目录）
    板块_<分类>.json
        {"分类":..., "抓取时间":..., "板块列表":[{名称,成分股数量},...],
         "成分股": {板块名称: [{代码,名称,最新价,涨跌幅,市盈率,市净率,总市值,换手率}, ...]}}
    板块建库汇总.json      各分类的板块数、成分股数、耗时、失败板块

用法
----
    python build_sector.py                    # 建核心六类（约 10 分钟）
    python build_sector.py --全部             # 建全部九类
    python build_sector.py --类别 申万二级,热门概念
    python build_sector.py --列表             # 只打印已建库情况，不联网
    python build_sector.py --强制             # 已有库也重新抓
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

import requests

项目目录 = os.path.dirname(os.path.abspath(__file__))
数据目录 = os.path.join(项目目录, "数据")
os.makedirs(数据目录, exist_ok=True)

汇总文件 = os.path.join(数据目录, "板块建库汇总.json")

# 分类名 → 产物文件名。核心六类是页面主要入口，其余为增强。
分类文件 = {
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
核心分类 = ["申万一级", "申万二级", "申万三级", "热门概念", "概念板块", "地域板块"]

单一页条数 = 80
请求超时 = 15
单板块重试 = 3
页间间隔 = 0.15      # 秒，轻微节制，避免被新浪判定为爬虫
板块间隔 = 0.05

# ---- 新浪行情节点接口 ----
URL_计数 = ("http://vip.stock.finance.sina.com.cn/quotes_service/api/"
            "json_v2.php/Market_Center.getHQNodeStockCount")
URL_分页 = ("http://vip.stock.finance.sina.com.cn/quotes_service/api/"
            "json_v2.php/Market_Center.getHQNodeData")

列名映射 = {
    "code": "代码",
    "name": "名称",
    "trade": "最新价",
    "pricechange": "涨跌额",
    "changepercent": "涨跌幅",
    "volume": "成交量",
    "amount": "成交额",
    "per": "市盈率",
    "pb": "市净率",
    "mktcap": "总市值",
    "nmc": "流通市值",
    "turnoverratio": "换手率",
}


def 写JSON(路径: str, 数据) -> None:
    """原子写入 JSON（先写临时文件再替换，避免中断留下半个文件）。"""
    临时 = 路径 + ".tmp"
    with io.open(临时, "w", encoding="utf-8") as 文件:
        json.dump(数据, 文件, ensure_ascii=False)
    os.replace(临时, 路径)


def 读JSON(路径: str, 默认=None):
    try:
        with io.open(路径, "r", encoding="utf-8") as 文件:
            return json.load(文件)
    except Exception:
        return 默认


def 北京时间() -> str:
    """返回北京时间字符串（不依赖第三方库）。"""
    import datetime as _dt

    时区 = _dt.timezone(_dt.timedelta(hours=8))
    return _dt.datetime.now(时区).strftime("%Y-%m-%d %H:%M:%S")


def 转数值(值):
    try:
        if 值 is None or 值 == "":
            return None
        结果 = float(值)
        if 结果 != 结果:
            return None
        return 结果
    except Exception:
        return None


清单缓存文件 = os.path.join(数据目录, "新浪板块清单.json")


def _取板块清单(分类: str):
    """从 akshare 内部函数拿板块清单 [(code, name), ...]。

    重要：新浪的分类清单接口（stock_classify_board）有约 60 秒的频率限制，
    每个分类都重新抓一次会让后面的分类直接返回空响应
    （典型报错：Expecting value: line 1 column 1 (char 0)）。
    因此第一次抓到就把「全部九个分类」一次性落盘，之后所有分类都读本地，
    只有本地没有时才重新联网，并带 6 次、每次间隔 10 秒的重试。
    """
    缓存 = 读JSON(清单缓存文件, {}) or {}
    已有 = 缓存.get(分类)
    if 已有 and 已有.get("板块"):
        return [(x.get("节点", ""), x.get("名称", "")) for x in 已有["板块"]]

    import akshare as ak

    取清单 = ak.stock_classify_sina.__globals__["stock_classify_board"]
    全部 = None
    for 次 in range(6):
        try:
            全部 = 取清单()
            if isinstance(全部, dict) and 全部:
                break
        except Exception:  # noqa: BLE001
            全部 = None
        time.sleep(10)
    if not isinstance(全部, dict) or not 全部:
        raise RuntimeError(
            "新浪板块清单接口连续 6 次失败（该接口有约 60 秒频率限制）。"
            "请等待 1 分钟后重新执行：python build_sector.py")

    # 一次性把全部分类落盘，避免后续再打这个接口
    新缓存 = {}
    for 分类名, 表 in 全部.items():
        列表 = []
        try:
            for _, 行 in 表.iterrows():
                码 = str(行.get("code", "") or "").strip()
                称 = str(行.get("name", "") or "").strip()
                if 称 and 称.lower() != "nan":
                    列表.append({"节点": 码, "名称": 称})
        except Exception:  # noqa: BLE001
            continue
        if 列表:
            新缓存[分类名] = {"板块": 列表}
    if 新缓存:
        写JSON(清单缓存文件, 新缓存)

    本次 = 新缓存.get(分类) or {}
    return [(x.get("节点", ""), x.get("名称", "")) for x in 本次.get("板块", [])]


def _抓一个板块(节点代码: str) -> list:
    """抓单个板块的全部成分股。失败返回空列表。

    每次请求都带超时与重试；某个板块挂了只影响它自己。
    """
    总数 = None
    for 次 in range(单板块重试):
        try:
            响应 = requests.get(URL_计数, params={"node": 节点代码}, timeout=请求超时)
            总数 = int(响应.json())
            break
        except Exception:
            if 次 == 单板块重试 - 1:
                return []
            time.sleep(0.4 * (次 + 1))
    if not 总数 or 总数 <= 0:
        return []

    页数 = (总数 + 单一页条数 - 1) // 单一页条数
    记录: list = []
    for 页 in range(1, 页数 + 1):
        成功 = False
        for 次 in range(单板块重试):
            try:
                响应 = requests.get(URL_分页, params={
                    "page": 页, "num": str(单一页条数), "sort": "symbol",
                    "asc": "1", "node": 节点代码, "symbol": "", "_s_r_a": "init",
                }, timeout=请求超时)
                数据 = 响应.json()
                if not isinstance(数据, list):
                    raise ValueError("返回不是列表")
                成功 = True
                break
            except Exception:
                if 次 == 单板块重试 - 1:
                    break
                time.sleep(0.4 * (次 + 1))
        if not 成功:
            # 该页失败：跳过这一页，继续后面的页，尽量保住已拿到的数据
            continue
        for 项 in 数据:
            if not isinstance(项, dict):
                continue
            代码 = str(项.get("code", "")).strip().zfill(6)
            if not 代码.isdigit():
                continue
            记录.append({
                "代码": 代码,
                "名称": str(项.get("name", "")),
                "最新价": 转数值(项.get("trade")),
                "涨跌幅": 转数值(项.get("changepercent")),
                "市盈率": 转数值(项.get("per")),
                "市净率": 转数值(项.get("pb")),
                "总市值": 转数值(项.get("mktcap")),
                "换手率": 转数值(项.get("turnoverratio")),
            })
        time.sleep(页间间隔)
    return 记录


def 建一类(分类: str, 强制: bool = False) -> dict:
    """抓取一类板块并落盘，返回统计信息。"""
    路径 = os.path.join(数据目录, 分类文件[分类])
    已有 = 读JSON(路径, None)
    if 已有 and not 强制 and 已有.get("成分股"):
        板块数 = len(已有.get("板块列表") or [])
        股票数 = len(已有["成分股"])
        print("  [跳过] %s 已建库：%d 个板块（抓取于 %s）"
              % (分类, 板块数, 已有.get("抓取时间", "未知")))
        return {"分类": 分类, "状态": "已存在", "板块数": 板块数,
                "成分记录数": 股票数, "耗时秒": 0, "抓取时间": 已有.get("抓取时间", "")}

    try:
        清单 = _取板块清单(分类)
    except Exception as 异常:  # noqa: BLE001
        print("  [失败] 取板块清单出错：%s" % str(异常)[:200])
        return {"分类": 分类, "状态": "失败", "错误": str(异常)[:300]}
    if not 清单:
        print("  [失败] 分类「%s」下没有任何板块" % 分类)
        return {"分类": 分类, "状态": "失败", "错误": "板块清单为空"}

    print("  [抓取] %s：%d 个板块%s"
          % (分类, len(清单), "，较多板块请耐心等待" if len(清单) > 200 else ""))
    开始 = time.time()
    成分股: dict = {}
    板块列表: list = []
    失败板块: list = []
    for 序号, (节点, 名称) in enumerate(清单, 1):
        if not 节点:
            失败板块.append("%s（无节点代码）" % 名称)
            continue
        记录 = _抓一个板块(节点)
        if not 记录:
            失败板块.append(名称)
            continue
        成分股[名称] = 记录
        板块列表.append({"名称": 名称, "成分股数量": len(记录), "节点": 节点})
        if 序号 % 50 == 0:
            已用 = time.time() - 开始
            预计 = 已用 / 序号 * (len(清单) - 序号)
            print("         进度 %d/%d，已用 %.0f 秒，预计还需 %.0f 秒"
                  % (序号, len(清单), 已用, 预计), flush=True)
        time.sleep(板块间隔)

    if not 成分股:
        print("  [失败] %s 一个板块都没抓到" % 分类)
        return {"分类": 分类, "状态": "失败", "错误": "全部板块抓取失败"}

    耗时 = round(time.time() - 开始, 1)
    产物 = {
        "分类": 分类,
        "抓取时间": 北京时间(),
        "板块列表": 板块列表,
        "成分股": 成分股,
    }
    写JSON(路径, 产物)
    总数 = sum(len(v) for v in 成分股.values())
    print("  [完成] %s：%d 个板块 / %d 条成分记录，耗时 %.1f 秒"
          % (分类, len(板块列表), 总数, 耗时))
    if 失败板块:
        print("         失败 %d 个板块：%s" % (len(失败板块), "、".join(失败板块[:8])
                                          + ("…" if len(失败板块) > 8 else "")))
    return {"分类": 分类, "状态": "成功", "板块数": len(板块列表),
            "成分记录数": 总数, "耗时秒": 耗时, "抓取时间": 产物["抓取时间"],
            "失败板块": 失败板块[:30]}


def 打印列表() -> None:
    """不联网，只汇报本地已建库情况。"""
    汇总 = 读JSON(汇总文件, {}) or {}
    print("=" * 68)
    print("板块成分股离线库现状")
    print("=" * 68)
    有库 = 0
    for 分类, 文件名 in 分类文件.items():
        路径 = os.path.join(数据目录, 文件名)
        数据 = 读JSON(路径, None)
        if not 数据 or not 数据.get("成分股"):
            print("  %-6s  未建库" % 分类)
            continue
        有库 += 1
        板块数 = len(数据.get("板块列表") or [])
        股票数 = sum(len(v) for v in 数据["成分股"].values())
        print("  %-6s %4d 个板块 / %5d 条成分记录   抓取于 %s"
              % (分类, 板块数, 股票数, 数据.get("抓取时间", "未知")))
    print("-" * 68)
    if 有库 == 0:
        print("  一个库都没有。页面的「板块全景」将无法下钻成分股。")
        print("  请执行：python build_sector.py")
    else:
        print("  已建 %d 个库。" % 有库)
        print("  如需更新，执行：python build_sector.py --强制")
    print("=" * 68)


def 主流程() -> int:
    解析 = argparse.ArgumentParser(
        description="板块成分股离线建库（新浪股票分类接口）")
    解析.add_argument("--类别", default="", help="要建的分类，逗号分隔")
    解析.add_argument("--全部", action="store_true", help="建全部分类（九个，约 15 分钟）")
    解析.add_argument("--强制", action="store_true", help="已有库也重新抓取")
    解析.add_argument("--列表", action="store_true", help="只打印已建库情况，不联网")
    参数 = 解析.parse_args()

    if 参数.列表:
        打印列表()
        return 0

    if 参数.全部:
        目标 = list(分类文件.keys())
    elif 参数.类别:
        目标 = [x.strip() for x in 参数.类别.split(",") if x.strip()]
    else:
        目标 = list(核心分类)

    未知 = [x for x in 目标 if x not in 分类文件]
    if 未知:
        print("[错误] 不认识的分类：%s" % "、".join(未知))
        print("       可选值：%s" % "、".join(分类文件.keys()))
        return 2

    print("=" * 68)
    print("开始建立板块成分股离线库")
    print("计划建库：%s%s" % ("、".join(目标), "（强制重建）" if 参数.强制 else ""))
    print("数据来源：新浪财经股票分类接口")
    print("说明：热门概念有 700+ 个板块，逐个分页抓取，约 5 分钟，请勿关闭窗口。")
    print("=" * 68)

    结果 = []
    总开始 = time.time()
    for 序号, 分类 in enumerate(目标, 1):
        print("\n[%d/%d] %s" % (序号, len(目标), 分类))
        结果.append(建一类(分类, 强制=参数.强制))

    总耗时 = round(time.time() - 总开始, 1)
    旧汇总 = 读JSON(汇总文件, {}) or {}
    明细 = {x["分类"]: x for x in (旧汇总.get("明细") or [])}
    for x in 结果:
        明细[x["分类"]] = x
    写JSON(汇总文件, {"更新时间": 北京时间(), "总耗时秒": 总耗时,
                   "明细": list(明细.values())})

    print("\n" + "=" * 68)
    print("建库结束，共耗时 %.1f 秒" % 总耗时)
    print("=" * 68)
    for x in 结果:
        if x["状态"] == "失败":
            print("  [失败] %-6s %s" % (x["分类"], x.get("错误", "")))
        else:
            print("  [%s] %-6s %4d 个板块 / %6d 条记录  %6.1f 秒"
                  % ("成功" if x["状态"] == "成功" else "已有", x["分类"],
                     x.get("板块数", 0), x.get("成分记录数", 0), x.get("耗时秒", 0)))
    成功数 = len([x for x in 结果 if x["状态"] == "成功"])
    print("\n成功 %d / %d 个分类" % (成功数, len(结果)))
    print("产物目录：%s" % 数据目录)
    print("查看现状：python build_sector.py --列表")
    print("接下来可直接启动看板：双击「运行脚本.bat」")
    return 0


if __name__ == "__main__":
    sys.exit(主流程())