# -*- coding: utf-8 -*-
"""
板块热力图：一眼看出今天哪些板块在涨、哪些在跌、钱都堆在哪里。

实现说明（为什么自己画，而不是装一个现成的图库）：
    1. 桌面版已经不用网页图表库了，再为一张热力图引一个绘制引擎不划算；
    2. 热力图的本质就是把矩形铺满一块区域，用 QPainter 直接画反而更快，
       几百个板块也是一次 paintEvent 画完，滚动、切主题都不掉帧；
    3. 可以精确控制中文字体、颜色深浅、悬停高亮，和别的页面视觉一致。

排版算法用 squarified treemap（Bruls/Huizing/van Wijk 2000），
核心思想是每行都尽量接近正方形 —— 长条形的色块很难看清，接近正方形才好认。
"""

import math

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from 应用 import 主题

# 涨跌幅到颜色的映射：±5% 以上就按最深的一档算，再深意义不大
颜色上限 = 5.0
# 面积用成交额算，但直接按比例画会让小板块小到看不见，
# 开个 0.8 次方压缩一下（图注里会说明「面积按成交额压缩」）
面积指数 = 0.8


def _混色(底色: QColor, 目标: QColor, 比例: float) -> QColor:
    """在两种颜色之间线性插值，比例 0 = 全底色，1 = 全目标色。"""
    比例 = max(0.0, min(1.0, 比例))
    return QColor(
        int(底色.red() + (目标.red() - 底色.red()) * 比例),
        int(底色.green() + (目标.green() - 底色.green()) * 比例),
        int(底色.blue() + (目标.blue() - 底色.blue()) * 比例),
    )


def _太暗(颜色: QColor) -> bool:
    """判断底色深不深，决定上面写字用白还是用黑。"""
    亮度 = 0.299 * 颜色.red() + 0.587 * 颜色.green() + 0.114 * 颜色.blue()
    return 亮度 < 150


def _排布(面积表: list, 区域: QRectF) -> list:
    """
    squarified treemap：把一组面积铺进一个矩形，返回每个面积对应的矩形。

    面积表必须已经按从大到小排好序，算法才能保证先铺大的、块也最方。
    """
    if not 面积表:
        return []
    总面积 = sum(面积表)
    if 总面积 <= 0:
        return []

    # 归一化：把数值换成「占整个区域的像素面积」
    缩放 = (区域.width() * 区域.height()) / 总面积
    剩余 = [值 * 缩放 for 值 in 面积表]

    结果 = []
    x, y = 区域.x(), 区域.y()
    宽, 高 = 区域.width(), 区域.height()
    下标 = 0

    while 下标 < len(剩余):
        边 = min(宽, 高)
        if 边 <= 0:
            break

        # 贪心地往当前行里加，只要「最差长宽比」在变好就继续加
        行 = [剩余[下标]]
        下一 = 下标 + 1
        while 下一 < len(剩余):
            旧 = _最差长宽比(行, 边)
            新 = _最差长宽比(行 + [剩余[下一]], 边)
            if 新 <= 旧:
                行.append(剩余[下一])
                下一 += 1
            else:
                break

        行和 = sum(行)
        if 行和 <= 0:
            下标 = 下一
            continue

        if 宽 >= 高:
            # 横着留一条：这一行占满整个高度，宽度按面积比例分
            行宽 = 行和 / 高 if 高 else 0
            yy = y
            for 面积 in 行:
                块高 = (面积 / 行宽) if 行宽 else 0
                结果.append(QRectF(x, yy, 行宽, 块高))
                yy += 块高
            x += 行宽
            宽 -= 行宽
        else:
            # 竖着留一条：这一行占满整个宽度，高度按面积比例分
            行高 = 行和 / 宽 if 宽 else 0
            xx = x
            for 面积 in 行:
                块宽 = (面积 / 行高) if 行高 else 0
                结果.append(QRectF(xx, y, 块宽, 行高))
                xx += 块宽
            y += 行高
            高 -= 行高

        下标 = 下一

    return 结果


def _最差长宽比(行: list, 边: float) -> float:
    """一组面积排成一行时的最差长宽比，越小越方。"""
    if not 行 or 边 <= 0:
        return float("inf")
    和 = sum(行)
    if 和 <= 0:
        return float("inf")
    最大 = max(行)
    最小 = min(行)
    if 最小 <= 0:
        return float("inf")
    return max((边 * 边 * 最大) / (和 * 和), (和 * 和) / (边 * 边 * 最小))


class 热力图(QWidget):
    """
    板块热力图控件。

    数据用 换数据(项列表)，每项是 (板块名称, 涨跌幅, 面积值, 补充说明)。
    面积值一般传成交额；涨跌幅决定颜色深浅。
    """

    点击板块 = Signal(str)
    双击 = Signal()          # 双击整块热力图（用来展开 / 收起）

    def __init__(self, 高度: int = 380, 父=None):
        super().__init__(父)
        self._项 = []
        self._块 = []          # [(名称, 矩形, 涨跌幅, 补充)]，每次重排时算一次
        self._悬停 = -1
        self._提示 = ""
        # 展开动画用：起块 / 终块按板块名称配对，绘制时按进度插值
        self._进度 = 1.0
        self._起块 = {}
        self._终块 = {}
        self._动画 = None
        self._默认高 = 高度
        self.setMinimumHeight(高度)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip(self._提示)

    # ---------- 对外 ----------

    def 换数据(self, 项列表: list, 说明: str = ""):
        """
        项列表：[{'名称': str, '涨跌幅': float, '面积': float, '说明': str}, ...]
        说明：图下方的口径说明，悬停空白处会显示。
        """
        清洗 = []
        for 项 in 项列表 or []:
            try:
                名 = str(项.get("名称", "")).strip()
                涨跌 = float(项.get("涨跌幅", 0) or 0)
                面积 = float(项.get("面积", 0) or 0)
            except Exception:
                continue
            if not 名:
                continue
            if 面积 <= 0:
                面积 = 1.0
            清洗.append({"名称": 名, "涨跌幅": 涨跌, "面积": 面积,
                       "说明": str(项.get("说明", "") or "")})
        清洗.sort(key=lambda 项: 项["面积"], reverse=True)
        self._项 = 清洗
        self._提示 = 说明
        self._悬停 = -1
        self._重排()
        self.update()

    def 数量(self) -> int:
        return len(self._项)

    def 清空(self):
        self._项 = []
        self._块 = []
        self._悬停 = -1
        self.update()

    # ---------- 排布 ----------

    def _算块(self, 宽: float, 高: float) -> list:
        """按给定尺寸算一遍每个方块的位置，不动任何状态。"""
        出 = []
        if not self._项:
            return 出
        内 = QRectF(0, 0, 宽, 高).adjusted(1, 1, -1, -1)
        if 内.width() <= 2 or 内.height() <= 2:
            return 出
        面积表 = [max(项["面积"], 0.0) ** 面积指数 for 项 in self._项]
        矩形表 = _排布(面积表, 内)
        for 项, 矩形 in zip(self._项, 矩形表):
            出.append((项["名称"], 矩形, 项["涨跌幅"], 项["说明"]))
        return 出

    def _重排(self, 动画: bool = False):
        新块 = self._算块(self.width(), self.height())
        if 动画 and self._块 and 新块:
            self._起块 = {块[0]: QRectF(块[1]) for 块 in self._块}
            self._终块 = {块[0]: QRectF(块[1]) for 块 in 新块}
            self._块 = 新块
            self._进度 = 0.0
            self._启动动画(280)
            return
        self._块 = 新块
        self._起块 = {}
        self._终块 = {}
        self._进度 = 1.0

    def 过渡到高度(self, 高: int, 毫秒: int = 280):
        """
        改变自己的高度，并让每个方块从旧位置平滑长到新位置。

        不能只依赖 resizeEvent —— 它要等一轮事件循环才来，
        那时我们已经没有「旧位置」可以当起点了。所以这里先手动按新尺寸
        算一遍终点，再启动插值，resizeEvent 在动画期间会跳过重排。
        """
        高 = int(max(80, 高))
        旧块 = {块[0]: QRectF(块[1]) for 块 in self._块}
        self.setMinimumHeight(高)
        self.setMaximumHeight(高)
        self.updateGeometry()

        新块 = self._算块(self.width(), 高)
        if not 旧块 or not 新块:
            self._块 = 新块
            self._起块 = {}
            self._终块 = {}
            self._进度 = 1.0
            self.update()
            return

        self._起块 = 旧块
        self._终块 = {块[0]: QRectF(块[1]) for 块 in 新块}
        self._块 = 新块
        self._进度 = 0.0
        self._启动动画(毫秒)

    def _启动动画(self, 毫秒: int):
        if self._动画 is not None:
            self._动画.stop()
        动 = QVariantAnimation(self)
        动.setStartValue(0.0)
        动.setEndValue(1.0)
        动.setDuration(int(max(60, 毫秒)))
        动.setEasingCurve(QEasingCurve.OutCubic)
        动.valueChanged.connect(self._动画帧)
        动.finished.connect(self._动画结束)
        self._动画 = 动
        动.start()

    def _动画帧(self, 值):
        self._进度 = float(值)
        self.update()

    def _动画结束(self):
        self._进度 = 1.0
        self._起块 = {}
        self._终块 = {}
        self.update()

    def _显示矩形(self, 名称: str, 矩形: QRectF) -> QRectF:
        """动画进行中就把起点和终点按进度插值，否则直接用终点。"""
        if self._进度 >= 1.0:
            return 矩形
        起 = self._起块.get(名称)
        终 = self._终块.get(名称)
        if 起 is None or 终 is None:
            return 矩形
        比 = self._进度
        return QRectF(
            起.x() + (终.x() - 起.x()) * 比,
            起.y() + (终.y() - 起.y()) * 比,
            起.width() + (终.width() - 起.width()) * 比,
            起.height() + (终.height() - 起.height()) * 比,
        )

    def resizeEvent(self, 事件):
        super().resizeEvent(事件)
        # 展开动画进行中，resize 是动画自己引起的，别把终点冲掉
        if self._进度 < 1.0 and self._终块:
            return
        self._重排()

    # ---------- 绘制 ----------

    def paintEvent(self, 事件):
        画 = QPainter(self)
        画.setRenderHint(QPainter.Antialiasing, True)
        画.setRenderHint(QPainter.TextAntialiasing, True)

        盘 = 主题.当前调色板()
        底 = QColor(盘["卡片"])
        涨色 = QColor(盘["涨"])
        跌色 = QColor(盘["跌"])

        画.fillRect(self.rect(), 底)

        if not self._块:
            画.setPen(QColor(盘["文字3"]))
            字体 = QFont(self.font())
            字体.setPixelSize(12)
            画.setFont(字体)
            画.drawText(self.rect(), Qt.AlignCenter, "还没有数据")
            return

        名称字体 = QFont(self.font())
        名称字体.setPixelSize(12)
        名称字体.setBold(True)
        数值字体 = QFont(self.font())
        数值字体.setPixelSize(11)

        for 序, (名称, 矩形, 涨跌, _说明) in enumerate(self._块):
            矩形 = self._显示矩形(名称, 矩形)
            if 矩形.width() < 1 or 矩形.height() < 1:
                continue
            强度 = min(abs(涨跌) / 颜色上限, 1.0)
            基色 = 涨色 if 涨跌 >= 0 else 跌色
            填充 = _混色(底, 基色, 0.14 + 0.80 * 强度)
            if 序 == self._悬停:
                填充 = _混色(填充, QColor(255, 255, 255), 0.22)

            块 = 矩形.adjusted(0.5, 0.5, -0.5, -0.5)
            画.setPen(Qt.NoPen)
            画.setBrush(填充)
            画.drawRect(块)

            if 序 == self._悬停:
                画.setBrush(Qt.NoBrush)
                画.setPen(QPen(QColor(盘["文字1"]), 1.6))
                画.drawRect(块)

            # 太小的块不写字，否则全是重叠的黑点
            if 块.width() < 34 or 块.height() < 22:
                continue

            文字色 = QColor(255, 255, 255) if _太暗(填充) else QColor(盘["文字1"])
            画.setPen(文字色)
            画.setFont(名称字体)
            内 = 块.adjusted(4, 2, -4, -2)

            名 = self._省略(画, 名称, 内.width())
            画.drawText(QRectF(内.x(), 内.y(), 内.width(), 内.height() / 2 + 2),
                        Qt.AlignLeft | Qt.AlignVCenter, 名)

            if 内.height() >= 30 and 内.width() >= 40:
                画.setFont(数值字体)
                画.drawText(QRectF(内.x(), 内.y() + 内.height() / 2,
                                 内.width(), 内.height() / 2),
                            Qt.AlignLeft | Qt.AlignVCenter, "%+.2f%%" % 涨跌)

    def _省略(self, 画: QPainter, 文本: str, 可用: float) -> str:
        """装不下就截断加省略号。"""
        度量 = 画.fontMetrics()
        if 度量.horizontalAdvance(文本) <= 可用:
            return 文本
        for 长度 in range(len(文本) - 1, 0, -1):
            试 = 文本[:长度] + "…"
            if 度量.horizontalAdvance(试) <= 可用:
                return 试
        return ""

    # ---------- 交互 ----------

    def _命中(self, 位置) -> int:
        点 = QPointF(位置)
        for 序, (名称, 矩形, _涨, _说) in enumerate(self._块):
            if self._显示矩形(名称, 矩形).contains(点):
                return 序
        return -1

    def mouseMoveEvent(self, 事件):
        新 = self._命中(事件.position())
        if 新 != self._悬停:
            self._悬停 = 新
            if 新 >= 0:
                名称, _矩形, 涨跌, 说明 = self._块[新]
                文本 = "%s　%+.2f%%" % (名称, 涨跌)
                if 说明:
                    文本 += "\n" + 说明
                文本 += "\n单击查看成分股"
                QToolTip.showText(事件.globalPosition().toPoint(), 文本, self)
                self.setCursor(Qt.PointingHandCursor)
            else:
                QToolTip.hideText()
                self.setCursor(Qt.ArrowCursor)
            self.update()
        super().mouseMoveEvent(事件)

    def leaveEvent(self, 事件):
        if self._悬停 != -1:
            self._悬停 = -1
            self.update()
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(事件)

    def mousePressEvent(self, 事件):
        if 事件.button() == Qt.LeftButton:
            序 = self._命中(事件.position())
            if 序 >= 0:
                self.点击板块.emit(self._块[序][0])
        super().mousePressEvent(事件)

    def mouseDoubleClickEvent(self, 事件):
        """双击任意位置 = 展开 / 收起，双击也意味着用户不是想选某一格。"""
        if 事件.button() == Qt.LeftButton:
            self.双击.emit()
        super().mouseDoubleClickEvent(事件)