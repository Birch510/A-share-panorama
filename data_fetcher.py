# -*- coding: utf-8 -*-
"""
data_fetcher.py —— A 股全景看板：统一取数层

设计原则：
    1) 所有函数返回 (数据, 错误信息, 来源, 附加信息) 或 (数据, 错误信息)，
       页面永远能拿到「为什么没数据」，不会白屏。
    2) 每一类数据都有明确的降级链，主通道失败自动换下一条。
    3) 网络请求统一加超时与重试，绝不无限等待。
    4) 板块成分股优先读本地离线库（build_index.py 建的），离线也能用。
    5) 禁止线程池并发调用 akshare：其依赖的 py_mini_racer 非线程安全，
       并发会直接把进程打崩（FATAL: Check failed: !IsConfigurablePoolInitialized）。

模块结构：
    一、通用工具（缓存、重试、列名规范化、日期处理）
    二、交易日历
    三、板块体系（申万行业 / 中证概念 / 地域）
    四、板块成分股
    五、行情数据（个股日线 / 分钟 / 全市场快照 / 指数）
    六、板块指数行情
    七、资金面（个股资金流 / 板块资金流 / 北向 / 两融）
    八、情绪（涨停池 / 炸板 / 跌停 / 龙虎榜）
    九、估值（全市场 PE/PB / 指数估值 / 行业估值）
    十、宏观（PMI / CPI / PPI / 货币供应 / 社融 / 国债）
    十一、事件（业绩预告 / 预约披露 / 解禁）
    十二、衍生品（期货 / ETF / 可转债）
    十三、导出辅助
"""

import datetime as dt
import io
import json
import os
import re
import time
import traceback

import pandas as pd

import config


class _懒加载akshare:
    """
    akshare 的懒加载代理。

    为什么不用 `import akshare as ak`：这个 import 要 1.8 秒左右
    （它得初始化 py_mini_racer 才能跑新浪的 JS 加密），而它又发生在
    主窗口构造函数里 —— 等于用户双击图标后要干等两秒才见到窗口。

    改成代理对象以后，`ak.stock_zh_a_spot()` 这类写法完全不用动，
    但真正的 import 推迟到第一次真正取数的时候（那时已经在后台线程里，
    界面早就出来了）。

    要取版本号这类元信息也照常：ak.__version__ → 转发给真模块。
    """

    _真 = None

    def _拿(self):
        if _懒加载akshare._真 is None:
            import akshare as 真模块
            _懒加载akshare._真 = 真模块
        return _懒加载akshare._真

    def __getattr__(self, 名):
        return getattr(self._拿(), 名)

    def __dir__(self):
        return dir(self._拿())


try:
    ak = _懒加载akshare()
    有AK = True
except Exception:  # pragma: no cover
    ak = None
    有AK = False

try:
    from cachetools import TTLCache
    有TTLCache = True
except Exception:  # pragma: no cover
    有TTLCache = False


# ================================================================ 一、通用工具 ====

def 北京时间() -> dt.datetime:
    """返回北京时间的当前时刻（不依赖系统时区设置）。"""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).replace(tzinfo=None)


def 北京时间文本(带秒: bool = True) -> str:
    return 北京时间().strftime(config.时间格式 if 带秒 else "%Y-%m-%d %H:%M")


class 内存缓存:
    """极简 TTL 缓存。有 cachetools 就用它，没有就退回自带字典实现。"""

    def __init__(self, 最大条目: int = 512):
        self._数据 = {}
        self._上限 = 最大条目
        if 有TTLCache:
            self._底层 = TTLCache(maxsize=最大条目, ttl=24 * 3600)
        else:
            self._底层 = None

    def 取(self, 键: str, 时长: int):
        现在 = time.time()
        项 = self._数据.get(键)
        if 项 and 现在 - 项[1] < 时长:
            return 项[0]
        return None

    def 存(self, 键: str, 值):
        if len(self._数据) >= self._上限:
            # 淘汰最旧的一半，简单但够用
            按时间 = sorted(self._数据.items(), key=lambda kv: kv[1][1])
            for 旧键, _ in 按时间[: self._上限 // 2]:
                self._数据.pop(旧键, None)
        self._数据[键] = (值, time.time())

    def 清空(self) -> int:
        n = len(self._数据)
        self._数据.clear()
        return n

    def 条目数(self) -> int:
        return len(self._数据)


缓存 = 内存缓存(config.内存缓存条目上限)


def 清空缓存() -> int:
    return 缓存.清空()


def 缓存条目数() -> int:
    return 缓存.条目数()


def 重试请求(函数, *参数, 次数: int = None, 说明: str = "", **关键字):
    """带指数退避的重试。返回 (结果, 错误文本)。"""
    次数 = 次数 or config.最大重试次数
    最后错误 = ""
    for i in range(次数):
        try:
            结果 = 函数(*参数, **关键字)
            if 结果 is None:
                raise ValueError("接口返回空值")
            if isinstance(结果, pd.DataFrame) and len(结果) == 0:
                raise ValueError("接口返回空表")
            return 结果, ""
        except Exception as e:
            最后错误 = "%s: %s" % (type(e).__name__, str(e)[:200])
            if i < 次数 - 1:
                time.sleep(config.重试等待秒 * (2 ** i))
    return None, (说明 + "：" if 说明 else "") + 最后错误


def 规范日期(值) -> str:
    """把 20260901 / 2026-9-1 / date 统一成 2026-09-01。"""
    if 值 is None or (isinstance(值, float) and 值 != 值):
        return ""
    if isinstance(值, (dt.date, dt.datetime)):
        return 值.strftime("%Y-%m-%d")
    s = str(值).strip()
    if not s:
        return ""
    数字 = re.sub(r"\D", "", s)
    if len(数字) >= 8:
        return "%s-%s-%s" % (数字[:4], 数字[4:6], 数字[6:8])
    return s


def 紧凑日期(值) -> str:
    """把 2026-09-01 统一成 20260901（部分接口要这种格式）。"""
    return 规范日期(值).replace("-", "")


def 数值(值):
    """把「1.23%」「1.2亿」「-」等转成 float；失败返回 None。"""
    if 值 is None:
        return None
    if isinstance(值, (int, float)):
        try:
            v = float(值)
            return None if v != v else v
        except Exception:
            return None
    s = str(值).strip().replace(",", "").replace("%", "")
    if not s or s in ("-", "--", "None", "nan", "NaN"):
        return None
    倍数 = 1.0
    if s.endswith("万亿"):
        倍数, s = 1e12, s[:-2]
    elif s.endswith("亿"):
        倍数, s = 1e8, s[:-1]
    elif s.endswith("万"):
        倍数, s = 1e4, s[:-1]
    try:
        return float(s) * 倍数
    except Exception:
        return None


def 规范股票代码(代码: str) -> str:
    """600111 / sh600111 / 600111.SH → 600111。"""
    s = str(代码).strip().upper()
    s = re.sub(r"^(SH|SZ|BJ)", "", s)
    for 后缀 in (".SH", ".SZ", ".BJ"):
        if s.endswith(后缀):
            s = s[: -len(后缀)]
    return s.zfill(6) if s.isdigit() else s


def 带前缀代码(代码: str) -> str:
    """600111 → sh600111（新浪接口要这种格式）。"""
    码 = 规范股票代码(代码)
    if not 码.isdigit():
        return 码
    if 码.startswith(("60", "68", "90")):
        return "sh" + 码
    if 码.startswith(("00", "30", "20")):
        return "sz" + 码
    if 码.startswith(("8", "4", "92")):
        return "bj" + 码
    return "sh" + 码


def 交易所前缀(代码: str) -> str:
    """600111 → 1.600111（东财 secid 用）；深市前缀 0。"""
    码 = 规范股票代码(代码)
    if 码.startswith(("60", "68", "90", "5")):
        return "1." + 码
    return "0." + 码


def 转数据框(数据, 列映射: dict = None) -> pd.DataFrame:
    框 = pd.DataFrame(数据) if not isinstance(数据, pd.DataFrame) else 数据.copy()
    if 列映射:
        框 = 框.rename(columns={k: v for k, v in 列映射.items() if k in 框.columns})
    return 框


def 补涨跌颜色列(框: pd.DataFrame, 列名: str = "涨跌幅") -> pd.DataFrame:
    """给表格加一列「方向」，页面据此上色（红涨绿跌）。"""
    if 列名 in 框.columns:
        def _方向(v):
            x = 数值(v)
            if x is None:
                return ""
            return "涨" if x > 0 else ("跌" if x < 0 else "平")
        框["方向"] = 框[列名].map(_方向)
    return 框


def 读本地JSON(路径: str, 默认=None):
    if not os.path.exists(路径):
        return 默认
    try:
        with io.open(路径, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return 默认


def 写本地JSON(路径: str, 对象) -> bool:
    try:
        os.makedirs(os.path.dirname(路径), exist_ok=True)
        临时 = 路径 + ".tmp"
        with io.open(临时, "w", encoding="utf-8") as f:
            json.dump(对象, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(临时, 路径)
        return True
    except Exception:
        return False


def _无AK错误():
    return "未安装 akshare，请先执行：pip install -r requirements.txt"


_东财UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def 东财数据中心(报表名: str, 列="ALL", 页码=1, 每页=50, 过滤="", 排序=""):
    """直连东方财富数据中心（实测可用），返回记录列表。"""
    import requests
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    参数 = {
        "reportName": 报表名,
        "columns": 列,
        "pageNumber": str(页码),
        "pageSize": str(每页),
        "source": "WEB",
        "client": "WEB",
    }
    if 过滤:
        参数["filter"] = 过滤
    if 排序:
        # 东财要求排序字段与方向分开传：sortColumns=TRADE_DATE&sortTypes=-1
        # 这里允许调用方写「-TRADE_DATE」这种带前缀的简写，自动拆开。
        字段 = 排序.strip()
        方向 = "1"
        if 字段.startswith("-"):
            方向, 字段 = "-1", 字段[1:]
        elif 字段.startswith("+"):
            字段 = 字段[1:]
        参数["sortColumns"] = 字段
        参数["sortTypes"] = 方向
    try:
        r = requests.get(url, params=参数, headers=_东财UA, timeout=config.请求超时秒)
        j = r.json()
        结果 = j.get("result") or {}
        return 结果.get("data") or [], ""
    except Exception as e:
        return None, "东财数据中心 %s 失败：%s: %s" % (报表名, type(e).__name__, str(e)[:120])


# ================================================================ 二、交易日历 ====

def 交易日历() -> tuple:
    """返回 (交易日列表[str], 错误)。失败时用「周一到周五」兜底。"""
    缓存键 = "交易日历"
    命中 = 缓存.取(缓存键, config.缓存时长["交易日历"])
    if 命中 is not None:
        return 命中, ""
    if not 有AK:
        return _兜底交易日(), _无AK错误()
    df, 错 = 重试请求(ak.tool_trade_date_hist_sina, 说明="交易日历")
    if df is None or len(df) == 0:
        return _兜底交易日(), 错
    try:
        列 = "trade_date" if "trade_date" in df.columns else df.columns[0]
        日期列表 = [规范日期(x) for x in df[列].tolist()]
        日期列表 = [x for x in 日期列表 if x]
        缓存.存(缓存键, 日期列表)
        return 日期列表, ""
    except Exception as e:
        return _兜底交易日(), str(e)[:120]


def _兜底交易日():
    今天 = 北京时间().date()
    起 = 今天 - dt.timedelta(days=400)
    列表 = []
    d = 起
    while d <= 今天:
        if d.weekday() < 5:
            列表.append(d.strftime("%Y-%m-%d"))
        d += dt.timedelta(days=1)
    return 列表


def 最近交易日(偏移: int = 0) -> str:
    """返回第 偏移 个交易日（0 = 最近一个已收盘/正在进行的交易日）。"""
    列表, _ = 交易日历()
    今天 = 北京时间().strftime("%Y-%m-%d")
    已过 = [x for x in 列表 if x <= 今天]
    if not 已过:
        return 今天
    if 偏移 <= 0:
        return 已过[-1 + 偏移] if len(已过) >= 1 - 偏移 else 已过[0]
    return 已过[-1 - 偏移] if len(已过) > 偏移 else 已过[0]


def 上一交易日(日期: str = None) -> str:
    列表, _ = 交易日历()
    目标 = 规范日期(日期) if 日期 else 北京时间().strftime("%Y-%m-%d")
    之前 = [x for x in 列表 if x < 目标]
    return 之前[-1] if 之前 else 目标


def 是否交易时段(时刻: dt.datetime = None) -> tuple:
    """返回 (是否盘中, 时段说明)。"""
    时刻 = 时刻 or 北京时间()
    if 时刻.weekday() >= 5:
        return False, "周末休市"
    t = 时刻.strftime("%H:%M")
    if "09:15" <= t < "09:30":
        return False, "集合竞价"
    if "09:30" <= t <= "11:30" or "13:00" <= t <= "15:00":
        return True, "交易中"
    if t < "09:15":
        return False, "未开盘"
    if "11:30" < t < "13:00":
        return False, "午间休市"
    return False, "已收盘"


# ================================================================ 五、行情数据 ====

def 个股日线(代码: str, 开始日期: str, 结束日期: str, 复权: str = "qfq") -> tuple:
    """个股日线。降级链：新浪 → 腾讯 → 东财。
    返回 (DataFrame[日期/开盘/最高/最低/收盘/成交量/成交额], 错误, 来源)。
    """
    代码 = 规范股票代码(代码)
    开始 = 规范日期(开始日期)
    结束 = 规范日期(结束日期)
    缓存键 = "日线_%s_%s_%s_%s" % (代码, 开始, 结束, 复权)
    命中 = 缓存.取(缓存键, config.缓存时长["日K"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    if not 有AK:
        return None, _无AK错误(), "无"

    错误列表 = []

    # 1) 新浪（实测稳定，支持前复权/后复权）
    try:
        df = ak.stock_zh_a_daily(symbol=带前缀代码(代码),
                                 start_date=紧凑日期(开始),
                                 end_date=紧凑日期(结束),
                                 adjust=复权 or "")
        if df is not None and len(df):
            框 = df.rename(columns={"date": "日期", "open": "开盘", "high": "最高",
                                    "low": "最低", "close": "收盘", "volume": "成交量",
                                    "amount": "成交额"}).copy()
            框 = _整理日K(框)
            if len(框):
                缓存.存(缓存键, 框)
                return 框, "", "新浪"
    except Exception as e:
        错误列表.append("新浪：%s" % str(e)[:100])

    # 2) 腾讯
    try:
        df = ak.stock_zh_a_hist_tx(symbol=带前缀代码(代码),
                                   start_date=紧凑日期(开始), end_date=紧凑日期(结束),
                                   adjust=复权 or "")
        if df is not None and len(df):
            框 = df.rename(columns={"date": "日期", "open": "开盘", "high": "最高",
                                    "low": "最低", "close": "收盘", "amount": "成交量"}).copy()
            框 = _整理日K(框)
            if len(框):
                缓存.存(缓存键, 框)
                return 框, "", "腾讯"
    except Exception as e:
        错误列表.append("腾讯：%s" % str(e)[:100])

    # 3) 东财（本机 clist/kline 路径常被阻断，仅作最后尝试）
    try:
        df = ak.stock_zh_a_hist(symbol=代码, period="daily",
                                start_date=紧凑日期(开始), end_date=紧凑日期(结束),
                                adjust=复权 or "")
        if df is not None and len(df):
            框 = df.rename(columns={"日期": "日期", "开盘": "开盘", "最高": "最高",
                                    "最低": "最低", "收盘": "收盘", "成交量": "成交量",
                                    "成交额": "成交额"}).copy()
            框 = _整理日K(框)
            if len(框):
                缓存.存(缓存键, 框)
                return 框, "", "东方财富"
    except Exception as e:
        错误列表.append("东财：%s" % str(e)[:100])

    return None, "个股 %s 日线取不到。%s" % (代码, "；".join(错误列表)), "无"


def _整理日K(框: pd.DataFrame) -> pd.DataFrame:
    """统一日K结构，按日期排序并规范类型。"""
    if 框 is None or len(框) == 0:
        return pd.DataFrame()
    保留 = [c for c in ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"] if c in 框.columns]
    框 = 框[保留].copy()
    框["日期"] = 框["日期"].map(规范日期)
    框 = 框[框["日期"].str.len() == 10]
    for 列 in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
        if 列 in 框.columns:
            框[列] = pd.to_numeric(框[列], errors="coerce")
    框 = 框.dropna(subset=["收盘"])
    框 = 框.sort_values("日期").drop_duplicates(subset=["日期"]).reset_index(drop=True)
    return 框


def 重采样K线(框: pd.DataFrame, 规则: str) -> pd.DataFrame:
    """把日K重采样成周K/月K。规则见 config.K线聚合规则。"""
    if 框 is None or len(框) == 0 or not 规则:
        return 框
    工作 = 框.copy()
    工作["日期"] = pd.to_datetime(工作["日期"])
    工作 = 工作.set_index("日期")
    聚合 = {k: v for k, v in config.K线聚合规则.items() if k in 工作.columns}
    结果 = 工作.resample(规则).agg(聚合).dropna(subset=["收盘"]).reset_index()
    结果["日期"] = 结果["日期"].dt.strftime("%Y-%m-%d")
    return 结果


def 个股K线(代码: str, 周期: str, 开始日期: str, 结束日期: str, 复权: str = "qfq") -> tuple:
    """按周期取个股 K 线。返回 (DataFrame, 错误, 来源)。"""
    配置 = config.K线周期映射.get(周期)
    if not 配置:
        return None, "未知周期：%s" % 周期, "无"

    if 配置["类别"] == "分钟类":
        return 个股分钟(代码, 配置["分钟参数"], 开始日期, 结束日期)

    # 周K/月K 需要更早的起点才能聚合出完整周期
    if 配置["重采样规则"] in ("W-FRI", "ME"):
        开始 = 规范日期(开始日期)
        try:
            起 = dt.datetime.strptime(开始, "%Y-%m-%d") - dt.timedelta(days=40)
            开始 = 起.strftime("%Y-%m-%d")
        except Exception:
            pass
        日K, 错, 源 = 个股日线(代码, 开始, 结束日期, 复权)
        if 日K is None:
            return None, 错, 源
        结果 = 重采样K线(日K, 配置["重采样规则"])
        return 结果, "", 源 + "（%s本地聚合）" % 周期

    返回 = 个股日线(代码, 开始日期, 结束日期, 复权)
    return 返回[0], 返回[1], 返回[2]


def 个股分钟(代码: str, 周期: str, 开始日期: str = "", 结束日期: str = "") -> tuple:
    """个股分钟行情。主通道新浪 stock_zh_a_minute（固定返回最近 1970 根）。
    返回 (DataFrame[日期/时间/开盘/最高/最低/收盘/成交量/成交额], 错误, 来源)。
    """
    代码 = 规范股票代码(代码)
    周期 = str(周期)
    缓存键 = "分钟_%s_%s_%s_%s" % (代码, 周期, 开始日期, 结束日期)
    命中 = 缓存.取(缓存键, config.缓存时长["分钟行情"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    if not 有AK:
        return None, _无AK错误(), "无"

    错误列表 = []

    # 1) 新浪分钟
    try:
        df = ak.stock_zh_a_minute(symbol=带前缀代码(代码), period=周期, adjust="")
        if df is not None and len(df):
            框 = df.rename(columns={"day": "时间戳", "open": "开盘", "high": "最高",
                                    "low": "最低", "close": "收盘", "volume": "成交量",
                                    "amount": "成交额"}).copy()
            框 = _整理分钟(框)
            if len(框):
                框 = _按区间过滤分钟(框, 开始日期, 结束日期)
                缓存.存(缓存键, 框)
                return 框, "", "新浪"
    except Exception as e:
        错误列表.append("新浪：%s" % str(e)[:100])

    # 2) 东财分钟（本机常被阻断）
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=代码, period=周期, adjust="")
        if df is not None and len(df):
            框 = df.rename(columns={"时间": "时间戳", "开盘": "开盘", "最高": "最高",
                                    "最低": "最低", "收盘": "收盘", "成交量": "成交量",
                                    "成交额": "成交额"}).copy()
            框 = _整理分钟(框)
            if len(框):
                框 = _按区间过滤分钟(框, 开始日期, 结束日期)
                缓存.存(缓存键, 框)
                return 框, "", "东方财富"
    except Exception as e:
        错误列表.append("东财：%s" % str(e)[:100])

    return None, "个股 %s 的 %s 分钟行情取不到。%s" % (代码, 周期, "；".join(错误列表)), "无"


def _整理分钟(框: pd.DataFrame) -> pd.DataFrame:
    """统一分钟数据结构：拆出「日期」「时间」两列。"""
    if 框 is None or len(框) == 0:
        return pd.DataFrame()
    列 = "时间戳" if "时间戳" in 框.columns else ("时间" if "时间" in 框.columns else None)
    if 列 is None:
        return pd.DataFrame()
    框 = 框.copy()
    文本 = 框[列].astype(str)
    框["日期"] = 文本.str.slice(0, 10).map(规范日期)
    框["时间"] = 文本.str.slice(11, 16)
    框 = 框[框["时间"].str.match(r"^\d{2}:\d{2}$", na=False)]
    for 名 in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
        if 名 in 框.columns:
            框[名] = pd.to_numeric(框[名], errors="coerce")
    框 = 框.dropna(subset=["收盘"])
    框 = 框.sort_values(["日期", "时间"]).drop_duplicates(subset=["日期", "时间"]).reset_index(drop=True)
    # 计算分钟涨跌幅（相对上一根收盘）
    if "收盘" in 框.columns and len(框) > 1:
        框["涨跌幅"] = (框["收盘"].pct_change() * 100).round(3)
        框.loc[框.index[0], "涨跌幅"] = None
    return 框


def _按区间过滤分钟(框: pd.DataFrame, 开始日期: str, 结束日期: str) -> pd.DataFrame:
    开始 = 规范日期(开始日期)
    结束 = 规范日期(结束日期)
    if 开始:
        框 = 框[框["日期"] >= 开始]
    if 结束:
        框 = 框[框["日期"] <= 结束]
    return 框.reset_index(drop=True)


def 全市场快照() -> tuple:
    """全市场 A 股实时快照（新浪，5576 只，约 13 秒）。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "全市场快照"
    命中 = 缓存.取(缓存键, config.缓存时长["实时快照"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"

    df, 错 = 重试请求(ak.stock_zh_a_spot, 说明="全市场快照", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "全市场快照无数据", "新浪"
    try:
        框 = df.rename(columns={
            "代码": "代码原文", "名称": "名称", "最新价": "最新价", "涨跌额": "涨跌额",
            "涨跌幅": "涨跌幅", "昨收": "昨收", "今开": "今开", "最高": "最高",
            "最低": "最低", "成交量": "成交量", "成交额": "成交额",
        }).copy()
        框["代码"] = 框["代码原文"].map(规范股票代码)
        框["换手率"] = None
        框["市盈率"] = None
        框["市净率"] = None
        框["总市值"] = None
        for 列 in ["最新价", "涨跌额", "涨跌幅", "昨收", "今开", "最高", "最低", "成交量", "成交额"]:
            if 列 in 框.columns:
                框[列] = pd.to_numeric(框[列], errors="coerce")
        框 = 框[框["代码"].str.isdigit()].reset_index(drop=True)
        缓存.存(缓存键, 框)
        return 框, "", "新浪"
    except Exception as e:
        return None, "全市场快照解析失败：%s" % str(e)[:150], "新浪"


def 指数实时() -> tuple:
    """主要指数实时行情（新浪，562 个指数）。返回 (DataFrame, 错误, 来源)。"""
    缓存键 = "指数实时"
    命中 = 缓存.取(缓存键, config.缓存时长["实时快照"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_zh_index_spot_sina, 说明="指数实时", 次数=2)
    if df is None or len(df) == 0:
        return None, 错 or "指数实时无数据", "新浪"
    框 = df.copy()
    for 列 in ["最新价", "涨跌额", "涨跌幅", "昨收", "今开", "最高", "最低", "成交量", "成交额"]:
        if 列 in 框.columns:
            框[列] = pd.to_numeric(框[列], errors="coerce")
    缓存.存(缓存键, 框)
    return 框, "", "新浪"


# 重点关注的宽基指数（页面「全局总览」用）
关注指数 = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300",
            "上证50", "中证500", "中证1000", "北证50", "国证2000"]


def 重点关注指数() -> tuple:
    """从指数实时结果里挑出宽基指数。返回 (DataFrame, 错误, 来源)。"""
    框, 错, 源 = 指数实时()
    if 框 is None:
        return None, 错, 源
    名列 = "名称" if "名称" in 框.columns else None
    if not 名列:
        return 框.head(10), "指数结果缺少名称列", 源
    子 = 框[框[名列].isin(关注指数)].copy()
    if len(子) == 0:
        return 框.head(10), "未匹配到宽基指数，改为展示前 10 个", 源
    # 按 关注指数 的顺序排
    序 = {名: i for i, 名 in enumerate(关注指数)}
    子["_序"] = 子[名列].map(序).fillna(99)
    return 子.sort_values("_序").drop(columns=["_序"]).reset_index(drop=True), "", 源


def 指数日线(指数代码: str, 开始日期: str = "", 结束日期: str = "") -> tuple:
    """指数日线。返回 (DataFrame[日期/开盘/最高/最低/收盘/成交量], 错误, 来源)。"""
    代码 = str(指数代码).strip()
    if not 代码.startswith(("sh", "sz", "bj")):
        代码 = "sh" + 代码
    缓存键 = "指数日线_%s_%s_%s" % (代码, 开始日期, 结束日期)
    命中 = 缓存.取(缓存键, config.缓存时长["日K"])
    if 命中 is not None:
        return 命中, "", "内存缓存"
    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.stock_zh_index_daily, symbol=代码, 说明="指数日线")
    if df is None or len(df) == 0:
        return None, 错 or "指数 %s 无日线数据" % 代码, "新浪"
    框 = df.rename(columns={"date": "日期", "open": "开盘", "high": "最高",
                            "low": "最低", "close": "收盘", "volume": "成交量"}).copy()
    框 = _整理日K(框)
    框 = _按区间过滤分钟(框, 开始日期, 结束日期) if 开始日期 or 结束日期 else 框
    缓存.存(缓存键, 框)
    return 框, "", "新浪"


# ============================================================ 六、板块指数行情 ====

def 申万板块K线(行业代码: str, 周期: str = "日K") -> tuple:
    """申万行业指数 K 线（实测：三级行业也有，最深可回溯到 1999 年）。
    返回 (DataFrame, 错误, 来源)。
    """
    代码 = str(行业代码).replace(".SI", "")
    周期参数 = {"日K": "day", "周K": "week", "月K": "month"}.get(周期)
    if not 周期参数:
        return None, "申万指数只支持 日K/周K/月K，不支持 %s" % 周期, "申万"
    缓存键 = "申万K线_%s_%s" % (代码, 周期)
    命中 = 缓存.取(缓存键, config.缓存时长["板块K线"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    if not 有AK:
        return None, _无AK错误(), "无"
    df, 错 = 重试请求(ak.index_hist_sw, symbol=代码, period=周期参数, 说明="申万指数 %s" % 代码)
    if df is None or len(df) == 0:
        return None, 错 or "申万指数 %s 无数据" % 代码, "申万"
    框 = df.rename(columns={"日期": "日期", "收盘": "收盘", "开盘": "开盘",
                            "最高": "最高", "最低": "最低", "成交量": "成交量",
                            "成交额": "成交额"}).copy()
    框 = _整理日K(框)
    缓存.存(缓存键, 框)
    return 框, "", "申万指数"


def 同花顺板块K线(板块名称: str, 板块类型: str = "概念板块",
                  开始日期: str = "", 结束日期: str = "") -> tuple:
    """同花顺板块指数 K 线（只有日线，周/月由本地重采样）。
    返回 (DataFrame, 错误, 来源)。
    """
    函数名 = ("stock_board_concept_index_ths" if 板块类型 == "概念板块"
              else "stock_board_industry_index_ths")
    缓存键 = "THSK线_%s_%s" % (板块类型, 板块名称)
    命中 = 缓存.取(缓存键, config.缓存时长["板块K线"])
    if 命中 is not None:
        return 命中, "", "内存缓存"

    if not 有AK:
        return None, _无AK错误(), "无"
    开始 = 紧凑日期(开始日期) if 开始日期 else "20200101"
    结束 = 紧凑日期(结束日期) if 结束日期 else 紧凑日期(北京时间().strftime("%Y-%m-%d"))
    try:
        df = getattr(ak, 函数名)(symbol=板块名称, start_date=开始, end_date=结束)
    except Exception as e:
        return None, "同花顺%s「%s」K线失败：%s" % (板块类型, 板块名称, str(e)[:120]), "同花顺"
    if df is None or len(df) == 0:
        return None, "同花顺%s「%s」无K线数据（可能板块名不匹配）" % (板块类型, 板块名称), "同花顺"
    框 = df.rename(columns={"日期": "日期", "收盘价": "收盘", "开盘价": "开盘",
                            "最高价": "最高", "最低价": "最低", "成交量": "成交量",
                            "成交额": "成交额"}).copy()
    框 = _整理日K(框)
    缓存.存(缓存键, 框)
    return 框, "", "同花顺指数"


def 合成板块K线(成分股代码列表: list, 周期: str, 开始日期: str, 结束日期: str,
                最多股票数: int = 20) -> tuple:
    """没有板块指数时，用成分股等权合成板块 K 线。
    合成方法：每只股票按起始日收盘价归一化，再对开/高/低/收逐日等权平均；
    成交量、成交额求和。图标题必须标注「合成板块K线」。
    """
    if not 成分股代码列表:
        return None, "没有成分股，无法合成", "合成"
    代码们 = [规范股票代码(c) for c in 成分股代码列表][:最多股票数]
    各股 = []
    失败数 = 0
    for 码 in 代码们:
        df, _, _ = 个股K线(码, 周期, 开始日期, 结束日期, "qfq")
        if df is None or len(df) < 2:
            失败数 += 1
            continue
        子 = df[["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]].copy() \
            if "成交额" in df.columns else df[["日期", "开盘", "最高", "最低", "收盘", "成交量"]].copy()
        首收 = 子["收盘"].iloc[0]
        if not 首收 or 首收 <= 0:
            失败数 += 1
            continue
        for 列 in ["开盘", "最高", "最低", "收盘"]:
            子[列] = 子[列] / 首收 * 100.0
        子["代码"] = 码
        各股.append(子)
    if not 各股:
        return None, "所有成分股都取不到 K 线，无法合成（失败 %d 只）" % 失败数, "合成"

    合并 = pd.concat(各股, ignore_index=True)
    聚合 = {"开盘": "mean", "最高": "mean", "最低": "mean", "收盘": "mean"}
    if "成交量" in 合并.columns:
        聚合["成交量"] = "sum"
    if "成交额" in 合并.columns:
        聚合["成交额"] = "sum"
    结果 = 合并.groupby("日期", as_index=False).agg(聚合).sort_values("日期").reset_index(drop=True)
    # 归一化基准是 100，转回「以首日收盘为基点」的指数点位，便于与真实指数同图对比
    说明 = "合成板块K线（%d 只成分股等权，%d 只取数失败）" % (len(各股), 失败数)
    return 结果, "", 说明


def 板块K线(板块名称: str, 板块类型: str, 周期: str, 开始日期: str, 结束日期: str,
           申万代码: str = "", 成分股代码: list = None) -> tuple:
    """板块 K 线统一入口。降级链：申万指数（行业）→ 同花顺指数 → 成分股合成。
    返回 (DataFrame, 错误, 来源, 数据性质)。
    数据性质为 "板块指数" 或 "合成板块K线"，页面必须显示。
    """
    if 周期 in ("周K", "月K") and 申万代码:
        框, 错, 源 = 申万板块K线(申万代码, 周期)
        if 框 is not None and len(框):
            if 开始日期 or 结束日期:
                框 = _按区间过滤分钟(框, 开始日期, 结束日期)
            return 框, "", 源, "板块指数"

    if 周期 in ("日K", "周K", "月K"):
        # 1) 申万（行业）
        if 申万代码:
            日K, 错1, 源1 = 申万板块K线(申万代码, "日K")
            if 日K is not None and len(日K):
                规则 = config.K线周期映射["周K"]["重采样规则"] if 周期 == "周K" else (
                    config.K线周期映射["月K"]["重采样规则"] if 周期 == "月K" else None)
                结果 = 重采样K线(日K, 规则) if 规则 else 日K
                if 开始日期 or 结束日期:
                    结果 = _按区间过滤分钟(结果, 开始日期, 结束日期)
                return 结果, "", "申万指数", "板块指数"
        # 2) 同花顺（概念/行业）
        日K, 错2, 源2 = 同花顺板块K线(板块名称, 板块类型, 开始日期, 结束日期)
        if 日K is not None and len(日K):
            规则 = config.K线周期映射["周K"]["重采样规则"] if 周期 == "周K" else (
                config.K线周期映射["月K"]["重采样规则"] if 周期 == "月K" else None)
            结果 = 重采样K线(日K, 规则) if 规则 else 日K
            来源 = "同花顺指数（%s本地聚合）" % 周期 if 规则 else "同花顺指数"
            return 结果, "", 来源, "板块指数"
        # 3) 成分股合成
        if 成分股代码:
            结果, 错3, 源3 = 合成板块K线(成分股代码, 周期, 开始日期, 结束日期)
            if 结果 is not None and len(结果):
                return 结果, "", 源3, "合成板块K线"
            return None, "板块「%s」取不到K线：%s" % (板块名称, 错3), "无", "无"
        return None, "板块「%s」取不到K线（无申万代码、同花顺无同名板块、也没有成分股可合成）" % 板块名称, "无", "无"

    # 分钟类：板块没有原生分钟指数，用成分股合成
    if 成分股代码:
        结果, 错, 源 = _合成板块分钟(成分股代码, config.K线周期映射[周期]["分钟参数"],
                                开始日期, 结束日期)
        if 结果 is not None and len(结果):
            return 结果, "", 源, "合成板块K线"
        return None, "板块「%s」分钟K线合成失败：%s" % (板块名称, 错), "无", "无"
    return None, "板块分钟K线需要成分股才能合成，但当前没有成分股", "无", "无"


def _合成板块分钟(成分股代码列表: list, 分钟参数: str, 开始日期: str, 结束日期: str,
                 最多股票数: int = 10) -> tuple:
    """用成分股分钟数据合成板块分钟 K 线（归一化等权平均）。"""
    代码们 = [规范股票代码(c) for c in 成分股代码列表][:最多股票数]
    各股 = []
    失败数 = 0
    for 码 in 代码们:
        df, _, _ = 个股分钟(码, 分钟参数, 开始日期, 结束日期)
        if df is None or len(df) < 2:
            失败数 += 1
            continue
        子 = df[["日期", "时间", "开盘", "最高", "最低", "收盘"]].copy()
        首收 = 子["收盘"].iloc[0]
        if not 首收 or 首收 <= 0:
            失败数 += 1
            continue
        for 列 in ["开盘", "最高", "最低", "收盘"]:
            子[列] = 子[列] / 首收 * 100.0
        各股.append(子)
    if not 各股:
        return None, "所有成分股分钟数据都取不到（失败 %d 只）" % 失败数, "合成"
    合并 = pd.concat(各股, ignore_index=True)
    结果 = 合并.groupby(["日期", "时间"], as_index=False).agg({
        "开盘": "mean", "最高": "mean", "最低": "mean", "收盘": "mean",
    }).sort_values(["日期", "时间"]).reset_index(drop=True)
    return 结果, "", "合成板块K线（%d 只等权，%d 只失败）" % (len(各股), 失败数)