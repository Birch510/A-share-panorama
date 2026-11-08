# -*- coding: utf-8 -*-
"""
K 线图：QtCharts 原生绘制，不走浏览器。

结构是上下三张图：
    上面 —— 蜡烛图（红涨绿跌）+ 均线
    中间 —— 成交量柱（颜色跟当天涨跌一致）
    下面 —— MACD 副图（红绿柱 + DIF / DEA 两条线）

交互：
    滚轮 —— 以鼠标位置为中心放大缩小
    按住左键拖动 —— 左右平移
    双击 —— 复位到最近 300 根
    悬停 —— 光标压在 K 线上，旁边浮出这根的时间段和开高低收

为什么整张图只建一次、缩放只改坐标轴范围
------------------------------------------
一开始的做法是「按可见区间切片、每次重建三张图」，300 根要 175 毫秒，
拖动只有 5 帧，明显卡。后来实测发现 QCandlestickSeries 和 QBarSeries 挂在
QValueAxis 上跟挂在 QBarCategoryAxis 上画出来一模一样（柱位、柱宽都对），
而数值轴改 range 只要 0.3 毫秒。所以改成：

    数据一次性全量灌进 series，X 轴是 0 … N-1 的数值轴，
    缩放平移就是 setRange(起-0.5, 止-0.5)，三个图一起改，瞬间完成。

这也是市面上看盘软件的通用做法。代价是 X 轴不能再用类别标签（类别轴才能
显示文字），日期改成在 paintEvent 里按当前范围手绘六个刻度。

MACD 参数固定 12/26/9，柱是 (DIF-DEA)*2，和通达信、同花顺的默认口径一致。

数据框只要含有 日期 / 开盘 / 最高 / 最低 / 收盘 / 成交量 这几列（或对应的英文列）就行，
列名兼容中文和英文两种写法。
"""

import pandas as pd
from PySide6.QtCharts import (QBarSeries, QBarSet, QCandlestickSeries, QCandlestickSet,
                              QChart, QChartView, QLineSeries, QValueAxis)
from PySide6.QtCore import QMargins, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

import config
from 应用 import 主题
from 应用.组件.加载圈 import 加载提示

# 指标线颜色，和 HTML 版 charts.py 的 make_kline_chart 一致：
# DIF / K 用橙，DEA / D 用蓝，J 用紫
线色_DIF = "#d18700"
线色_DEA = "#2f6fd0"
线色_K = "#d18700"
线色_D = "#2f6fd0"
线色_J = "#9b59b6"

# 中文列名 → 内部标准名
列别名 = {
    "日期": "日期", "date": "日期", "时间": "日期", "day": "日期",
    "开盘": "开盘", "开盘价": "开盘", "open": "开盘",
    "最高": "最高", "最高价": "最高", "high": "最高",
    "最低": "最低", "最低价": "最低", "low": "最低",
    "收盘": "收盘", "收盘价": "收盘", "close": "收盘",
    "成交量": "成交量", "volume": "成交量", "vol": "成交量",
}

# 分钟周期的粒度（分钟）。新浪把每根标在这根的**结束**时刻上：
# 1 分钟首根是 09:31、末根是 15:00，所以「这根覆盖的区间」是 [标签-粒度, 标签]。
周期分钟 = {"1分钟": 1, "5分钟": 5, "15分钟": 15, "30分钟": 30, "60分钟": 60}
# 集合竞价的午休边界，跨过去要夹住，否则 13:01 那根会算成 11:30 起
上午开市 = (9, 30)
下午开市 = (13, 0)

# 一屏最多画多少根，再多蜡烛就糊成一片了
默认根数 = 300
# 放大到底限，再少就看不出形态了
最少根数 = 15
# X 轴画几个日期刻度
刻度个数 = 6


def _规整(数据框: pd.DataFrame) -> pd.DataFrame:
    """把各种写法的列名统一成中文标准名，日期统一成 datetime。"""
    if not isinstance(数据框, pd.DataFrame) or 数据框.empty:
        return pd.DataFrame()

    映射 = {}
    已用 = set()
    for 原列 in 数据框.columns:
        标准 = 列别名.get(str(原列).strip().lower()) or 列别名.get(str(原列).strip())
        # 分钟数据同时有「日期」和「时间」两列，都映射成日期会造成重名列
        if 标准 and 标准 not in 已用:
            映射[原列] = 标准
            已用.add(标准)

    表 = 数据框.rename(columns=映射)
    需要 = ["日期", "开盘", "最高", "最低", "收盘"]
    if any(列 not in 表.columns for 列 in 需要):
        return pd.DataFrame()

    表 = 表.copy()
    表["日期"] = pd.to_datetime(表["日期"], errors="coerce")
    # 分钟数据带「时间戳」，它比纯日期精确，用它当横轴才对得上分时
    if "时间戳" in 表.columns:
        刻 = pd.to_datetime(表["时间戳"], errors="coerce")
        if 刻.notna().any():
            表["日期"] = 刻
    表 = 表.dropna(subset=["日期", "收盘"])
    for 列 in ["开盘", "最高", "最低", "收盘", "成交量"]:
        if 列 in 表.columns:
            表[列] = pd.to_numeric(表[列], errors="coerce")
    if "成交量" not in 表.columns:
        表["成交量"] = 0.0
    表 = 表.dropna(subset=["开盘", "最高", "最低"])
    表 = 表.sort_values("日期").reset_index(drop=True)
    return 表


def _均线(收盘: pd.Series, 窗口: int) -> pd.Series:
    return 收盘.rolling(窗口, min_periods=1).mean()


def _MACD(收盘: pd.Series, 快: int = 12, 慢: int = 26, 信号: int = 9):
    """返回 (DIF, DEA, 柱)。柱是 (DIF-DEA)*2，和通达信、同花顺的默认口径一致。"""
    指数 = 收盘.ewm(span=快, adjust=False).mean() - 收盘.ewm(span=慢, adjust=False).mean()
    信号线 = 指数.ewm(span=信号, adjust=False).mean()
    柱 = (指数 - 信号线) * 2.0
    return 指数, 信号线, 柱


def _KDJ(最高: pd.Series, 最低: pd.Series, 收盘: pd.Series,
         n: int = 9, k_n: int = 3, d_n: int = 3):
    """返回 (K, D, J)。口径和 HTML 版 charts.计算KDJ 完全一致。

    RSV 用最近 n 根的最高最低，K / D 用 alpha=1/n 的指数平滑（等价通达信的 SMA），
    J = 3K - 2D。全区最高最低相等时 RSV 按 50 处理，避免除零。
    """
    if len(收盘) == 0:
        return None, None, None
    高n = 最高.rolling(window=n, min_periods=1).max()
    低n = 最低.rolling(window=n, min_periods=1).min()
    差值 = (高n - 低n).replace(0, pd.NA)
    rsv = ((收盘 - 低n) / 差值 * 100).astype("float64").fillna(50.0)
    K = rsv.ewm(alpha=1.0 / k_n, adjust=False).mean()
    D = K.ewm(alpha=1.0 / d_n, adjust=False).mean()
    J = 3.0 * K - 2.0 * D
    return K, D, J


def _线点(序列: pd.Series):
    """把一列值变成 QLineSeries 要的点；空值跳过（跳过的地方线会断开，正是想要的）。"""
    return [QPointF(float(序), float(值)) for 序, 值 in enumerate(序列.tolist())
            if pd.notna(值)]


class _交互视图(QChartView):
    """把滚轮、拖动、双击转给 K 线图本体处理。

    三张图各挂一个，所以鼠标落在成交量图或 MACD 图上也能缩放平移，
    而且三张图共用同一段区间 —— 始终对齐。
    """

    def __init__(self, 主图窗, 父=None):
        super().__init__(父)
        self._主图窗 = 主图窗
        self.画日期 = False
        self.setMouseTracking(True)
        # 橡皮筋和左键拖动抢事件，这里不要
        self.setRubberBand(QChartView.NoRubberBand)
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, 事件):
        # 有数据就把滚轮拿来做缩放，别让它冒泡去滚整个页面；
        # 还没数据时照旧交给父类，页面该滚滚
        if self._主图窗._表.empty:
            super().wheelEvent(事件)
            return
        self._主图窗.滚轮缩放(事件, self)
        事件.accept()

    def mousePressEvent(self, 事件):
        if 事件.button() == Qt.LeftButton and not self._主图窗._表.empty:
            self._主图窗.开始拖动(事件, self)
            事件.accept()
            return
        super().mousePressEvent(事件)

    def mouseMoveEvent(self, 事件):
        if self._主图窗._拖动中:
            self._主图窗.拖动中(事件, self)
            事件.accept()
            return
        self._主图窗.悬停(事件, self)
        super().mouseMoveEvent(事件)

    def leaveEvent(self, 事件):
        self._主图窗._藏读数()
        super().leaveEvent(事件)

    def mouseReleaseEvent(self, 事件):
        if self._主图窗._拖动中:
            self._主图窗.结束拖动(事件, self)
            事件.accept()
            return
        super().mouseReleaseEvent(事件)

    def mouseDoubleClickEvent(self, 事件):
        if 事件.button() == Qt.LeftButton and not self._主图窗._表.empty:
            self._主图窗.复位()
            事件.accept()
            return
        super().mouseDoubleClickEvent(事件)

    def paintEvent(self, 事件):
        super().paintEvent(事件)
        # X 轴是数值轴、标签关掉了，日期在这里手绘
        if not self.画日期:
            return
        图表 = self.chart()
        刻度 = getattr(self._主图窗, "_轴刻度", None)
        # 蜡烛系列是挂在**主图**那个 chart 上的，要拿主图去换算坐标；
        # 那张图的绘图区宽度跟这张不完全一样，所以再按比例映射过来
        源图 = None
        系列 = getattr(self._主图窗, "_蜡烛系列", None)
        源轴Y = getattr(self._主图窗, "_轴Y主", None)
        if getattr(self._主图窗, "_视图主", None) is not None:
            源图 = self._主图窗._视图主.chart()
        if 图表 is None or not 刻度 or 系列 is None or 源图 is None or 源轴Y is None:
            return
        区 = 图表.plotArea()
        源区 = 源图.plotArea()
        if 区.width() <= 1 or 区.height() <= 1 or 源区.width() <= 1:
            return

        字体 = QFont("Microsoft YaHei UI", 7)
        量度 = QFontMetrics(字体)
        画器 = QPainter(self.viewport())
        画器.setRenderHint(QPainter.TextAntialiasing, True)
        画器.setFont(字体)
        画器.setPen(QColor(主题.当前调色板()["文字2"]))

        偏 = self.viewport().mapTo(self, QPoint(0, 0))
        底点 = self.mapFromScene(QPointF(区.left(), 区.bottom()))
        左 = 底点.x() - 偏.x()
        底 = 底点.y() - 偏.y()
        宽 = 区.width()
        基线 = 底 + 2 + 量度.ascent()
        参考Y = 源轴Y.min()

        for 序, 文本 in 刻度:
            位置 = 源图.mapToPosition(QPointF(float(序), 参考Y), 系列)
            比例 = (位置.x() - 源区.left()) / 源区.width()
            x = 左 + max(0.0, min(1.0, 比例)) * 宽
            字宽 = 量度.horizontalAdvance(文本)
            if x - 字宽 / 2.0 < 左:
                x0 = 左
            elif x + 字宽 / 2.0 > 左 + 宽:
                x0 = 左 + 宽 - 字宽
            else:
                x0 = x - 字宽 / 2.0
            画器.drawText(QPointF(x0, 基线), 文本)
        画器.end()


class _读数卡(QLabel):
    """跟着鼠标走的读数卡片。

    为什么不用 QToolTip：提示框是独立的顶层窗口，由系统摆位。量下来三个毛病：
    它一盖住光标就会触发视口的 leaveEvent（我们的 leave 里要收提示），于是自己把
    自己关掉；Qt 重建提示框的那一瞬间采样会读到"不可见"；它还会掉到图外面去。
    换成挂在 K 线图上的子控件：坐标自己算，永远在图里，鼠标事件穿过去不算离开。
    """

    def __init__(self, 父):
        super().__init__(父)
        self.setObjectName("读数卡")
        self.setTextFormat(Qt.RichText)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()


class K线图(QWidget):
    """一只股票或一个板块的蜡烛图 + 成交量 + MACD，支持滚轮缩放和拖动平移。"""

    def __init__(self, 数据框: pd.DataFrame = None, 标题: str = "",
                 周期: str = "日K", 均线窗口=None, 显示MACD: bool = True,
                 显示KDJ: bool = False, 父=None):
        super().__init__(父)
        self._标题 = 标题 or ""
        self._周期 = 周期 or "日K"
        self._均线窗口 = list(均线窗口 if 均线窗口 else config.均线默认)
        self._显示MACD = bool(显示MACD)
        self._显示KDJ = bool(显示KDJ)
        self._表 = pd.DataFrame()

        # 缩放状态：可见区间是 [起, 止)，None 表示回到默认（最近 300 根）
        self._区间 = None
        self._均线缓存 = {}
        self._DIF = None
        self._DEA = None
        self._MACD柱 = None
        self._K值 = None
        self._D值 = None
        self._J值 = None
        self._悬停序 = -1

        # 建一次就复用的绘图对象
        self._轴刻度 = []
        self._蜡烛系列 = None
        self._轴X主 = None
        self._轴X量 = None
        self._轴X指 = None
        self._轴XKDJ = None
        self._轴Y主 = None
        self._轴Y量 = None
        self._轴Y指 = None
        self._轴YKDJ = None
        self._视图主 = None
        self._视图量 = None
        self._视图MACD = None
        self._视图KDJ = None
        self._已建 = False

        # 拖动状态
        self._拖动中 = False
        self._拖起像素 = 0.0
        self._拖起区间 = (0, 0)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(4)

        self._提示 = 加载提示("暂无数据", 居中=True, 对象名="空状态", 父=self)
        布局.addWidget(self._提示, 1)

        self._读数 = _读数卡(self)
        self._读数文 = ""
        self._读数纯文 = ""
        self._读数.setStyleSheet(self._读数样式())

        self._提示条 = QLabel("滚轮缩放，按住左键拖动左右平移，双击复位", self)
        self._提示条.setObjectName("来源标注")
        self._提示条.setVisible(False)
        布局.addWidget(self._提示条, 0)

        if 数据框 is not None:
            self.换数据(数据框, 标题, 周期)

    # ---------------------------------------------------------------- 对外

    def 换数据(self, 数据框: pd.DataFrame, 标题: str = None, 周期: str = None):
        if 标题 is not None:
            self._标题 = 标题
        if 周期 is not None:
            self._周期 = 周期
        self._藏读数()
        self._表 = _规整(数据框)
        self._区间 = None          # 换股票就回到默认视角
        self._算指标()
        self._建图()

    def 清空(self, 文本: str = "暂无数据"):
        self._表 = pd.DataFrame()
        self._区间 = None
        self._均线缓存 = {}
        self._DIF = self._DEA = self._MACD柱 = None
        self._K值 = self._D值 = self._J值 = None
        self._藏读数()
        self._提示.setText(文本)
        self._提示.setVisible(True)
        self._提示条.setVisible(False)
        for 视图 in (self._视图主, self._视图量, self._视图MACD, self._视图KDJ):
            if 视图 is not None:
                视图.setVisible(False)

    def 复位(self):
        """回到默认视角（最近 300 根）。"""
        self._藏读数()
        if self._表.empty:
            return
        self._区间 = None
        self._应用区间()

    def 应用主题变化(self):
        """切浅色 / 深色之后要把图重建一遍，颜色写在建图时。"""
        self._读数文 = ""
        self._读数.setStyleSheet(self._读数样式())
        self._读数.hide()
        if self._表.empty:
            return
        self._建图()

    def 设显示(self, 均线窗口=None, 显示MACD=None, 显示KDJ=None):
        """换均线窗口或开关副图，重建一次。None 表示这一项不动。"""
        变了 = False
        if 均线窗口 is not None:
            新 = [int(x) for x in 均线窗口]
            if 新 != self._均线窗口:
                self._均线窗口 = 新
                变了 = True
        if 显示MACD is not None and bool(显示MACD) != self._显示MACD:
            self._显示MACD = bool(显示MACD)
            变了 = True
        if 显示KDJ is not None and bool(显示KDJ) != self._显示KDJ:
            self._显示KDJ = bool(显示KDJ)
            变了 = True
        if not 变了 or self._表.empty:
            return
        # 副图增减了要把视图也重建，所以清掉旧的
        if not self._显示KDJ and self._视图KDJ is not None:
            self._视图KDJ.setParent(None)
            self._视图KDJ.deleteLater()
            self._视图KDJ = None
        if not self._显示MACD and self._视图MACD is not None:
            self._视图MACD.setParent(None)
            self._视图MACD.deleteLater()
            self._视图MACD = None
        self._算指标()
        self._建图()

    # ---------------------------------------------------------------- 区间

    def _算指标(self):
        """指标在全量数据上算好，缩放时只是改轴范围，不用重算。"""
        self._均线缓存 = {}
        self._DIF = self._DEA = self._MACD柱 = None
        self._K值 = self._D值 = self._J值 = None
        if self._表.empty:
            return
        收盘 = self._表["收盘"]
        for 窗口 in self._均线窗口:
            self._均线缓存[窗口] = _均线(收盘, 窗口)
        if self._显示MACD:
            self._DIF, self._DEA, self._MACD柱 = _MACD(收盘)
        if self._显示KDJ:
            self._K值, self._D值, self._J值 = _KDJ(self._表["最高"], self._表["最低"], 收盘)

    def _默认区间(self):
        总 = len(self._表)
        跨度 = min(总, 默认根数)
        return 总 - 跨度, 总

    def _取区间(self):
        总 = len(self._表)
        if 总 <= 0:
            return 0, 0
        if self._区间 is None:
            return self._默认区间()
        起, 止 = self._区间
        起 = max(0, min(int(起), max(0, 总 - 1)))
        止 = max(起 + 1, min(int(止), 总))
        return 起, 止

    def _落区间(self, 起, 止):
        """把区间夹到合法范围内，太短则按最少根数补齐。"""
        总 = len(self._表)
        if 总 <= 0:
            self._区间 = None
            return
        起, 止 = int(round(起)), int(round(止))
        跨度 = max(min(最少根数, 总), min(总, 止 - 起))
        起 = max(0, min(起, 总 - 跨度))
        self._区间 = (起, 起 + 跨度)

    # ---------------------------------------------------------------- 交互

    def _场景点(self, 事件, 视图):
        return 视图.mapToScene(事件.position().toPoint())

    def _鼠标比例(self, 事件, 视图):
        """鼠标落在绘图区宽度的百分之几（0 左 1 右）。落在绘图区外就夹到边。"""
        图 = 视图.chart()
        if 图 is None:
            return 0.5
        区 = 图.plotArea()
        if 区.width() <= 1:
            return 0.5
        点 = self._场景点(事件, 视图)
        return max(0.0, min(1.0, (点.x() - 区.left()) / 区.width()))

    def 滚轮缩放(self, 事件, 视图):
        if self._表.empty:
            return
        self._藏读数()  # 缩放之后这根已经不在原处，读数就地作废
        差 = 事件.angleDelta().y()
        if 差 == 0:
            return
        起, 止 = self._取区间()
        跨度 = 止 - 起
        总 = len(self._表)
        # 向上滚放大（看得更少更细），向下滚缩小
        倍 = 0.84 if 差 > 0 else 1.0 / 0.84
        新跨 = max(min(最少根数, 总), min(总, int(round(跨度 * 倍))))
        if 新跨 == 跨度:
            return
        比例 = self._鼠标比例(事件, 视图)
        中心 = 起 + 比例 * 跨度
        self._落区间(中心 - 比例 * 新跨, 中心 + (1 - 比例) * 新跨)
        self._应用区间()

    def 开始拖动(self, 事件, 视图):
        if 事件.button() != Qt.LeftButton or self._表.empty:
            return
        self._藏读数()
        self._拖动中 = True
        self._拖起像素 = self._场景点(事件, 视图).x()
        self._拖起区间 = self._取区间()
        视图.setCursor(Qt.ClosedHandCursor)

    def 拖动中(self, 事件, 视图):
        if not self._拖动中:
            return
        图 = 视图.chart()
        if 图 is None:
            return
        区宽 = 图.plotArea().width()
        if 区宽 <= 1:
            return
        起0, 止0 = self._拖起区间
        跨度 = 止0 - 起0
        # 往左拖，手底下的图跟着左移，露出的是更晚的数据
        位移 = self._场景点(事件, 视图).x() - self._拖起像素
        根数 = int(round(-位移 / 区宽 * 跨度))
        self._落区间(起0 + 根数, 起0 + 根数 + 跨度)
        self._应用区间()

    def 结束拖动(self, 事件, 视图):
        if 事件.button() == Qt.LeftButton:
            self._拖动中 = False
            视图.setCursor(Qt.OpenHandCursor)

    def 悬停(self, 事件, 视图):
        """鼠标停在哪根上，就在光标旁边显示这根的开高低收，和 HTML 版的 hovertext 一个意思。"""
        if self._表.empty or self._拖动中:
            return
        图 = 视图.chart()
        if 图 is None:
            return
        区 = 图.plotArea()
        if 区.width() <= 1:
            return
        点 = self._场景点(事件, 视图)
        比例 = (点.x() - 区.left()) / 区.width()
        if 比例 < 0.0 or 比例 > 1.0:
            self._藏读数()
            return
        起, 止 = self._取区间()
        序 = int(round(起 - 0.5 + 比例 * (止 - 起)))
        序 = max(0, min(len(self._表) - 1, 序))
        if 序 == self._悬停序 and self._读数.isVisible():
            return
        self._悬停序 = 序
        # 视口坐标 → 本控件坐标（从子往父走，Qt 只认这个方向）
        图内点 = 视图.viewport().mapTo(self, 事件.position().toPoint())
        self._显示读数(序, 图内点)

    def _读数样式(self) -> str:
        盘 = 主题.当前调色板()
        return ("QLabel#读数卡 { background: %s; border: 1px solid %s; border-radius: 8px;"
                " padding: 8px 10px; }" % (盘["卡片"], 盘["边框"]))

    def _读数富文本(self, 序: int) -> str:
        """把 悬停文本() 那几行包成卡片里的富文本；只有阳线 / 阴线那一句带涨跌色。"""
        行们 = self.悬停文本(序).split("\n")
        if not 行们 or not 行们[0]:
            return ""
        盘 = 主题.当前调色板()
        时间, _, 其余 = 行们[0].partition("　")
        色 = 盘["涨"] if 其余.startswith("阳线") else 盘["跌"]
        段 = ['<div style="font-family:Microsoft YaHei UI; font-size:12px; color:%s;">' % 盘["文字1"],
              "<b>%s</b><br>" % 时间,
              '<span style="color:%s;">%s</span>' % (色, 其余)]
        for 行 in 行们[1:]:
            段.append("<br>%s" % 行)
        段.append("</div>")
        return "".join(段)

    def _显示读数(self, 序: int, 图内点: QPoint):
        """摆卡片：默认在光标右侧，靠右就翻到左侧，上下夹在图里，永远不压住光标。"""
        文 = self._读数富文本(序)
        if not 文:
            self._读数.hide()
            return
        self._读数纯文 = self.悬停文本(序)
        if 文 != self._读数文:
            self._读数文 = 文
            self._读数.setText(文)
            self._读数.adjustSize()
        宽, 高 = self._读数.width(), self._读数.height()
        x = 图内点.x() + 16
        if x + 宽 > self.width() - 6:
            x = 图内点.x() - 宽 - 16
        x = max(6, x)
        y = max(6, min(self.height() - 高 - 6, 图内点.y() - 高 // 2))
        self._读数.move(x, y)
        self._读数.show()
        self._读数.raise_()

    def _藏读数(self):
        self._悬停序 = -1
        self._读数纯文 = ""
        self._读数.hide()

    def _时间段(self, 行) -> str:
        """这根 K 线覆盖的时间段。

        分钟线的新浪标签是**结束时刻**，区间取 [标签 - 粒度, 标签]；跨午休时夹到 13:00。
        日线以上就用日期本身 —— 周 / 月线的标签是那一周的周五或当月首日，那是接口的口径，
        不在这里替它换算。
        """
        刻 = 行.get("日期")
        粒度 = 周期分钟.get(self._周期, 0)
        if not hasattr(刻, "strftime"):
            return str(刻 if 刻 is not None else "")
        if 粒度 <= 0 or not (刻.hour or 刻.minute):
            return 刻.strftime("%Y-%m-%d")
        起 = 刻 - pd.Timedelta(minutes=粒度)
        if 刻.hour >= 12:
            市 = 刻.replace(hour=下午开市[0], minute=下午开市[1], second=0, microsecond=0)
        else:
            市 = 刻.replace(hour=上午开市[0], minute=上午开市[1], second=0, microsecond=0)
        if 起 < 市:
            起 = 市
        if 起 == 刻:
            return "%s %s" % (刻.strftime("%Y-%m-%d"), 刻.strftime("%H:%M"))
        return "%s %s–%s" % (刻.strftime("%Y-%m-%d"), 起.strftime("%H:%M"), 刻.strftime("%H:%M"))

    def 悬停文本(self, 序: int) -> str:
        """第 序 根的时间段 + 开高低收 + 涨跌幅 + 成交量，纯文本，方便测试直接比对。"""
        if self._表.empty or 序 < 0 or 序 >= len(self._表):
            return ""
        行 = self._表.iloc[序]
        日期 = self._时间段(行)
        开 = float(行["开盘"])
        高 = float(行["最高"])
        低 = float(行["最低"])
        收 = float(行["收盘"])
        百分 = (收 - 开) / 开 * 100.0 if 开 else 0.0
        量 = 行.get("成交量")
        量文 = self._量文(量)
        首行 = "%s　%s %+.2f%%" % (日期, "阳线" if 收 >= 开 else "阴线", 百分)
        正文 = "开 %.2f　高 %.2f\n低 %.2f　收 %.2f" % (开, 高, 低, 收)
        if 量文:
            正文 += "\n量 %s" % 量文
        return "%s\n%s" % (首行, 正文)

    def _量文(self, 量) -> str:
        """成交量的单位按周期挑，不然一分钟那根会写成「0.00 亿」。

        数据源给的都是**股**（新浪日线和分钟线都是），日线一天几千万股，用亿说得通；
        一分钟只有几万股，除以 1e8 就只剩 0.00，所以分钟周期改写成万股。
        """
        try:
            if not pd.notna(量):
                return ""
            值 = float(量)
        except Exception:
            return ""
        if 周期分钟.get(self._周期, 0) > 0:
            if abs(值) >= 1e4:
                return "%.1f 万股" % (值 / 1e4)
            return "%.0f 股" % 值
        return "%.2f 亿" % (值 / 1e8)

    # ---------------------------------------------------------------- 绘制

    def _建图(self):
        """把整段数据一次性灌进三张图。只有换股票或切主题才需要重建。"""
        表 = self._表
        if 表.empty:
            self.清空("暂无数据")
            return

        盘 = 主题.当前调色板()
        涨色 = QColor(盘["涨"])
        跌色 = QColor(盘["跌"])
        根数 = len(表)
        开们 = 表["开盘"].tolist()
        高们 = 表["最高"].tolist()
        低们 = 表["最低"].tolist()
        收们 = 表["收盘"].tolist()
        量们 = 表["成交量"].tolist()

        布局 = self.layout()
        if self._视图主 is None:
            self._视图主 = _交互视图(self, self)
            self._视图量 = _交互视图(self, self)
            for 视图 in (self._视图主, self._视图量):
                视图.setRenderHint(QPainter.Antialiasing, True)
                视图.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            布局.addWidget(self._视图主, 3)
            布局.addWidget(self._视图量, 1)
        if self._显示MACD and self._视图MACD is None:
            self._视图MACD = _交互视图(self, self)
            self._视图MACD.setRenderHint(QPainter.Antialiasing, True)
            self._视图MACD.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            布局.addWidget(self._视图MACD, 1)
        if self._显示KDJ and self._视图KDJ is None:
            self._视图KDJ = _交互视图(self, self)
            self._视图KDJ.setRenderHint(QPainter.Antialiasing, True)
            self._视图KDJ.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            布局.addWidget(self._视图KDJ, 1)
        self._提示.setVisible(False)
        self._提示条.setVisible(True)
        for 视图 in (self._视图主, self._视图量, self._视图MACD, self._视图KDJ):
            if 视图 is not None:
                视图.setVisible(True)

        # ---------------- 主图：蜡烛 + 均线 ----------------
        主图 = QChart()
        主图.setBackgroundVisible(False)
        主图.setMargins(QMargins(6, 6, 4, 4))
        主图.legend().setVisible(True)
        主图.legend().setAlignment(Qt.AlignTop)
        主图.legend().setLabelColor(QColor(盘["文字2"]))
        主图.legend().setFont(QFont("Microsoft YaHei UI", 8))
        主图.setAnimationOptions(QChart.NoAnimation)  # 动画会拖慢切换

        蜡烛 = QCandlestickSeries()
        蜡烛.setName("K线")
        蜡烛.setIncreasingColor(涨色)
        蜡烛.setDecreasingColor(跌色)
        蜡烛.setBodyOutlineVisible(True)
        蜡烛.setPen(QPen(跌色, 1))
        # 逐根 append 要几千次跨语言调用，攒成列表一次 append
        点列表 = []
        for 序 in range(根数):
            开, 高, 低, 收 = 开们[序], 高们[序], 低们[序], 收们[序]
            点 = QCandlestickSet(开, 高, 低, 收, float(序))
            点.setPen(QPen(涨色 if 收 >= 开 else 跌色, 1))
            点列表.append(点)
        蜡烛.append(点列表)
        主图.addSeries(蜡烛)
        self._蜡烛系列 = 蜡烛

        轴X = QValueAxis()
        轴X.setRange(-0.5, 根数 - 0.5)
        轴X.setLabelsVisible(False)
        轴X.setGridLineVisible(False)
        轴X.setLinePenColor(QColor(盘["边框深"]))
        主图.addAxis(轴X, Qt.AlignBottom)
        蜡烛.attachAxis(轴X)
        self._轴X主 = 轴X

        轴Y = QValueAxis()
        轴Y.setLabelFormat("%.2f")
        轴Y.setLabelsColor(QColor(盘["文字2"]))
        轴Y.setLabelsFont(QFont("Microsoft YaHei UI", 7))
        轴Y.setGridLineColor(QColor(盘["边框"]))
        轴Y.setLinePenColor(QColor(盘["边框深"]))
        主图.addAxis(轴Y, Qt.AlignLeft)
        蜡烛.attachAxis(轴Y)
        self._轴Y主 = 轴Y

        for 窗口 in self._均线窗口:
            全均 = self._均线缓存.get(窗口)
            if 全均 is None:
                continue
            线 = QLineSeries()
            线.setName("MA%d" % 窗口)
            # 颜色按窗口号取，别直接 zip config.均线颜色（那是字典，迭代出来是键）
            线.setPen(QPen(QColor(config.均线颜色.get(int(窗口), "#666666")), 1.2))
            线.replace(_线点(全均))
            主图.addSeries(线)
            线.attachAxis(轴X)
            线.attachAxis(轴Y)

        主图.setTitle(self._标题)
        主图.setTitleFont(QFont("Microsoft YaHei UI", 9, QFont.Medium))
        主图.setTitleBrush(QColor(盘["文字1"]))
        self._视图主.setChart(主图)

        # ---------------- 副图：成交量 ----------------
        量图 = QChart()
        量图.setBackgroundVisible(False)
        量图.setMargins(QMargins(6, 6, 4, 4))
        量图.legend().setVisible(False)
        量图.setAnimationOptions(QChart.NoAnimation)

        涨柱 = QBarSet("上涨")
        跌柱 = QBarSet("下跌")
        涨柱.setColor(涨色)
        跌柱.setColor(跌色)
        涨柱.setBorderColor(Qt.transparent)
        跌柱.setBorderColor(Qt.transparent)
        涨列 = []
        跌列 = []
        for 序 in range(根数):
            涨 = 收们[序] >= 开们[序]
            值 = 量们[序] if pd.notna(量们[序]) else 0.0
            涨列.append(值 / 1e8 if 涨 else 0.0)
            跌列.append(0.0 if 涨 else 值 / 1e8)
        涨柱.append(涨列)
        跌柱.append(跌列)
        柱 = QBarSeries()
        柱.setBarWidth(0.7)
        柱.append(涨柱)
        柱.append(跌柱)
        量图.addSeries(柱)

        轴X量 = QValueAxis()
        轴X量.setRange(-0.5, 根数 - 0.5)
        轴X量.setLabelsVisible(False)
        轴X量.setGridLineVisible(False)
        轴X量.setLinePenColor(QColor(盘["边框深"]))
        量图.addAxis(轴X量, Qt.AlignBottom)
        柱.attachAxis(轴X量)
        self._轴X量 = 轴X量

        轴Y量 = QValueAxis()
        轴Y量.setLabelFormat("%.1f")
        轴Y量.setTitleText("量(亿)")
        轴Y量.setTitleFont(QFont("Microsoft YaHei UI", 7))
        轴Y量.setTitleBrush(QColor(盘["文字3"]))
        轴Y量.setLabelsColor(QColor(盘["文字2"]))
        轴Y量.setLabelsFont(QFont("Microsoft YaHei UI", 7))
        轴Y量.setGridLineColor(QColor(盘["边框"]))
        轴Y量.setLinePenColor(QColor(盘["边框深"]))
        量图.addAxis(轴Y量, Qt.AlignLeft)
        柱.attachAxis(轴Y量)
        self._轴Y量 = 轴Y量

        self._视图量.setChart(量图)

        # ---------------- 副图二：MACD ----------------
        if self._显示MACD and self._视图MACD is not None and self._DIF is not None:
            指标图 = QChart()
            指标图.setBackgroundVisible(False)
            指标图.setMargins(QMargins(6, 6, 4, 4))
            指标图.legend().setVisible(True)
            指标图.legend().setAlignment(Qt.AlignTop)
            指标图.legend().setLabelColor(QColor(盘["文字2"]))
            指标图.legend().setFont(QFont("Microsoft YaHei UI", 7))
            指标图.setAnimationOptions(QChart.NoAnimation)

            正柱 = QBarSet("MACD")
            负柱 = QBarSet("MACD")
            正柱.setColor(涨色)
            负柱.setColor(跌色)
            for 集 in (正柱, 负柱):
                集.setBorderColor(Qt.transparent)
            柱值 = [float(v) for v in self._MACD柱.tolist()]
            正柱.append([v if v > 0 else 0.0 for v in 柱值])
            负柱.append([v if v < 0 else 0.0 for v in 柱值])
            柱列 = QBarSeries()
            柱列.setBarWidth(0.62)
            柱列.append(正柱)
            柱列.append(负柱)
            指标图.addSeries(柱列)

            轴X指 = QValueAxis()
            轴X指.setRange(-0.5, 根数 - 0.5)
            轴X指.setLabelsVisible(False)
            轴X指.setGridLineVisible(False)
            轴X指.setLinePenColor(QColor(盘["边框深"]))
            指标图.addAxis(轴X指, Qt.AlignBottom)
            柱列.attachAxis(轴X指)
            self._轴X指 = 轴X指

            轴Y指 = QValueAxis()
            轴Y指.setLabelsColor(QColor(盘["文字2"]))
            轴Y指.setLabelsFont(QFont("Microsoft YaHei UI", 7))
            轴Y指.setGridLineColor(QColor(盘["边框"]))
            轴Y指.setLinePenColor(QColor(盘["边框深"]))
            轴Y指.setTickCount(3)
            指标图.addAxis(轴Y指, Qt.AlignLeft)
            柱列.attachAxis(轴Y指)
            self._轴Y指 = 轴Y指

            for 名称, 段, 颜色 in (("DIF", self._DIF, 线色_DIF), ("DEA", self._DEA, 线色_DEA)):
                线 = QLineSeries()
                线.setName(名称)
                线.setPen(QPen(QColor(颜色), 1.2))
                线.replace(_线点(段))
                指标图.addSeries(线)
                线.attachAxis(轴X指)
                线.attachAxis(轴Y指)

            # 柱子两个 set 会在图例里占两行同名项，藏掉，只留 DIF / DEA
            try:
                for 标记 in 指标图.legend().markers(柱列):
                    标记.setVisible(False)
            except Exception:
                pass

            self._视图MACD.setChart(指标图)
        else:
            self._轴X指 = None
            self._轴Y指 = None

        # ---------------- 副图三：KDJ ----------------
        if self._显示KDJ and self._视图KDJ is not None and self._K值 is not None:
            K图 = QChart()
            K图.setBackgroundVisible(False)
            K图.setMargins(QMargins(6, 6, 4, 4))
            K图.legend().setVisible(True)
            K图.legend().setAlignment(Qt.AlignTop)
            K图.legend().setLabelColor(QColor(盘["文字2"]))
            K图.legend().setFont(QFont("Microsoft YaHei UI", 7))
            K图.setAnimationOptions(QChart.NoAnimation)

            轴XK = QValueAxis()
            轴XK.setRange(-0.5, 根数 - 0.5)
            轴XK.setLabelsVisible(False)
            轴XK.setGridLineVisible(False)
            轴XK.setLinePenColor(QColor(盘["边框深"]))
            K图.addAxis(轴XK, Qt.AlignBottom)
            self._轴XKDJ = 轴XK

            轴YK = QValueAxis()
            轴YK.setLabelsColor(QColor(盘["文字2"]))
            轴YK.setLabelsFont(QFont("Microsoft YaHei UI", 7))
            轴YK.setGridLineColor(QColor(盘["边框"]))
            轴YK.setLinePenColor(QColor(盘["边框深"]))
            轴YK.setTickCount(3)
            轴YK.setLabelFormat("%.0f")
            K图.addAxis(轴YK, Qt.AlignLeft)
            self._轴YKDJ = 轴YK

            for 名称, 段, 颜色 in (("K", self._K值, 线色_K),
                                   ("D", self._D值, 线色_D),
                                   ("J", self._J值, 线色_J)):
                线 = QLineSeries()
                线.setName(名称)
                线.setPen(QPen(QColor(颜色), 1.2))
                线.replace(_线点(段))
                K图.addSeries(线)
                线.attachAxis(轴XK)
                线.attachAxis(轴YK)

            self._视图KDJ.setChart(K图)
        else:
            self._轴XKDJ = None
            self._轴YKDJ = None

        # 各图高度差固定，避免每次重画尺寸抖动
        self._视图主.setMinimumHeight(200)
        self._视图量.setMinimumHeight(72)
        if self._视图MACD is not None:
            self._视图MACD.setMinimumHeight(78)
        if self._视图KDJ is not None:
            self._视图KDJ.setMinimumHeight(78)

        # 日期只画在最下面那张图上，否则会压到下一张图的顶部
        最下 = self._视图量
        if self._视图MACD is not None:
            最下 = self._视图MACD
        if self._视图KDJ is not None:
            最下 = self._视图KDJ
        for 视图 in (self._视图主, self._视图量, self._视图MACD, self._视图KDJ):
            if 视图 is not None:
                视图.画日期 = (视图 is 最下)

        self._已建 = True
        self._应用区间()

    def _应用区间(self):
        """缩放平移的全部开销就在这里：改几个 setRange，实测 0.3 毫秒一个。"""
        总 = len(self._表)
        if 总 <= 0 or not self._已建 or self._轴X主 is None:
            return
        起, 止 = self._取区间()
        左 = 起 - 0.5
        右 = 止 - 0.5
        self._轴X主.setRange(左, 右)
        self._轴X量.setRange(左, 右)
        if self._轴X指 is not None:
            self._轴X指.setRange(左, 右)
        if self._轴XKDJ is not None:
            self._轴XKDJ.setRange(左, 右)

        段 = self._表.iloc[起:止]
        if not 段.empty:
            低 = float(段["最低"].min())
            高 = float(段["最高"].max())
            余 = (高 - 低) * 0.06 or max(abs(高) * 0.01, 0.01)
            self._轴Y主.setRange(低 - 余, 高 + 余)

            最大量 = max(float(段["成交量"].max()) / 1e8, 0.01)
            self._轴Y量.setRange(0, 最大量 * 1.15)

            if self._轴Y指 is not None and self._MACD柱 is not None:
                柱段 = self._MACD柱.iloc[起:止]
                DIF段 = self._DIF.iloc[起:止]
                DEA段 = self._DEA.iloc[起:止]
                值们 = [float(x) for x in (DIF段.tolist() + DEA段.tolist() + 柱段.tolist())
                        if pd.notna(x)]
                低指 = min(值们 + [0.0])
                高指 = max(值们 + [0.0])
                if 高指 - 低指 < 1e-9:
                    高指 = 低指 + 1.0
                余指 = (高指 - 低指) * 0.16
                self._轴Y指.setRange(低指 - 余指, 高指 + 余指)
                self._轴Y指.setLabelFormat("%.3f" if 高指 < 10 else "%.2f")

            if self._轴YKDJ is not None and self._K值 is not None:
                K段 = self._K值.iloc[起:止]
                D段 = self._D值.iloc[起:止]
                J段 = self._J值.iloc[起:止]
                值们 = [float(x) for x in (K段.tolist() + D段.tolist() + J段.tolist())
                        if pd.notna(x)]
                # 常态下就把 0~100 框住，J 值偶尔冲出去再跟着放
                低k = min(值们 + [0.0])
                高k = max(值们 + [100.0])
                if 高k - 低k < 1e-9:
                    高k = 低k + 100.0
                余k = (高k - 低k) * 0.06
                self._轴YKDJ.setRange(低k - 余k, 高k + 余k)

        # X 轴刻度：可见区间里等间隔取几个日期，paintEvent 会照着画
        跨度 = 止 - 起
        个数 = max(2, min(刻度个数, 跨度))
        if self._周期 in ("1分钟", "5分钟", "15分钟", "30分钟", "60分钟"):
            格式 = "%m-%d %H:%M" if 跨度 > 60 else "%H:%M"
        else:
            格式 = "%Y-%m" if self._周期 == "月K" else "%Y-%m-%d"
        刻度 = []
        for 位 in range(个数):
            序 = 起 + int(round((跨度 - 1) * 位 / (个数 - 1))) if 个数 > 1 else 起
            try:
                文本 = self._表["日期"].iloc[序].strftime(格式)
            except Exception:
                continue
            刻度.append((序, 文本))
        self._轴刻度 = 刻度

        self._更新提示条(起, 止, 总)
        for 视图 in (self._视图主, self._视图量, self._视图MACD, self._视图KDJ):
            if 视图 is not None:
                视图.viewport().update()

    def _更新提示条(self, 起, 止, 总):
        """告诉用户现在看的是哪一段、还剩多少没看。"""
        try:
            首 = self._表["日期"].iloc[起]
            尾 = self._表["日期"].iloc[止 - 1]
            格式 = "%Y-%m-%d %H:%M" if self._周期 in 周期分钟 else "%Y-%m-%d"
            跨 = "%s 至 %s" % (首.strftime(格式), 尾.strftime(格式))
        except Exception:
            跨 = ""
        段 = "共 %d 根，当前显示第 %d–%d 根" % (总, 起 + 1, 止)
        if 止 - 起 >= 总:
            段 = "共 %d 根，已全部显示" % 总
        提示 = "%s ｜ %s ｜ 滚轮缩放，按住左键拖动，双击复位" % (跨, 段) if 跨 else 段
        if 止 - 起 <= 最少根数:
            提示 += " ｜ 已放到最大"
        self._提示条.setText(提示)