# -*- coding: utf-8 -*-
"""
data_export.py —— 导出辅助

约定：
    CSV  一律 UTF-8-SIG（带 BOM），这样 Excel 双击打开中文不乱码。
    Excel 用 openpyxl / xlsxwriter，缺失时抛出中文提示而不是崩栈。
    文件名做净化：中文板块名里的「/」（如「通讯/通信」）会被当成目录分隔符，
    必须替换成下划线，否则下载会失败。
"""

import io
import os
import re

import pandas as pd

import config


def 净化文件名(名: str) -> str:
    """把文件名里的非法字符替换成下划线。"""
    s = str(名 or "导出")
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", s)
    s = s.strip(" .")
    return s or "导出"


def 建议文件名(前缀: str, 后缀: str = "csv") -> str:
    """生成「前缀_YYYYMMDD_HHMMSS.后缀」形式的中文文件名。"""
    from data_fetcher import 北京时间文本
    戳 = 北京时间文本().replace("-", "").replace(":", "").replace(" ", "_")
    return "%s_%s.%s" % (净化文件名(前缀), 戳, 后缀)


def 转CSV字节(df: pd.DataFrame) -> bytes:
    """DataFrame → UTF-8-SIG 编码的 CSV 字节。"""
    if df is None:
        df = pd.DataFrame()
    return df.to_csv(index=False, encoding=config.导出编码).encode(config.导出编码)


def 转Excel字节(df: pd.DataFrame, 工作表名: str = "数据") -> bytes:
    """DataFrame → xlsx 字节。优先 xlsxwriter，退回 openpyxl。"""
    if df is None:
        df = pd.DataFrame()
    缓冲 = io.BytesIO()
    表名 = 净化文件名(工作表名)[:31] or "数据"
    错误 = []
    try:
        with pd.ExcelWriter(缓冲, engine="xlsxwriter") as 写:
            df.to_excel(写, index=False, sheet_name=表名)
        return 缓冲.getvalue()
    except Exception as e:
        错误.append("xlsxwriter：%s" % str(e)[:80])
    缓冲 = io.BytesIO()
    try:
        with pd.ExcelWriter(缓冲, engine="openpyxl") as 写:
            df.to_excel(写, index=False, sheet_name=表名)
        return 缓冲.getvalue()
    except Exception as e:
        错误.append("openpyxl：%s" % str(e)[:80])
    raise RuntimeError("Excel 导出失败（请先安装 xlsxwriter 或 openpyxl）：" + "；".join(错误))


def 导出到目录(df: pd.DataFrame, 前缀: str, 格式: str = "csv") -> tuple:
    """把 DataFrame 写成文件放到 导出目录。返回 (路径, 错误)。"""
    目录 = config.导出目录名
    os.makedirs(目录, exist_ok=True)
    名 = 建议文件名(前缀, 格式)
    路径 = os.path.join(目录, 名)
    try:
        if 格式.lower() == "xlsx":
            with open(路径, "wb") as f:
                f.write(转Excel字节(df))
        else:
            with open(路径, "wb") as f:
                f.write(转CSV字节(df))
        return 路径, ""
    except Exception as e:
        return "", "导出失败：%s" % str(e)[:150]