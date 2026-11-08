# -*- coding: utf-8 -*-
"""
全局总览：一进软件就能看懂今天市场怎么样。

三块内容，从上往下：
    1. 主要指数 —— 上证、深证、创业板、科创50 等，涨跌幅上红下绿
    2. 市场温度 —— 涨跌家数、涨停跌停、两市成交额
    3. 指数明细表 —— 想看具体数字可以展开看

数据是分两批在后台拉的：指数很快（一两秒），全市场五千多只要十几秒，
所以先出指数，市场温度那块先显示「正在统计」，算完自动填进去。
"""

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

import data_fetcher
import fetch_sector
from 应用 import 主题
from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 分区, 指标行, 来源标注, 空状态
from 应用.组件.柱状图 import 柱状图
from 应用.组件.色标 import 涨跌色标
from 应用.组件.数据表 import 数据表
from 应用.组件.热力图 import 热力图
from 应用.页面.基类 import 页面基

# 涨跌幅分布的 13 个档位，从左到右：跌停 → 平盘 → 涨停
档名 = ["跌停", "-9.8~-7", "-7~-5", "-5~-3", "-3~-1", "-1~0", "平盘",
        "0~1", "1~3", "3~5", "5~7", "7~9.8", "涨停"]
平盘档 = 6


def _分档(值序列) -> list:
    计数 = [0] * len(档名)
    for v in 值序列:
        if v <= -9.8:
            计数[0] += 1
        elif v < -7:
            计数[1] += 1
        elif v < -5:
            计数[2] += 1
        elif v < -3:
            计数[3] += 1
        elif v < -1:
            计数[4] += 1
        elif v < 0:
            计数[5] += 1
        elif v == 0:
            计数[平盘档] += 1
        elif v < 1:
            计数[7] += 1
        elif v < 3:
            计数[8] += 1
        elif v < 5:
            计数[9] += 1
        elif v < 7:
            计数[10] += 1
        elif v < 9.8:
            计数[11] += 1
        else:
            计数[12] += 1
    return 计数


def _混色(色1: str, 色2: str, 比例: float) -> str:
    """按比例从 色1 过渡到 色2，返回 #rrggbb。比例 0 得 色1，1 得 色2。"""
    a, b = QColor(色1), QColor(色2)
    比例 = max(0.0, min(1.0, float(比例)))
    return "#%02x%02x%02x" % (
        int(a.red() + (b.red() - a.red()) * 比例),
        int(a.green() + (b.green() - a.green()) * 比例),
        int(a.blue() + (b.blue() - a.blue()) * 比例),
    )


def _档色(盘) -> list:
    """跌的六档由深绿渐变到浅绿，平盘灰，涨的六档由浅红渐变到深红。"""
    浅 = 盘["卡片"]
    色们 = []
    for i in range(len(档名)):
        if i == 平盘档:
            色们.append(盘["文字3"])
        elif i < 平盘档:
            距离 = 平盘档 - i            # 1 最靠近 0，6 是跌停
            色们.append(_混色(浅, 盘["跌"], 0.20 + 0.13 * 距离))
        else:
            距离 = i - 平盘档
            色们.append(_混色(浅, 盘["涨"], 0.20 + 0.13 * 距离))
    return 色们


class 全局总览(页面基):
    def __init__(self):
        super().__init__("全局总览", "主要指数、市场温度与整体涨跌分布，打开即看当日全貌。")
        self._已加载 = False
        self._放大中 = False      # 热力图是否处于铺满页面的放大状态
        self._放回高 = 0          # 放大前的高度，收起时还原

        # ---- 指数卡片 ----
        self.加(分区("主要指数", "红涨绿跌，数据来自新浪行情快照。"))
        self._指数区 = QWidget()
        self._指数布局 = QVBoxLayout(self._指数区)
        self._指数布局.setContentsMargins(0, 0, 0, 0)
        self._指数布局.setSpacing(8)
        self._指数提示 = QLabel("正在获取指数行情…")
        self._指数提示.setObjectName("空状态")
        self._指数布局.addWidget(self._指数提示)
        self.加(self._指数区)

        # ---- 市场温度 ----
        self.加(分区("市场温度", "全市场个股涨跌家数与成交额，统计口径为全部 A 股。"))
        self._温度区 = QWidget()
        self._温度布局 = QVBoxLayout(self._温度区)
        self._温度布局.setContentsMargins(0, 0, 0, 0)
        self._温度布局.setSpacing(8)
        self._温度提示 = QLabel("正在统计全市场数据，约需十秒…")
        self._温度提示.setObjectName("空状态")
        self._温度布局.addWidget(self._温度提示)
        self.加(self._温度区)

        # ---- 涨跌分布 ----
        self.加(分区("涨跌分布", "全部 A 股按涨跌幅分成 13 档，柱子高低就是落在这一档的股票家数。"
                                 "左右两头翘说明两极分化，中间高说明多数小幅波动。"))
        self._分布图 = 柱状图("全市场涨跌幅分布（家数）", 高度=290)
        self.加(self._分布图)
        self._分布说明 = 来源标注("等待全市场数据…")
        self.加(self._分布说明)

        # ---- 板块热力图 ----
        标题行 = QWidget()
        标题布局 = QHBoxLayout(标题行)
        标题布局.setContentsMargins(0, 0, 0, 0)
        标题布局.setSpacing(8)
        标题布局.addWidget(
            分区("板块热力图",
                 "按申万二级行业看冷热，面积是成交额，颜色是涨跌幅，右侧色标是刻度。"
                 "鼠标停上去看涨跌家数；双击方块或点右边「放大」把整块铺开，再双击收复。"
                 "要看成分股，到「板块全景」里点。"), 1)
        self._展开钮 = QPushButton("放大")
        self._展开钮.setObjectName("主题按钮")
        self._展开钮.setCheckable(True)
        self._展开钮.setCursor(Qt.PointingHandCursor)
        self._展开钮.setToolTip("把热力图铺满整页，再点一下恢复原样")
        self._展开钮.clicked.connect(self._切换展开)
        标题布局.addWidget(self._展开钮, 0, Qt.AlignTop)
        self._热力标题行 = 标题行
        self.加(标题行)

        self._热力行 = QWidget()
        热力布局 = QHBoxLayout(self._热力行)
        热力布局.setContentsMargins(0, 0, 0, 0)
        热力布局.setSpacing(4)
        self._热力 = 热力图(高度=320)
        self._热力.双击.connect(lambda: self._切换展开(not self._放大中))
        热力布局.addWidget(self._热力, 1)
        self._色标 = 涨跌色标()
        热力布局.addWidget(self._色标, 0)
        self.加(self._热力行)
        self._热力说明 = 来源标注("等待全市场数据算完…")
        self.加(self._热力说明)

        # ---- 指数明细表 ----
        self._表标题 = 分区("指数明细", "含今开、最高、最低、成交额，点表头可排序。")
        self.加(self._表标题)
        self._表 = 数据表(pd.DataFrame(), 高度=250, 标题="主要指数")
        self.加(self._表)
        self._来源 = 来源标注("新浪", "指数快照约为实时值")
        self.加(self._来源)

        self.加伸缩()

    # ------------------------------------------------------------ 加载

    def _切换展开(self, 展开: bool):
        """
        把热力图铺开到整页高度，或者收回原样。

        和板块全景页同一套做法：放大时先把下面的「指数明细」藏起来，
        再让热力图把高度涨到「视口高度减一点」。高度变化交给
        热力图.过渡到高度 做插值，方块会从旧位置平滑长到新位置。
        """
        展开 = bool(展开)
        if 展开 == self._放大中:
            return
        self._放大中 = 展开
        self._展开钮.setChecked(展开)
        self._展开钮.setText("还原" if 展开 else "放大")

        for 件 in (self._表标题, self._表, self._来源):
            件.setVisible(not 展开)

        if 展开:
            self._放回高 = max(320, self._热力.height())
            视口 = max(self.viewport().height(), 480)
            # 页面标题、分区标题、坐上面的分布图都还占地方，留 150px 给它
            目标 = max(460, 视口 - 150)
            self._热力.过渡到高度(目标, 300)
            self.verticalScrollBar().setValue(0)
        else:
            self._热力.过渡到高度(self._放回高 or 320, 260)

        self._色标.update()

    def showEvent(self, 事件):
        super().showEvent(事件)
        if not self._已加载:
            self._已加载 = True
            self._拉指数()
            self._拉全市场()
            # 热力图要复用全市场快照，排在全市场之后发，第二次直接走缓存
            self._拉热力图()

    def _拉指数(self):
        self._表.置加载(True, "正在获取主要指数…")
        后台运行(data_fetcher.重点关注指数, 完成=self._指数到了, 失败=self._指数失败)

    def 刷新(self) -> int:
        """全局刷新：指数、全市场快照、热力图三样都重拉一遍。"""
        次数 = super().刷新()
        self._拉指数()
        self._拉全市场()
        # 热力图复用全市场快照，同样排在全市场后面发
        self._拉热力图()
        return 次数 + 3

    def _拉全市场(self):
        后台运行(data_fetcher.全市场快照, 完成=self._温度到了, 失败=self._温度失败)

    def _拉热力图(self):
        self._热力说明.setText("正在按行业汇总涨跌…")
        后台运行(fetch_sector.板块涨跌一览, 完成=self._热力到了, 失败=self._热力失败,
                 参数=("行业板块",))

    def _热力到了(self, 结果):
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
        self._热力.换数据(项, "面积按成交额压缩显示 · 颜色按涨跌幅深浅")
        self._热力说明.setText("数据来源：%s ｜ %d 个申万二级行业 ｜ 颜色上限 ±5%%"
                             % (来源 or "离线库", len(项)))

    def _热力失败(self, 错误):
        self._热力.清空()
        self._热力说明.setText("板块热力图没取到：%s" % 错误)

    # ------------------------------------------------------------ 回调

    def _指数到了(self, 结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            self._指数失败("指数接口返回格式异常")
            return

        if 框 is None or 框.empty:
            self._指数失败(错误 or "没有取到指数数据")
            return

        # 同一个指数偶尔会以两个代码重复出现（沪深300 有 sh000300 和 sz399300），按名称去重
        if "名称" in 框.columns:
            框 = 框.drop_duplicates(subset=["名称"], keep="first").reset_index(drop=True)

        while self._指数布局.count():
            项 = self._指数布局.takeAt(0)
            件 = 项.widget()
            if 件 is not None:
                件.deleteLater()
            elif 项.layout() is not None:
                _清空布局(项.layout())

        # 卡片：取前 8 个主要指数
        项列表 = []
        for _, 行 in 框.head(8).iterrows():
            涨跌 = _数(行.get("涨跌幅"))
            项列表.append((
                str(行.get("名称", "")),
                "%.2f" % _数(行.get("最新价")),
                "%+.2f%%  %+.2f" % (涨跌, _数(行.get("涨跌额"))),
                1 if 涨跌 > 0 else (-1 if 涨跌 < 0 else 0),
            ))
        self._指数布局.addWidget(指标行(项列表, 每行=4))

        self._表.换数据(框)
        self._来源.setText("数据来源：%s ｜ 更新于 %s" % (
            来源 or "新浪", data_fetcher.北京时间文本()))

    def _指数失败(self, 错误):
        self._表.置加载(False)
        self._指数提示.setText("指数行情没取到：%s" % 错误)

    def _温度到了(self, 结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            self._温度失败("全市场接口返回格式异常")
            return

        if 框 is None or 框.empty:
            self._温度失败(错误 or "没有取到全市场数据")
            return

        涨跌列 = None
        for 候选 in ("涨跌幅", "涨跌幅(%)", "涨幅"):
            if 候选 in 框.columns:
                涨跌列 = 候选
                break
        if 涨跌列 is None:
            self._温度失败("返回数据里没有涨跌幅列")
            return

        值 = pd.to_numeric(框[涨跌列], errors="coerce").dropna()
        总数 = len(值)
        上涨 = int((值 > 0).sum())
        下跌 = int((值 < 0).sum())
        平盘 = 总数 - 上涨 - 下跌
        涨停 = int((值 >= 9.8).sum())
        跌停 = int((值 <= -9.8).sum())

        成交额 = 0.0
        for 候选 in ("成交额", "成交金额"):
            if 候选 in 框.columns:
                成交额 = float(pd.to_numeric(框[候选], errors="coerce").fillna(0).sum())
                break

        while self._温度布局.count():
            项 = self._温度布局.takeAt(0)
            件 = 项.widget()
            if 件 is not None:
                件.deleteLater()
            elif 项.layout() is not None:
                _清空布局(项.layout())

        占比 = 上涨 / 总数 * 100 if 总数 else 0
        项列表 = [
            ("上涨家数", "%s" % "{:,}".format(上涨), "占全部 A 股 %.1f%%" % 占比, 1 if 上涨 else 0),
            ("下跌家数", "%s" % "{:,}".format(下跌), "占全部 A 股 %.1f%%" % (下跌 / 总数 * 100 if 总数 else 0),
             -1 if 下跌 else 0),
            ("平盘家数", "%s" % "{:,}".format(平盘), "涨跌幅为 0", 0),
            ("涨停 / 跌停", "%d / %d" % (涨停, 跌停), "按涨跌幅 ≥9.8% 粗算", 0),
            ("两市成交额", "%.0f 亿" % (成交额 / 1e8), "全部 A 股合计", 0),
            ("统计只数", "%s" % "{:,}".format(总数), "已剔除停牌与无报价", 0),
        ]
        self._温度布局.addWidget(指标行(项列表, 每行=3))

        # 涨跌幅分布：13 档，绿→灰→红
        计数 = _分档(值.tolist())
        try:
            self._分布图.换数据(档名, 计数, 逐柱颜色=_档色(主题.当前调色板()),
                                小数位=0, 轴标题="家数")
            最多档 = max(range(len(计数)), key=lambda i: 计数[i])
            self._分布说明.setText(
                "数据来源：%s ｜ 共 %d 只 ｜ 最多的一档是「%s」共 %d 只 ｜ 跌停 %d 家，涨停 %d 家" % (
                    来源 or "新浪", 总数, 档名[最多档], 计数[最多档], 计数[0], 计数[12]))
        except Exception as 错:
            self._分布说明.setText("涨跌分布画不出来：%s" % 错)

    def _温度失败(self, 错误):
        self._温度提示.setText("全市场统计没成功：%s" % 错误)


def _数(值) -> float:
    try:
        return float(值)
    except Exception:
        return 0.0


def _清空布局(布局):
    while 布局.count():
        项 = 布局.takeAt(0)
        件 = 项.widget()
        if 件 is not None:
            件.deleteLater()
        elif 项.layout() is not None:
            _清空布局(项.layout())


def 页面() -> QWidget:
    return 全局总览()