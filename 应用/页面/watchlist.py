# -*- coding: utf-8 -*-
"""
自选监控：自己盯的那几只。

自选池存在 `数据/自选池.json` 里，关掉软件也不会丢。
每只股票的实时价格从全市场快照里筛，不单独发请求，
所以就算加到几十只也不会变慢。

加股票只要输代码，删股票点表格下方的按钮。
"""

import json
import os

import pandas as pd
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

import config
import data_fetcher
from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 分区, 来源标注
from 应用.组件.柱状图 import 柱状图
from 应用.组件.数据表 import 数据表
from 应用.页面.基类 import 页面基

# 一次最多加多少只：太多柱状图会挤成一团，也怕手抖粘进一大段
单次上限 = 20


def _读自选() -> list:
    路径 = getattr(config, "自选文件", os.path.join(config.数据目录, "自选池.json"))
    try:
        with open(路径, "r", encoding="utf-8") as 文件:
            内容 = json.load(文件)
        if isinstance(内容, list):
            return [str(项) for 项 in 内容]
        if isinstance(内容, dict) and "代码" in 内容:
            return [str(项) for 项 in 内容["代码"]]
    except Exception:
        pass
    return ["600111", "300750", "002415", "688981", "601012"]


def _写自选(代码列表: list):
    路径 = getattr(config, "自选文件", os.path.join(config.数据目录, "自选池.json"))
    try:
        目录 = os.path.dirname(路径)
        if 目录 and not os.path.isdir(目录):
            os.makedirs(目录, exist_ok=True)
        with open(路径, "w", encoding="utf-8") as 文件:
            json.dump(代码列表, 文件, ensure_ascii=False, indent=2)
        return ""
    except Exception as 错:
        return "保存失败：%s" % 错


class 自选监控(页面基):
    def __init__(self):
        super().__init__("自选监控", "把自己关注的股票放在一起，一屏看完全部实时状态。")
        self._代码 = _读自选()

        栏 = QWidget()
        栏行 = QHBoxLayout(栏)
        栏行.setContentsMargins(0, 0, 0, 0)
        栏行.setSpacing(8)
        栏行.addWidget(QLabel("添加股票代码"))
        self.输入 = QLineEdit()
        self.输入.setMaximumWidth(280)
        self.输入.setPlaceholderText("可一次贴多个，用空格或逗号隔开")
        self.输入.returnPressed.connect(self._添加)
        栏行.addWidget(self.输入)
        加按钮 = QPushButton("添加到自选")
        加按钮.setObjectName("主按钮")
        加按钮.clicked.connect(self._添加)
        栏行.addWidget(加按钮)
        栏行.addStretch(1)
        栏行.addWidget(QLabel("删除代码"))
        self.删输入 = QLineEdit()
        self.删输入.setMaximumWidth(120)
        self.删输入.setPlaceholderText("如 600519")
        栏行.addWidget(self.删输入)
        删按钮 = QPushButton("删除")
        删按钮.clicked.connect(self._删除)
        栏行.addWidget(删按钮)
        self.加(栏)

        self.加(分区("自选股列表", "价格取自全市场快照，红涨绿跌。"))
        self.表 = 数据表(None, 高度=380, 标题="自选股")
        self.加(self.表)
        self.提示 = 来源标注("正在加载…")
        self.加(self.提示)

        self.加(分区("自选涨跌对比", "自己这几只谁强谁弱，一眼看出来。"))
        self.柱 = 柱状图("自选股涨跌幅（%）", 高度=300)
        self.加(self.柱)
        self._柱说明 = 来源标注("等这批行情回来就有了。")
        self.加(self._柱说明)

        self.加伸缩()
        self._已加载 = False

    def showEvent(self, 事件):
        super().showEvent(事件)
        if not self._已加载:
            self._已加载 = True
            self.刷新()

    def _添加(self):
        原样 = (self.输入.text() or "").strip()
        if not 原样:
            self.提示.setText("请输入股票代码")
            return
        # 支持一次贴多只：逗号、空格、分号、顿号都当分隔符
        片段们 = 原样.replace(",", " ").replace("，", " ").replace(";", " ") \
            .replace("；", " ").replace("、", " ").split()
        新码 = []
        for 片 in 片段们:
            码 = "".join(字 for 字 in 片 if 字.isdigit())
            if 码 and 码 not in self._代码 and 码 not in 新码:
                新码.append(码)
        if not 新码:
            self.提示.setText("这些代码要么不合法，要么已经在自选里了")
            return
        if len(新码) > 单次上限:
            新码 = 新码[:单次上限]
        self._代码.extend(新码)
        self._写回()
        self.输入.clear()
        记 = self.提示.text()
        self.刷新()
        if len(新码) > 1:
            self._柱说明.setText("刚加入 %d 只：%s" % (len(新码), "、".join(新码)))

    def _删除(self):
        代码 = (self.删输入.text() or "").strip()
        代码 = "".join(字 for 字 in 代码 if 字.isdigit())
        if not 代码:
            self.提示.setText("请输入要删除的股票代码")
            return
        if 代码 not in self._代码:
            self.提示.setText("%s 不在自选里" % 代码)
            return
        self._代码 = [项 for 项 in self._代码 if 项 != 代码]
        self._写回()
        self.删输入.clear()
        self.刷新()

    def _写回(self):
        错误 = _写自选(self._代码)
        if 错误:
            self.提示.setText(错误)

    def 刷新(self):
        if not self._代码:
            self.表.换数据(None)
            self.提示.setText("自选池是空的，先在上面加几只股票")
            return
        self.提示.setText("正在获取全市场快照…")
        self.表.置加载(True, "正在获取全市场快照…")
        后台运行(data_fetcher.全市场快照, 完成=self._到了, 失败=self._失败)

    def _到了(self, 结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            self.表.置加载(False)
            self.提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or 框.empty:
            self.表.换数据(None)
            self.提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        代码列 = "代码" if "代码" in 框.columns else 框.columns[0]
        子集 = 框[框[代码列].astype(str).isin(set(self._代码))]
        if 子集.empty:
            self.表.换数据(None)
            self.提示.setText("自选里的代码都没在快照中找到，可能代码写错了")
            return
        想显示 = ["代码", "名称", "最新价", "涨跌额", "涨跌幅", "换手率",
                  "市盈率", "市净率", "总市值", "成交额"]
        列 = [列名 for 列名 in 想显示 if 列名 in 子集.columns]
        子集 = 子集[列].copy()
        # 按自选的先后顺序排，而不是按市场顺序
        序号 = {代码: 序 for 序, 代码 in enumerate(self._代码)}
        子集["_序"] = 子集["代码"].astype(str).map(序号).fillna(999)
        子集 = 子集.sort_values("_序").drop(columns=["_序"]).reset_index(drop=True)
        self.表.换数据(子集)
        self.提示.setText("数据来源：%s ｜ 自选 %d 只 ｜ 快照共 %d 只" % (来源 or "新浪", len(子集), len(框)))
        self._画柱(子集)

    def _画柱(self, 子集):
        """把自选股按涨跌幅画成柱状图，红涨绿跌，和表格一个口径。"""
        if "涨跌幅" not in 子集.columns:
            self.柱.清空("这批数据里没有涨跌幅")
            return
        值 = pd.to_numeric(子集["涨跌幅"], errors="coerce")
        序号 = [i for i, v in enumerate(值.tolist()) if v == v]
        if not 序号:
            self.柱.清空("涨跌幅全是空值")
            return
        名 = []
        for i in 序号:
            行 = 子集.iloc[i]
            标签 = str(行.get("名称", "")) or str(行.get("代码", ""))
            # 新浪的简称里常带全角空格（「五 粮 液」），画到柱子上要清掉
            名.append(标签.replace(" ", "").replace("\u3000", "")[:6])
        数 = [float(值.iloc[i]) for i in 序号]
        self.柱.换数据(名, 数, 标题="自选股涨跌幅（%）", 小数位=2, 轴标题="涨跌幅(%)")
        最好 = 数.index(max(数))
        最差 = 数.index(min(数))
        self._柱说明.setText("共 %d 只（红涨绿跌）｜ 最强 %s %+.2f%% ｜ 最弱 %s %+.2f%%"
                            % (len(数), 名[最好], 数[最好], 名[最差], 数[最差]))

    def _失败(self, 错误文本: str):
        self.表.置加载(False)
        self.提示.setText("取数失败：%s" % 错误文本)


def 页面() -> QWidget:
    return 自选监控()