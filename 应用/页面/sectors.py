# -*- coding: utf-8 -*-
"""
板块全景：行业 / 概念 / 地域三大类板块的完整清单 + 热力图 + 下钻成分股。

三类口径的区别（这个页面的说明里也写了，免得用户搞混）：
    行业板块 —— 申万分类，最规范，一只股票只归一个行业
    概念板块 —— 新浪分类，一只股票可能属于很多概念
    地域板块 —— 按省份划分

页面从上到下四块：
    热力图   —— 谁在涨谁在跌，面积看成交额，颜色看涨跌幅，点一下直接下钻
    板块列表 —— 完整清单，可排序，双击下钻
    成分股   —— 选中板块后的股票列表
    板块 K 线 —— 选中板块的板块指数 K 线，日/周/月可切
"""

import datetime as dt

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

import config
import data_fetcher
import fetch_sector
from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 分区, 分段选择器, 指标行, 来源标注
from 应用.组件.数据表 import 数据表
from 应用.组件.色标 import 涨跌色标
from 应用.组件.热力图 import 热力图
from 应用.组件.K线图 import K线图
from 应用.页面.基类 import 页面基

类型说明 = {
    "行业板块": "申万行业分类，一只股票只属于一个行业，适合横向比较。",
    "概念板块": "新浪概念分类，一只股票可属于多个概念，适合找题材。",
    "地域板块": "按上市公司所在省份划分。",
}

# 热力图用哪一层板块：和 fetch_sector.热力分类 对应，说明文字写清楚
热力层级 = {
    "行业板块": "申万二级行业",
    "概念板块": "新浪概念板块",
    "地域板块": "省级行政区",
}

# 行业板块的层级细分（申万口径），对应 fetch_sector.行业层级
层级选项 = ["一级行业", "二级行业", "三级行业"]

# 板块 K 线可选的周期。板块指数只有日线，周/月由本地按日历聚合
K线周期 = ["日K", "周K", "月K"]

# 板块 K 线取多少天：日线给三年，周月给更长的区间才够看趋势
K线天数 = {"日K": 1100, "周K": 2600, "月K": 4000}


class 板块全景(页面基):
    def __init__(self):
        super().__init__("板块全景", "全品类板块清单，热力图看冷热，双击或单击查看成分股。")
        self._类型 = "行业板块"
        self._当前板块 = ("", "")
        self._缓存的列表 = {}
        self._缓存的成分 = {}
        self._放大中 = False     # 热力图是否处于铺满页面的放大状态
        self._放回高 = 0         # 放大前的高度，收起时还原
        self._成分代码 = []      # 当前板块的成分股代码，板块 K 线合成时要用
        self._成分表 = None      # 占位表（取数期间带中央转圈），数据到了复用同一张
        self._当前重点 = None    # 选中的是不是 13 个重点板块之一（有申万代码）
        self._K线周期 = "日K"

        # ---- 顶部：类型切换 + 重点板块直达 ----
        头 = QWidget()
        头行 = QHBoxLayout(头)
        头行.setContentsMargins(0, 0, 0, 0)
        头行.setSpacing(8)
        标签 = QLabel("板块类型")
        标签.setObjectName("分区说明")
        头行.addWidget(标签)

        self._类型组 = QButtonGroup(self)
        self._类型组.setExclusive(True)
        for 名 in ["行业板块", "概念板块", "地域板块"]:
            钮 = QPushButton(名)
            钮.setObjectName("主题按钮")
            钮.setCheckable(True)
            钮.setCursor(Qt.PointingHandCursor)
            钮.setChecked(名 == self._类型)
            钮.clicked.connect(lambda _=False, t=名: self._换类型(t))
            self._类型组.addButton(钮)
            头行.addWidget(钮)
        头行.addStretch(1)

        头行.addWidget(QLabel("重点板块"))
        self._重点 = QComboBox()
        self._重点.addItem("选择重点板块…")
        for 模 in config.重点板块:
            self._重点.addItem(模["显示名"])
        self._重点.setMinimumWidth(168)
        self._重点.setToolTip("也可以不选，直接在下面的表里双击任意板块")
        self._重点.activated.connect(self._选重点板块)
        头行.addWidget(self._重点)
        self.加(头)

        self._类型说明 = QLabel(类型说明["行业板块"])
        self._类型说明.setObjectName("分区说明")
        self.加(self._类型说明)

        # ---- 行业层级：只有行业板块才分一级 / 二级 / 三级 ----
        self._层级 = fetch_sector.默认行业层级
        self._层级条 = QWidget()
        层行 = QHBoxLayout(self._层级条)
        层行.setContentsMargins(0, 0, 0, 0)
        层行.setSpacing(8)
        层标签 = QLabel("行业层级")
        层标签.setObjectName("分区说明")
        层行.addWidget(层标签)
        self._层级选择 = 分段选择器(层级选项, 当前=self._层级)
        self._层级选择.选择变化.connect(self._换层级)
        层行.addWidget(self._层级选择)
        层行.addStretch(1)
        self.加(self._层级条)

        # ---- 一、热力图 ----
        标题行 = QWidget()
        标题布局 = QHBoxLayout(标题行)
        标题布局.setContentsMargins(0, 0, 0, 0)
        标题布局.setSpacing(8)
        标题布局.addWidget(
            分区("板块热力图",
                 "每个方块是一个板块，方块越大成交额越高，越红涨得越多、越绿跌得越多；"
                 "右侧色标是颜色对应的涨跌幅刻度。鼠标停上去看涨跌家数，"
                 "单击方块加载成分股，双击或点右侧「放大」把整块铺开放大。"), 1)

        self._展开钮 = QPushButton("放大")
        self._展开钮.setObjectName("主题按钮")
        self._展开钮.setCheckable(True)
        self._展开钮.setCursor(Qt.PointingHandCursor)
        self._展开钮.setToolTip("把热力图放到整个页面高度，再点一下恢复原样")
        self._展开钮.clicked.connect(self._切换展开)
        标题布局.addWidget(self._展开钮, 0, Qt.AlignTop)
        self._热力标题行 = 标题行
        self.加(标题行)

        self._热力 = 热力图(高度=380)
        self._热力.点击板块.connect(self._热力点击)
        self._热力.双击.connect(lambda: self._切换展开(not self._放大中))
        self._色标 = 涨跌色标()

        热力行 = QWidget()
        热力布局 = QHBoxLayout(热力行)
        热力布局.setContentsMargins(0, 0, 0, 0)
        热力布局.setSpacing(4)
        热力布局.addWidget(self._热力, 1)
        热力布局.addWidget(self._色标, 0)
        self._热力行 = 热力行
        self.加(热力行)
        self._热力来源 = 来源标注("正在读取板块涨跌…")
        self.加(self._热力来源)

        # ---- 二、板块列表 ----
        self._列表标题 = 分区("板块列表", "完整清单，双击某一行即可查看成分股，可点表头排序。")
        self.加(self._列表标题)
        self._表 = 数据表(pd.DataFrame(), 高度=280, 标题="板块列表")
        self._表.行双击.connect(self._双击板块)
        self.加(self._表)
        self._列表来源 = 来源标注("离线板块库")
        self.加(self._列表来源)

        # ---- 三、成分股 ----
        self._成分标题 = 分区("成分股", "先在上表里双击一个板块，或直接单击上面的热力图方块。")
        self.加(self._成分标题)
        self._成分区 = QWidget()
        self._成分布局 = QVBoxLayout(self._成分区)
        self._成分布局.setContentsMargins(0, 0, 0, 0)
        self._成分布局.setSpacing(8)
        self._成分提示 = QLabel("还没有选择板块。")
        self._成分提示.setObjectName("空状态")
        self._成分布局.addWidget(self._成分提示)
        self.加(self._成分区)

        # ---- 四、板块 K 线 ----
        K线头 = QWidget()
        K线头行 = QHBoxLayout(K线头)
        K线头行.setContentsMargins(0, 0, 0, 0)
        K线头行.setSpacing(8)
        self._K线标题 = 分区("板块 K 线", "选中板块后这里显示它的板块指数走势，日/周/月可切。")
        K线头行.addWidget(self._K线标题, 1)
        self._周期选择 = 分段选择器(K线周期, 当前="日K")
        self._周期选择.选择变化.connect(self._换周期)
        K线头行.addWidget(self._周期选择, 0, Qt.AlignTop)
        self._K线头 = K线头
        self.加(K线头)

        self._K线 = K线图(标题="板块 K 线", 周期="日K")
        self._K线.setMinimumHeight(480)
        self._K线区 = self._K线
        self.加(self._K线区)
        self._K线来源 = 来源标注("先在表里双击一个板块，或单击上面的热力图方块。")
        self.加(self._K线来源)

        self.加伸缩()

    # ------------------------------------------------------------ 加载

    def _键(self, 类型: str = "", 层级: str = "") -> str:
        """缓存键：行业板块要把层级算进去，否则一级和三级会互相覆盖。"""
        类型 = 类型 or self._类型
        层级 = (层级 or self._层级) if 类型 == "行业板块" else ""
        return "%s|%s" % (类型, 层级)

    def showEvent(self, 事件):
        super().showEvent(事件)
        if self._键() not in self._缓存的列表:
            self._拉列表()
            self._拉热力()

    def 刷新(self) -> int:
        """全局刷新：列表、热力图重拉，选中的板块连成分股和 K 线一起重取。"""
        次数 = super().刷新()
        # 列表本身有一层内存缓存，不清掉的话「重拉」会原样返回旧表
        self._缓存的列表.pop(self._键(), None)
        self._拉列表()
        self._拉热力()
        次数 += 2
        代码, 名称 = self._当前板块
        if 名称:
            self._拉成分股(名称, 重点模=self._当前重点,
                          代码=代码 if self._当前重点 is None else "", 名称=名称)
            次数 += 1
        return 次数

    def _拉列表(self, 类型: str = "", 层级: str = ""):
        类型 = 类型 or self._类型
        层级 = (层级 or self._层级) if 类型 == "行业板块" else ""
        键 = self._键(类型, 层级)
        self._表.换数据(pd.DataFrame())
        self._表.置加载(True, "正在读取「%s」…" % self._键文字(类型, 层级))
        self._列表来源.setText("正在读取「%s」离线库…" % self._键文字(类型, 层级))
        后台运行(fetch_sector.板块列表, 完成=lambda 结果, k=键: self._列表到了(结果, k),
                 失败=self._列表失败, 参数=(类型, 层级))

    def _拉热力(self, 类型: str = "", 层级: str = ""):
        类型 = 类型 or self._类型
        层级 = (层级 or self._层级) if 类型 == "行业板块" else ""
        键 = self._键(类型, 层级)
        self._热力来源.setText("正在计算「%s」涨跌…" % self._键文字(类型, 层级))
        后台运行(fetch_sector.板块涨跌一览, 完成=lambda 结果, k=键: self._热力到了(结果, k),
                 失败=self._热力失败, 参数=(类型, 层级))

    def _键文字(self, 类型: str, 层级: str) -> str:
        return ("%s · %s" % (类型, 层级)) if 类型 == "行业板块" else 类型

    def _列表到了(self, 结果, 键: str = ""):
        try:
            框, 说明, 来源 = 结果
        except Exception:
            self._列表失败("接口返回格式异常")
            return
        if 框 is None or 框.empty:
            self._列表失败(说明 or "离线库为空，请先执行 build_sector.py 建库")
            return
        键 = 键 or self._键()
        self._缓存的列表[键] = (框, 说明, 来源)
        if 键 == self._键():
            self._表.换数据(框)
            self._列表来源.setText("数据来源：%s ｜ %d 个板块 ｜ %s"
                                % (来源 or "离线库", len(框), 说明 or ""))

    def _列表失败(self, 错误):
        self._表.置加载(False)
        self._列表来源.setText("读取失败：%s" % 错误)

    def _热力到了(self, 结果, 键: str = ""):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            self._热力失败("接口返回格式异常")
            return
        if 框 is None or 框.empty:
            self._热力失败(错误 or "没有取到板块涨跌数据")
            return
        项 = []
        for _, 行 in 框.iterrows():
            项.append({
                "名称": str(行.get("板块名称", "")),
                "涨跌幅": float(行.get("涨跌幅", 0) or 0),
                "面积": float(行.get("成交额", 0) or 0),
                "说明": "成分 %d 只，上涨 %d 家，下跌 %d 家" % (
                    int(行.get("成分数", 0) or 0),
                    int(行.get("上涨家数", 0) or 0),
                    int(行.get("下跌家数", 0) or 0)),
            })
        键 = 键 or self._键()
        if 键 != self._键():
            return
        self._热力.换数据(
            项, "面积按成交额压缩显示 · 颜色按涨跌幅深浅 · 浅色为零点附近")
        self._热力来源.setText(
            "数据来源：%s ｜ %d 个%s ｜ 颜色上限 ±%.0f%%"
            % (来源 or "离线库", len(项), self._热力层级文字(), 5))

    def _热力层级文字(self) -> str:
        if self._类型 == "行业板块":
            return "申万%s" % self._层级
        return 热力层级.get(self._类型, "板块")

    def _热力失败(self, 错误):
        self._热力.清空()
        self._热力来源.setText("热力图取数失败：%s" % 错误)

    # ------------------------------------------------------------ 交互

    def _换类型(self, 类型: str):
        self._类型 = 类型
        self._类型说明.setText(类型说明.get(类型, ""))
        # 行业层级只在行业板块下有意义，切到概念/地域就收起来
        self._层级条.setVisible(类型 == "行业板块")
        for 钮 in self._类型组.buttons():
            钮.setChecked(钮.text() == 类型)
        键 = self._键(类型)
        if 键 in self._缓存的列表:
            框, 说明, 来源 = self._缓存的列表[键]
            self._表.换数据(框)
            self._列表来源.setText("数据来源：%s ｜ %d 个板块 ｜ %s"
                                % (来源 or "离线库", len(框), 说明 or ""))
        else:
            self._拉列表(类型)
        self._拉热力(类型)

    def _换层级(self, 层级: str):
        """行业层级切换：板块列表和热力图都跟着换一层。"""
        if 层级 not in 层级选项:
            return
        self._层级 = 层级
        键 = self._键("行业板块", 层级)
        if 键 in self._缓存的列表:
            框, 说明, 来源 = self._缓存的列表[键]
            self._表.换数据(框)
            self._列表来源.setText("数据来源：%s ｜ %d 个板块 ｜ %s"
                                % (来源 or "离线库", len(框), 说明 or ""))
        else:
            self._拉列表("行业板块", 层级)
        self._拉热力("行业板块", 层级)

    def _选重点板块(self, 序号: int):
        if 序号 <= 0:
            return
        模 = config.重点板块[序号 - 1]
        self._拉成分股(模["显示名"], 模)

    def _双击板块(self, 行号: int):
        框 = self._表.数据()
        if 框.empty or 行号 >= len(框):
            return
        行 = 框.iloc[行号]
        代码 = str(行.get("板块代码", ""))
        名称 = str(行.get("板块名称", ""))
        if not 名称:
            return
        self._当前板块 = (代码, 名称)
        self._拉成分股(名称, None, 代码, 名称)

    def _热力点击(self, 名称: str):
        """点热力图方块：离线库以名称为主键，所以代码也用名称。"""
        if not 名称:
            return
        self._当前板块 = (名称, 名称)
        self._拉成分股(名称, None, 名称, 名称)

    # ------------------------------------------------------------ 放大 / 收起

    def _切换展开(self, 展开: bool):
        """
        把热力图铺开到整页高度，或者收回原样。

        做法：放大时先把下面三块（列表标题 / 列表 / 来源）和成分股区藏起来，
        再让热力图自己把高度涨到「视口高度减一点」。
        高度变化交给 热力图.过渡到高度 做插值，方块会从旧位置平滑长到新位置，
        不是瞬间跳一下。
        """
        展开 = bool(展开)
        if 展开 == self._放大中:
            return
        self._放大中 = 展开
        self._展开钮.setChecked(展开)
        self._展开钮.setText("还原" if 展开 else "放大")

        for 件 in (self._列表标题, self._表, self._列表来源,
                   self._成分标题, self._成分区,
                   self._K线头, self._K线区, self._K线来源):
            件.setVisible(not 展开)

        if 展开:
            self._放回高 = max(380, self._热力.height())
            视口 = max(self.viewport().height(), 480)
            # 留 150px 给页面标题、分区标题和底部说明，别把热力图顶到屏幕外
            目标 = max(460, 视口 - 150)
            self._热力.过渡到高度(目标, 300)
            self.verticalScrollBar().setValue(0)
        else:
            目标 = self._放回高 or 380
            self._热力.过渡到高度(目标, 260)

        self._色标.update()

    # ------------------------------------------------------------ 成分股

    def _拉成分股(self, 标题: str, 重点模=None, 代码: str = "", 名称: str = ""):
        self._清空成分()
        self._成分代码 = []
        self._当前板块 = (代码 or 名称, 标题)
        self._当前重点 = 重点模
        self._成分标题.设说明("正在获取「%s」的成分股…" % 标题)
        # 先摆一张空表并让它转圈，用户看到的是「表格在装数据」，而不是一片空白
        self._成分表 = 数据表(None, 高度=340, 标题="%s 成分股" % 标题)
        self._成分表.置加载(True, "正在获取「%s」的成分股…" % 标题)
        self._成分布局.addWidget(self._成分表)

        # 板块 K 线先摆个占位，等成分股回来拿到代码再拉（合成要用成分股）
        self._K线标题.设说明("正在获取「%s」的板块走势…" % 标题)
        self._K线来源.setText("正在获取「%s」的板块 K 线…" % 标题)

        if 重点模 is not None:
            后台运行(fetch_sector.重点板块成分股, 完成=self._成分到了,
                     失败=self._成分失败, 参数=(重点模["显示名"],))
        else:
            后台运行(fetch_sector.板块成分股, 完成=self._成分到了,
                     失败=self._成分失败,
                     参数=(self._类型, 代码, 名称))

    def _成分到了(self, 结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            self._成分失败("接口返回格式异常")
            return
        # 占位表先摘下来，清完其它占位内容再挂回去，这样表格位置不会跳动
        占位 = self._成分表
        if 占位 is not None:
            self._成分布局.removeWidget(占位)
            占位.setParent(None)
        self._清空成分()
        if 框 is None or 框.empty:
            self._成分失败(错误 or "这个板块没有取到成分股")
            return

        名称 = ""
        for 候选 in ("所属板块", "板块名称", "显示名"):
            if 候选 in 框.columns and len(框):
                名称 = str(框.iloc[0][候选])
                break
        名称 = 名称 or (self._当前板块[1] if self._当前板块 else "板块")
        self._成分标题.设说明("共 %s 只 · 数据来源：%s"
                            % ("{:,}".format(len(框)), 来源 or "离线库"))

        涨的 = 跌的 = 0
        if "涨跌幅" in 框.columns:
            值 = pd.to_numeric(框["涨跌幅"], errors="coerce").dropna()
            涨的 = int((值 > 0).sum())
            跌的 = int((值 < 0).sum())
        均涨 = ""
        if "涨跌幅" in 框.columns:
            值 = pd.to_numeric(框["涨跌幅"], errors="coerce").dropna()
            if len(值):
                均涨 = "%+.2f%%" % float(值.mean())

        self._成分布局.addWidget(指标行([
            ("成分股数量", "%s 只" % "{:,}".format(len(框)), 名称, 0),
            ("平均涨跌幅", 均涨 or "—", "等权平均", 0),
            ("上涨家数", "{} 只".format(涨的), "", 0),
            ("下跌家数", "{} 只".format(跌的), "", 0),
        ], 每行=4))

        表 = 占位 or 数据表(None, 高度=340, 标题="%s 成分股" % 名称)
        表.换数据(框)          # 换数据会顺手收掉中央的转圈
        self._成分布局.addWidget(表)
        self._成分表 = 表

        # 拿到成分股代码，接着拉板块 K 线（合成降级要用）
        if "代码" in 框.columns:
            self._成分代码 = [str(x) for x in 框["代码"].tolist() if str(x).strip()]
        self._拉板块K线(名称)

    def _成分失败(self, 错误):
        self._清空成分()
        self._成分标题.设说明("没取到成分股")
        提示 = QLabel("成分股没取到：%s" % 错误)
        提示.setObjectName("空状态")
        提示.setWordWrap(True)
        self._成分布局.addWidget(提示)
        # 成分股没有也不代表板块指数没有，K 线照样试一次
        self._拉板块K线(self._当前板块[1] if self._当前板块 else "板块")

    def _清空成分(self):
        self._成分表 = None
        while self._成分布局.count():
            项 = self._成分布局.takeAt(0)
            件 = 项.widget()
            if 件 is not None:
                件.deleteLater()
            elif 项.layout() is not None:
                _清空(项.layout())

    # ------------------------------------------------------------ 板块 K 线

    def _换周期(self, 周期: str):
        """切换日/周/月线：重新拉一次当前板块的 K 线。"""
        if not 周期 or 周期 == self._K线周期:
            return
        self._K线周期 = 周期
        名称 = self._当前板块[1] if self._当前板块 else ""
        if not 名称:
            return
        self._拉板块K线(名称)

    def _拉板块K线(self, 名称: str):
        if not 名称:
            return
        周期 = self._K线周期
        self._K线标题.设说明("正在获取「%s」的%s…" % (名称, 周期))
        self._K线来源.setText("正在获取「%s」的%s…" % (名称, 周期))

        # 板块类型：同花顺只认「概念板块」和「行业板块」两种
        类型 = "概念板块" if self._类型 == "概念板块" else "行业板块"

        # 申万代码只有重点板块才有，普通板块靠同花顺同名指数或成分股合成
        申万 = ""
        模 = getattr(self, "_当前重点", None)
        if 模:
            代码表 = 模.get("申万代码") or []
            if 代码表:
                申万 = str(代码表[0])

        结束 = data_fetcher.北京时间().strftime("%Y-%m-%d")
        开始 = (data_fetcher.北京时间()
                - dt.timedelta(days=K线天数.get(周期, 1100))).strftime("%Y-%m-%d")

        后台运行(data_fetcher.板块K线, 完成=self._K线到了, 失败=self._K线失败,
                 参数=(名称, 类型, 周期, 开始, 结束),
                 关键字={"申万代码": 申万, "成分股代码": list(self._成分代码)[:10]})

    def _K线到了(self, 结果):
        try:
            框, 错误, 来源, 性质 = 结果
        except Exception:
            self._K线失败("接口返回格式异常")
            return
        名称 = self._当前板块[1] if self._当前板块 else "板块"
        if 框 is None or 框.empty:
            self._K线.清空("暂无数据")
            self._K线标题.设说明("「%s」没取到 K 线" % 名称)
            self._K线来源.setText("取不到「%s」的板块 K 线：%s" % (名称, 错误 or "接口返回为空"))
            return
        标题 = "%s %s" % (名称, self._K线周期)
        self._K线.换数据(框, 标题=标题, 周期=self._K线周期)
        性质文字 = "板块指数" if 性质 == "板块指数" else "合成板块K线（成分股等权，非官方指数）"
        self._K线标题.设说明("%s ｜ %s ｜ 共 %d 根" % (标题, 性质文字, len(框)))
        self._K线来源.setText(
            "数据来源：%s ｜ 数据性质：%s ｜ 滚轮缩放，左键拖动，双击复位"
            % (来源 or "未知", 性质文字))

    def _K线失败(self, 错误文本: str):
        self._K线.清空("取数失败")
        self._K线来源.setText("板块 K 线取数失败：%s" % 错误文本)


def 当前类型(页) -> str:
    return 页._类型


def _清空(布局):
    while 布局.count():
        项 = 布局.takeAt(0)
        件 = 项.widget()
        if 件 is not None:
            件.deleteLater()
        elif 项.layout() is not None:
            _清空(项.layout())


def 页面() -> QWidget:
    return 板块全景()