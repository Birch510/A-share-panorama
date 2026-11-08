# -*- coding: utf-8 -*-
"""
折线图：多条走势线 + 可选参考线，鼠标移上去能读出那一点的具体数值。

给宏观指标（PMI、货币供应）和估值走势用。

X 轴用类别轴（放中文月份），不用时间轴 —— 缺月份、非交易日都不会留出空档，
标签也能直接写「2026年09月」这种中文，不用再格式化成英文。

系列格式：[(名称, 值列表, 颜色或None), ...]，值列表里的 None 会断线不连。

悬停读数：鼠标在绘图区里移动时，按横坐标算它落在第几个类别上，
画一条竖虚线，并在光标旁边弹出「月份 + 每条线的数值」。
算的是最近的类别而不是插值 —— 月度数据一个月只有一个点，
插出来的数没有意义，如实告诉用户「这个月就是这些数」更靠谱。

置高()：给「放大」用。高度用补间动画改，不瞬间跳。
"""

from PySide6.QtCharts import QBarCategoryAxis, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QEasingCurve, QMargins, QPointF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QVBoxLayout, QWidget

from 应用 import 主题
from 应用.组件.加载圈 import 加载提示

# 默认线色：克制的蓝、橙、紫、青，够区分又不刺眼
默认线色 = ["#2f6bd8", "#d97706", "#7c3aed", "#0f766e"]


class _悬停视图(QChartView):
    """把鼠标位置与离开事件转给折线图自己处理，QChartView 默认不吃这些事件。"""

    def __init__(self, 父=None):
        super().__init__(父)
        self.到移动 = None
        self.到离开 = None
        self.setMouseTracking(True)

    def mouseMoveEvent(self, 事件):
        if self.到移动:
            self.到移动(事件.position().toPoint())
        super().mouseMoveEvent(事件)

    def leaveEvent(self, 事件):
        if self.到离开:
            self.到离开()
        super().leaveEvent(事件)


class 折线图(QWidget):
    """高度可调的一张小图，数据到了再画。"""

    def __init__(self, 标题: str = "", 高度: int = 260, 父=None):
        super().__init__(父)
        self._标题 = 标题 or ""
        self._高度 = 高度
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(高度)
        self.setMaximumHeight(高度)

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(0)

        self._提示 = 加载提示("暂无数据", 居中=True, 对象名="空状态", 父=self)
        布局.addWidget(self._提示, 1)

        self._视图 = None
        self._十字 = None
        self._类别 = []
        self._系列 = []
        self._轴下 = 0.0
        self._轴上 = 1.0
        self._小数位 = 2
        self._悬停文本 = ""      # 最近一次弹出来的读数，自检脚本靠它验证
        self._高动画 = None

    # ---------------------------------------------------------------- 对外

    def 换数据(self, 系列, 类别, 参考线=None, 标题=None, Y轴标题="", 小数位=2):
        self._画(系列, 类别, 参考线, 标题, Y轴标题, 小数位)

    def 清空(self, 文本: str = "暂无数据"):
        self._提示.setText(文本)
        self._提示.setVisible(True)
        self._类别 = []
        self._系列 = []
        if self._视图 is not None:
            self._视图.setVisible(False)
        self._收起十字()

    def 置高(self, 高: int, 毫秒: int = 0):
        """改图的高度。毫秒为 0 时立刻生效，否则做补间动画。"""
        高 = max(120, int(高))
        self._停高动画()
        if 毫秒 <= 0:
            self._直接设高(高)
            return
        起 = float(self.height() or self._高度)
        self._高动画 = QVariantAnimation(self)
        self._高动画.setStartValue(起)
        self._高动画.setEndValue(float(高))
        self._高动画.setDuration(int(毫秒))
        self._高动画.setEasingCurve(QEasingCurve.OutCubic)
        self._高动画.valueChanged.connect(self._高帧)
        self._高动画.start(QVariantAnimation.DeleteWhenStopped)

    # ---------------------------------------------------------------- 绘制

    def _直接设高(self, 高: int):
        self._高度 = 高
        self.setMinimumHeight(高)
        self.setMaximumHeight(高)

    def _高帧(self, 值):
        self._直接设高(int(值))

    def _停高动画(self):
        if self._高动画 is not None:
            try:
                self._高动画.stop()
            except RuntimeError:
                pass
            self._高动画 = None

    def _画(self, 系列, 类别, 参考线, 标题, Y轴标题, 小数位):
        类别 = list(类别 or [])
        干净 = []
        for 名, 值, 色 in (系列 or []):
            序列 = [None if v is None else float(v) for v in (值 or [])]
            if 序列:
                干净.append((str(名), 序列, 色))
        if not 干净 or not 类别:
            self.清空()
            return

        if 标题 is not None:
            self._标题 = 标题
        盘 = 主题.当前调色板()
        self._小数位 = max(0, int(小数位))

        if self._视图 is None:
            self._视图 = _悬停视图(self)
            self._视图.到移动 = self._悬停移动
            self._视图.到离开 = self._悬停离开
            self._视图.setRenderHint(QPainter.Antialiasing, True)
            self._视图.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.layout().addWidget(self._视图, 1)
        self._视图.setVisible(True)
        self._提示.setVisible(False)

        图 = QChart()
        图.setBackgroundVisible(False)
        图.setMargins(QMargins(4, 4, 4, 2))
        图.setAnimationOptions(QChart.NoAnimation)
        图.legend().setVisible(len(干净) > 1)
        图.legend().setAlignment(Qt.AlignTop)
        图.legend().setLabelColor(QColor(盘["文字2"]))
        图.legend().setFont(QFont("Microsoft YaHei UI", 8))

        # 先算取值范围，参考线也要落在可视区内
        全部值 = [v for _, 序列, _ in 干净 for v in 序列 if v is not None]
        if 参考线 and 参考线 not in (None, ""):
            try:
                全部值.append(float(参考线[0]))
            except Exception:
                pass
        if not 全部值:
            self.清空()
            return
        最低 = min(全部值)
        最高 = max(全部值)
        if 最高 - 最低 < 1e-9:
            最高 = 最低 + 1.0
        余 = (最高 - 最低) * 0.12
        # 指标类数据（如 PMI）上下留白对称一些更好看
        轴下 = 最低 - 余
        轴上 = 最高 + 余
        self._轴下 = 轴下
        self._轴上 = 轴上
        self._类别 = list(类别)
        self._系列 = [(名, 序列) for 名, 序列, _ in 干净]

        for 序, (名, 序列, 色) in enumerate(干净):
            线 = QLineSeries()
            线.setName(名)
            颜色 = 色 or 默认线色[序 % len(默认线色)]
            线.setPen(QPen(QColor(颜色), 1.6))
            for i, v in enumerate(序列[:len(类别)]):
                if v is not None:
                    线.append(float(i), v)
            图.addSeries(线)

        标签 = _抽稀(类别, 8)
        轴X = QBarCategoryAxis()
        轴X.append(标签)
        轴X.setGridLineVisible(False)
        轴X.setLabelsColor(QColor(盘["文字2"]))
        轴X.setLabelsFont(QFont("Microsoft YaHei UI", 7))
        图.addAxis(轴X, Qt.AlignBottom)

        轴Y = QValueAxis()
        轴Y.setRange(轴下, 轴上)
        轴Y.setLabelFormat("%%.%df" % self._小数位)
        轴Y.setTickCount(5)
        轴Y.setLabelsColor(QColor(盘["文字2"]))
        轴Y.setLabelsFont(QFont("Microsoft YaHei UI", 7))
        轴Y.setGridLineColor(QColor(盘["边框"]))
        if Y轴标题:
            轴Y.setTitleText(Y轴标题)
            轴Y.setTitleFont(QFont("Microsoft YaHei UI", 7))
            轴Y.setTitleBrush(QColor(盘["文字3"]))
        图.addAxis(轴Y, Qt.AlignLeft)

        for 线 in 图.series():
            线.attachAxis(轴X)
            线.attachAxis(轴Y)

        # 悬停竖虚线：数据变换里建，跟着每次重画换一份新的
        self._十字 = QLineSeries()
        self._十字.setName("")
        self._十字.setPen(QPen(QColor(盘["文字3"]), 1.0, Qt.DashLine))
        self._十字.setVisible(False)
        图.addSeries(self._十字)
        self._十字.attachAxis(轴X)
        self._十字.attachAxis(轴Y)

        # 参考线最后加，画在折线上面，虚线不挡视线
        if 参考线:
            try:
                值 = float(参考线[0])
                字样 = str(参考线[1]) if len(参考线) > 1 else ""
            except Exception:
                值 = None
            if 值 is not None:
                参考 = QLineSeries()
                参考.setName(字样 or "参考线")
                笔 = QPen(QColor(盘["文字3"]), 1.0, Qt.DashLine)
                参考.setPen(笔)
                参考.append(0.0, 值)
                参考.append(float(len(类别) - 1), 值)
                图.addSeries(参考)
                参考.attachAxis(轴X)
                参考.attachAxis(轴Y)

        if self._标题:
            图.setTitle(self._标题)
            图.setTitleFont(QFont("Microsoft YaHei UI", 9, QFont.Medium))
            图.setTitleBrush(QColor(盘["文字1"]))
        self._视图.setChart(图)
        self._收起十字()
        self._同步图例()

    def _同步图例(self):
        """
        图例只给「看得见的」系列。

        QtCharts 给每个 addSeries 的系列都建一个图例标记，哪怕它是隐藏的。
        悬停用的十字虚线是隐藏的，不收拾它，图例右边就会多出一个空标记
        （一个没有文字的小色块），看起来像图没画全。
        """
        图 = self._视图.chart()
        if 图 is None or 图.legend() is None:
            return
        for 系 in 图.series():
            for 标 in 图.legend().markers(系):
                标.setVisible(bool(系.isVisible()))
        # 十字线是悬停辅助线，任何时候都不该出现在图例里
        if self._十字 is not None:
            try:
                for 标 in 图.legend().markers(self._十字):
                    标.setVisible(False)
            except RuntimeError:
                self._十字 = None

    # ---------------------------------------------------------------- 悬停读数

    def _悬停移动(self, 点):
        if self._视图 is None or not self._类别 or not self._系列:
            return
        图 = self._视图.chart()
        if 图 is None:
            return
        区 = 图.plotArea()
        if 区.width() <= 1 or 区.height() <= 1 or not 区.contains(点):
            self._收起十字()
            return

        总数 = len(self._类别)
        比例 = (点.x() - 区.left()) / 区.width()
        序 = int(比例 * 总数)
        序 = max(0, min(总数 - 1, 序))

        文本 = self.读数文本(序)
        self._悬停文本 = 文本
        if self._十字 is not None:
            try:
                self._十字.replace([QPointF(float(序), self._轴下), QPointF(float(序), self._轴上)])
                self._十字.setVisible(True)
            except RuntimeError:
                self._十字 = None
        QToolTip.showText(self._视图.mapToGlobal(点), 文本, self._视图)

    def _悬停离开(self):
        self._收起十字()
        QToolTip.hideText()

    def 读数文本(self, 序: int) -> str:
        """第 序 个类别的读数，一行一条线。自检脚本也直接调它。"""
        if 序 < 0 or 序 >= len(self._类别):
            return ""
        行 = [str(self._类别[序])]
        for 名, 序列 in self._系列:
            值 = 序列[序] if 序 < len(序列) else None
            行.append("%s  %s" % (名, "—" if 值 is None else ("%.*f" % (self._小数位, 值))))
        return "\n".join(行)

    def _收起十字(self):
        if self._十字 is not None:
            try:
                self._十字.setVisible(False)
            except RuntimeError:
                self._十字 = None
        self._同步图例()


def _抽稀(标签列表, 目标个数: int):
    """类别轴标签太多会重叠，等间隔抽稀。"""
    总数 = len(标签列表)
    if 总数 <= 目标个数:
        return list(标签列表)
    步长 = max(1, 总数 // 目标个数)
    末尾 = 总数 - 1
    return [标签列表[i] if i % 步长 == 0 else ("'%s" % 标签列表[末尾] if i == 末尾 and 末尾 % 步长 else "")
            for i in range(总数)]