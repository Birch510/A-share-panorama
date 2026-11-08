# -*- coding: utf-8 -*-
"""
柱状图：横向排名图 + 竖向分布图。

两个用途：
    板块滚动市盈率排行 —— 横向，一眼看出谁贵谁便宜
    全市场涨跌幅分布 —— 竖向，看今天是普涨还是分化

正值和负值分两个色块画（不是正负都一个色），
所以涨跌分布图能直接看出红绿两侧的平衡。
"""

from PySide6.QtCharts import (QAbstractBarSeries, QBarCategoryAxis, QBarSeries, QBarSet, QChart,
                              QChartView, QHorizontalBarSeries, QStackedBarSeries, QValueAxis)
from PySide6.QtCore import QEasingCurve, QMargins, QPointF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QGraphicsSimpleTextItem, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from 应用 import 主题
from 应用.组件.加载圈 import 加载提示


class 柱状图(QWidget):
    """固定高度的一张柱状图，数据到了再画。"""

    def __init__(self, 标题: str = "", 高度: int = 260, 横向: bool = False, 父=None):
        super().__init__(父)
        self._标题 = 标题 or ""
        self._横向 = bool(横向)
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
        self._高动画 = None
        # 柱子上的数字自己画（QGraphicsSimpleTextItem），不用 Qt 的 labelsFormat
        self._图 = None
        self._标注 = []
        self._图值 = []
        self._单位 = ""
        self._小数位 = 2
        self._要标数字 = False

    # ---------------------------------------------------------------- 对外

    def 换数据(self, 标签, 值, 标题=None, 单位="", 小数位=2, 显示数值=None,
               正向色=None, 负向色=None, 轴标题="", 逐柱颜色=None):
        """
        标签：类目名列表；值：数字列表，和标签一一对应。
        显示数值：柱子上是否标数字，不传时在柱数 ≤ 14 时自动开。
        逐柱颜色：给每根柱子单独指定颜色（如涨跌分布的绿→红渐变档位），
                  传了就不再按正负分色。
        """
        标签 = [str(x) for x in (标签 or [])]
        数 = []
        for v in (值 or []):
            try:
                数.append(float(v))
            except Exception:
                数.append(0.0)
        if not 标签 or not 数:
            self.清空()
            return
        对数 = min(len(标签), len(数))
        标签 = 标签[:对数]
        数 = 数[:对数]

        if 标题 is not None:
            self._标题 = 标题
        盘 = 主题.当前调色板()
        正色 = QColor(正向色 or 盘["涨"])
        负色 = QColor(负向色 or 盘["跌"])
        if 显示数值 is None:
            显示数值 = 对数 <= 14

        if self._视图 is None:
            self._视图 = QChartView(self)
            self._视图.setRenderHint(QPainter.Antialiasing, True)
            self._视图.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.layout().addWidget(self._视图, 1)
        self._视图.setVisible(True)
        self._提示.setVisible(False)

        # 横向图里 QBarCategoryAxis 是从下往上排的，反过来喂才能让第一个在最上面
        图签 = list(reversed(标签)) if self._横向 else list(标签)
        图值 = list(reversed(数)) if self._横向 else list(数)

        正值集 = QBarSet("正")
        负值集 = QBarSet("负")
        正值集.setColor(正色)
        负值集.setColor(负色)
        for 集 in (正值集, 负值集):
            集.setBorderColor(Qt.transparent)
            集.setLabelColor(QColor(盘["文字1"]))
        有正 = any(v > 0 for v in 图值)
        有负 = any(v < 0 for v in 图值)
        小数位 = max(0, int(小数位))

        if 逐柱颜色 is not None:
            # 每根柱要不同色，QBarSet 只能整组一个颜色，
            # 所以一根柱建一个 set 堆叠起来（其余位置填 0，看不见）
            色序列 = list(逐柱颜色)[:对数]
            图色 = list(reversed(色序列)) if self._横向 else 色序列
        elif 有正 and 有负:
            # 正负两色也不能拆成两个 set 并排：那样 Qt 会把两组柱子
            # 左右各占半个槽位，柱心偏离类别中心约三四十像素，
            # 自己画的数字就会「飘在柱子旁边」。同样改成一根一个 set 堆叠。
            图色 = [正色 if v > 0 else 负色 for v in 图值]
        else:
            图色 = None

        if 图色 is not None:
            系列 = QStackedBarSeries()
            系列.setBarWidth(0.72)
            for i, 色 in enumerate(图色):
                集 = QBarSet("")
                集.setColor(QColor(色))
                集.setBorderColor(Qt.transparent)
                集.setLabelColor(QColor(盘["文字1"]))
                for j in range(对数):
                    集.append(图值[j] if j == i else 0.0)
                系列.append(集)
        else:
            if 有正:
                for v in 图值:
                    正值集.append(v if v > 0 else 0.0)
            if 有负:
                for v in 图值:
                    负值集.append(v if v < 0 else 0.0)
            if self._横向:
                系列 = QHorizontalBarSeries()
            else:
                系列 = QBarSeries()
            系列.setBarWidth(0.72)
            # 只挂真有数据的那一侧，否则全零的那一组会白画一遍，
            # 每根柱上还会多出一个「0」
            if 有正:
                系列.append(正值集)
            if 有负:
                系列.append(负值集)
            if not 有正 and not 有负:
                系列.append(正值集)

        if 显示数值:
            # 数字不用 Qt 的 labelsFormat：它的 precision 是「有效数字位数」，
            # 走的是 %g，小数位设成 1 时 40.16 会被印成「4e+1」，
            # 249.65 会印成「2e+2」—— 用户看到的就是这种科学计数法。
            # 所以数字一律自己画（见 _重排标注），文本完全由我们控制。
            系列.setLabelsVisible(False)
        self._要标数字 = bool(显示数值)
        self._图值 = list(图值)
        self._单位 = 单位 or ""
        self._小数位 = max(0, int(小数位))

        图 = QChart()
        图.setBackgroundVisible(False)
        图.setMargins(QMargins(4, 4, 8, 4))
        图.setAnimationOptions(QChart.NoAnimation)
        图.legend().setVisible(False)
        图.addSeries(系列)

        类别轴 = QBarCategoryAxis()
        类别轴.append(图签)
        类别轴.setGridLineVisible(False)
        类别轴.setLabelsColor(QColor(盘["文字2"]))
        类别轴.setLabelsFont(QFont("Microsoft YaHei UI", 7.5))

        最小值 = min(0.0, min(图值))
        最大值 = max(0.0, max(图值))
        if 最大值 - 最小值 < 1e-9:
            最大值 = 最小值 + 1.0
        余 = (最大值 - 最小值) * 0.18
        值轴 = QValueAxis()
        值轴.setRange(最小值 - (余 if 最小值 < 0 else 0), 最大值 + 余)
        值轴.setLabelFormat("%%.%df" % max(0, int(小数位)))
        轴名 = 轴标题 or 单位
        if 轴名:
            值轴.setTitleText(轴名)
            值轴.setTitleFont(QFont("Microsoft YaHei UI", 7))
            值轴.setTitleBrush(QColor(盘["文字3"]))
        值轴.setLabelsColor(QColor(盘["文字2"]))
        值轴.setLabelsFont(QFont("Microsoft YaHei UI", 7))
        值轴.setGridLineColor(QColor(盘["边框"]))
        值轴.setTickCount(5)

        if self._横向:
            图.addAxis(类别轴, Qt.AlignLeft)
            图.addAxis(值轴, Qt.AlignBottom)
        else:
            图.addAxis(类别轴, Qt.AlignBottom)
            图.addAxis(值轴, Qt.AlignLeft)
        系列.attachAxis(类别轴)
        系列.attachAxis(值轴)

        # 零轴：横竖都要有一条，否则看不出正负分界
        if self._标题:
            图.setTitle(self._标题)
            图.setTitleFont(QFont("Microsoft YaHei UI", 9, QFont.Medium))
            图.setTitleBrush(QColor(盘["文字1"]))
        self._图 = 图
        # 记下系列和轴，摆数字时用图自己的坐标映射，别自己插值算
        self._系列 = 系列
        self._类别轴 = 类别轴
        self._值轴 = 值轴
        图.plotAreaChanged.connect(lambda _区: self._重排标注())
        self._视图.setChart(图)
        QTimer.singleShot(0, self._重排标注)

    # ---------------------------------------------------------------- 柱子上的数字

    def _清标注(self):
        """把上一次画的数字全撤掉（换数据、缩放、切主题都要重画）。"""
        for 项 in self._标注:
            try:
                场景 = 项.scene()
                if 场景 is not None:
                    场景.removeItem(项)
            except RuntimeError:
                pass
        self._标注 = []

    def _重排标注(self):
        """按绘图区把每根柱子末端摆一个数字。

        文本用「%.几f + 单位」拼，不经过 Qt 的 %g 格式化，
        所以 40.16 就是 40.2、249.65 就是 249.7，绝不会变成 4e+1。
        """
        self._清标注()
        if not self._要标数字 or self._图 is None or not self._图值:
            return
        区 = self._图.plotArea()
        if 区.width() <= 2 or 区.height() <= 2:
            # 布局还没算完，下一轮再摆
            QTimer.singleShot(30, self._重排标注)
            return

        盘 = 主题.当前调色板()
        数值 = self._图值
        个数 = len(数值)
        最小值 = min(0.0, min(数值))
        最大值 = max(0.0, max(数值))
        余 = (最大值 - 最小值) * 0.18
        轴小 = 最小值 - (余 if 最小值 < 0 else 0.0)
        轴大 = 最大值 + 余
        跨度 = (轴大 - 轴小) or 1.0
        系列 = getattr(self, "_系列", None)

        字体 = QFont("Microsoft YaHei UI", 7.5)
        颜色 = QColor(盘["文字2"])
        格式 = "%%.%df" % self._小数位
        for i, v in enumerate(数值):
            文本 = (格式 % v) + self._单位
            项 = QGraphicsSimpleTextItem(文本, self._图)
            项.setFont(字体)
            项.setBrush(颜色)
            宽 = 项.boundingRect().width()
            高 = 项.boundingRect().height()
            # 柱子的真实位置由图表自己算：QBarSeries 会在绘图区里再留一圈内缩，
            # 自己用区.left() + (i+0.5)/个数*区.width() 插值会偏出三五十像素，
            # 数字看着就像「飘在柱子旁边」。所以一律用 mapToPosition 问图要点位。
            点 = None
            if 系列 is not None:
                try:
                    点 = self._图.mapToPosition(QPointF(float(i), float(v)), 系列)
                except (RuntimeError, TypeError):
                    点 = None
            # 横向图里类别轴在左边、值轴在下面，mapToPosition 的参数顺序和竖向不同，
            # 传错会算到画布外面去。所以对结果做个范围校验，不合理就退回按轴插值。
            if 点 is not None and not (区.left() - 6 <= 点.x() <= 区.right() + 6
                                       and 区.top() - 6 <= 点.y() <= 区.bottom() + 6):
                点 = None
            if 点 is None:
                if self._横向:
                    点 = QPointF(区.left() + (v - 轴小) / 跨度 * 区.width(),
                                区.bottom() - (i + 0.5) / 个数 * 区.height())
                else:
                    点 = QPointF(区.left() + (i + 0.5) / 个数 * 区.width(),
                                区.bottom() - (v - 轴小) / 跨度 * 区.height())
            if self._横向:
                x = 点.x() + 4 if v >= 0 else 点.x() - 宽 - 4
                y = 点.y() - 高 / 2.0
            else:
                x = 点.x() - 宽 / 2.0
                y = 点.y() - 高 - 3 if v >= 0 else 点.y() + 3
            项.setPos(x, y)
            self._标注.append(项)

    def 标注文本(self):
        """给验证用的：当前图上每个数字的文本与位置。"""
        return [(项.text(), 项.pos().x(), 项.pos().y()) for 项 in self._标注]

    def 清空(self, 文本: str = "暂无数据"):
        self._清标注()
        self._图 = None
        self._图值 = []
        self._提示.setText(文本)
        self._提示.setVisible(True)
        if self._视图 is not None:
            self._视图.setVisible(False)

    def resizeEvent(self, 事件):
        super().resizeEvent(事件)
        QTimer.singleShot(0, self._重排标注)

    def 置高(self, 高: int, 毫秒: int = 0):
        """改图的高度，给「放大」用；毫秒为 0 时立刻生效。"""
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


def 横排(标签, 值, 标题="", 高度=280, 正向色=None, 小数位=2, 轴标题=""):
    """常用组合：横向排名图，快速造一个。"""
    图 = 柱状图(标题, 高度=高度, 横向=True)
    图.换数据(标签, 值, 标题=标题, 正向色=正向色, 小数位=小数位, 轴标题=轴标题)
    return 图