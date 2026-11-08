# -*- coding: utf-8 -*-
"""
个股微观：盯住一只股票。

上面是价格卡片，中间是 K 线，下面可以切到成交明细或资金流。
K 线用 Qt 自带的蜡烛图控件画，红涨绿跌，和国内软件的习惯一致。

分钟线只保留最近 1970 根，这是新浪接口的硬限制，不是我们截的。
"""

from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

import config
import data_fetcher
from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 分区, 分段选择器, 来源标注, 指标行
from 应用.组件.K线图 import K线图
from 应用.页面.基类 import 页面基

周期列表 = ["日K", "周K", "月K", "60分钟", "30分钟", "15分钟", "5分钟", "1分钟"]

# 复权口径：不复权看真实成交价，前复权看连续涨跌，后复权看长期收益
复权选项 = ["不复权", "前复权", "后复权"]
复权代码 = {"不复权": "", "前复权": "qfq", "后复权": "hfq"}

# 回看多久：只看日/周/月线，分钟线由接口自己决定区间
回看选项 = ["1年", "2年", "3年", "5年", "全部"]
回看天数 = {"1年": 365, "2年": 730, "3年": 1095, "5年": 1825, "全部": 8000}

# 各周期的天数倍率：周线一根顶五天，同样的时间跨度不用多拉
_天数 = {"日K": 1.0, "周K": 1.0, "月K": 1.0}


def _日期范围(周期: str, 回看: str = "3年", 复权: str = "前复权"):
    import datetime as dt

    try:
        止 = data_fetcher.最近交易日()
    except Exception:
        止 = dt.date.today().strftime("%Y-%m-%d")

    if 周期 not in _天数:
        return "", ""  # 分钟类：接口自己决定返回区间

    try:
        末 = dt.datetime.strptime(止, "%Y-%m-%d")
    except Exception:
        末 = dt.datetime.now()
    天 = int(回看天数.get(回看, 1095) * _天数[周期])
    起 = (末 - dt.timedelta(days=天)).strftime("%Y-%m-%d")
    return 起, 止


class 个股微观(页面基):
    def __init__(self):
        super().__init__("个股微观", "输入代码看一只股票的走势、K 线与当日资金情况。")
        self._代码 = "600111"
        self._周期 = "日K"

        栏 = QWidget()
        栏行 = QHBoxLayout(栏)
        栏行.setContentsMargins(0, 0, 0, 0)
        栏行.setSpacing(8)
        栏行.addWidget(QLabel("股票代码"))
        self.输入 = QLineEdit(self._代码)
        self.输入.setMaximumWidth(110)
        self.输入.setPlaceholderText("如 600111")
        栏行.addWidget(self.输入)
        self.按钮 = QPushButton("查询")
        self.按钮.setObjectName("主按钮")
        self.按钮.clicked.connect(self.查询)
        self.输入.returnPressed.connect(self.查询)
        栏行.addWidget(self.按钮)

        栏行.addSpacing(16)
        栏行.addWidget(QLabel("复权"))
        self.复权框 = QComboBox()
        self.复权框.addItems(复权选项)
        self.复权框.setCurrentText("前复权")
        self.复权框.setMinimumWidth(92)
        self.复权框.currentTextChanged.connect(self._条件变了)
        栏行.addWidget(self.复权框)

        栏行.addWidget(QLabel("回看"))
        self.回看框 = QComboBox()
        self.回看框.addItems(回看选项)
        self.回看框.setCurrentText("3年")
        self.回看框.setMinimumWidth(86)
        self.回看框.currentTextChanged.connect(self._条件变了)
        栏行.addWidget(self.回看框)
        栏行.addStretch(1)
        self.加(栏)

        self.选择器 = 分段选择器(周期列表)
        self.选择器.设当前(self._周期)
        self.选择器.选择变化.connect(self._换周期)
        self.加(self.选择器)

        # 指标开关：均线窗口、成交量之外的两个副图，和网页版保持一致的可选性
        显栏 = QWidget()
        显行 = QHBoxLayout(显栏)
        显行.setContentsMargins(0, 0, 0, 0)
        显行.setSpacing(8)
        显行.addWidget(QLabel("均线"))
        self._均线 = list(config.均线默认)
        self._均线框 = []
        for 窗口 in config.均线候选:
            框 = QCheckBox("MA%d" % 窗口)
            框.setChecked(int(窗口) in self._均线)
            框.stateChanged.connect(self._显示变了)
            显行.addWidget(框)
            self._均线框.append((int(窗口), 框))
        显行.addSpacing(12)
        self._MACD框 = QCheckBox("MACD")
        self._MACD框.setChecked(True)
        self._MACD框.stateChanged.connect(self._显示变了)
        显行.addWidget(self._MACD框)
        self._KDJ框 = QCheckBox("KDJ")
        self._KDJ框.setChecked(False)
        self._KDJ框.stateChanged.connect(self._显示变了)
        显行.addWidget(self._KDJ框)
        显行.addStretch(1)
        self.加(显栏)

        self.指标区 = QWidget()
        self.指标布局 = QHBoxLayout(self.指标区)
        self.指标布局.setContentsMargins(0, 0, 0, 0)
        self.加(self.指标区)

        self.图 = K线图()
        self.图.setMinimumHeight(620)
        self.加(self.图)

        self.提示 = 来源标注("正在加载…")
        self.加(self.提示)
        self.加伸缩()

    def showEvent(self, 事件):
        super().showEvent(事件)
        if not getattr(self, "_已加载", False):
            self._已加载 = True
            self.查询()

    def _换周期(self, 周期: str):
        self._周期 = 周期
        # 分钟线的区间由接口决定，回看天数对它无效，干脆置灰免得误导
        if hasattr(self, "回看框"):
            self.回看框.setEnabled(周期 in _天数)
        self.查询()

    def _条件变了(self, _=None):
        """复权或回看天数变了就重新取一次数。"""
        self.查询()

    def _显示变了(self):
        """勾选变了就把窗口交回给 K 线图，它自己决定重建哪些图。"""
        窗口们 = [号 for 号, 框 in self._均线框 if 框.isChecked()]
        if not 窗口们:
            # 一条均线都不选也得留一条，否则图上什么都不画用户会以为坏了
            号, 框 = self._均线框[0]
            框.setChecked(True)
            return
        self._均线 = 窗口们
        self.图.设显示(均线窗口=窗口们,
                       显示MACD=self._MACD框.isChecked(),
                       显示KDJ=self._KDJ框.isChecked())

    def 应用主题变化(self):
        """K 线图的配色是在建图时写死的，切浅色/深色得让它重建一遍。"""
        super().应用主题变化()
        self.图.应用主题变化()

    def 刷新(self) -> int:
        """全局刷新：按输入框里的代码、周期、复权、回看重新查一次。"""
        次数 = super().刷新()
        self.查询()
        return 次数 + 1

    def 查询(self):
        代码 = (self.输入.text() or "").strip() or self._代码
        self._代码 = 代码
        周期 = self._周期
        回看 = self.回看框.currentText() if hasattr(self, "回看框") else "3年"
        复权 = self.复权框.currentText() if hasattr(self, "复权框") else "前复权"
        起, 止 = _日期范围(周期, 回看, 复权)
        self.提示.setText("正在获取 %s 的 %s 数据（%s）…" % (代码, 周期, 复权))
        后台运行(data_fetcher.个股K线, 完成=self._K线到了, 失败=self._失败,
                 参数=(代码, 周期, 起, 止, 复权代码.get(复权, "qfq")))

    def _K线到了(self, 结果):
        try:
            框, 错误, 来源 = 结果
        except Exception:
            self.提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or 框.empty:
            self.图.清空()
            self.提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        self.图.换数据(框, 周期=self._周期)
        self._填指标(框)
        复权 = self.复权框.currentText() if hasattr(self, "复权框") else "前复权"
        回看 = self.回看框.currentText() if hasattr(self, "回看框") else "3年"
        self.提示.setText("数据来源：%s ｜ %s ｜ %s ｜ 回看 %s ｜ 共 %d 根"
                         % (来源 or "新浪", self._周期, 复权, 回看, len(框)))

    def _填指标(self, 框):
        try:
            收盘列 = "收盘" if "收盘" in 框.columns else ("close" if "close" in 框.columns else None)
            if 收盘列 is None:
                return
            列 = 框[收盘列].astype(float)
            最新 = 列.iloc[-1]
            首 = 列.iloc[0]
            涨跌 = (最新 / 首 - 1) * 100 if 首 else 0
            最高 = 列.max()
            最低 = 列.min()
        except Exception:
            return

        while self.指标布局.count():
            项 = self.指标布局.takeAt(0)
            if 项.widget():
                项.widget().deleteLater()

        from 应用.组件.基础 import 指标卡
        for 名称, 值, 注释, 方向 in [
            ("最新价", "%.2f" % 最新, "", 1 if 涨跌 > 0 else (-1 if 涨跌 < 0 else 0)),
            ("区间涨跌", "%+.2f%%" % 涨跌, "%d 根区间" % len(框), 1 if 涨跌 > 0 else (-1 if 涨跌 < 0 else 0)),
            ("区间最高", "%.2f" % 最高, "", 0),
            ("区间最低", "%.2f" % 最低, "", 0),
        ]:
            卡 = 指标卡(名称, 值, 注释, 方向)
            self.指标布局.addWidget(卡)

    def _失败(self, 错误文本: str):
        self.提示.setText("取数失败：%s" % 错误文本)


def 页面() -> QWidget:
    return 个股微观()