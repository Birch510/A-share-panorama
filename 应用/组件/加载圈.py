# -*- coding: utf-8 -*-
"""
加载圈：数据还没回来的那几秒，让页面看起来「在动」，而不是「卡住了」。

为什么不直接用现成的 gif：
    1. gif 是位图，深色主题下边缘会露一圈白，放在浅色底上更明显；
    2. gif 的帧率是写死的，缩放或者高 DPI 屏上看起来一顿一顿；
    3. 换主题就得再准备一套素材，深色浅色各一张。

所以这里用 QPainter 自己画：底下一圈很淡的导轨，上面一段 100 度的弧，
弧的尾部用锥形渐变淡出，转起来像一条拖着尾巴的细光。弧头和导轨都是圆头端帽，
直径 16 像素、线宽 2 像素，和 11.5 号正文放在一行里刚好不抢视线。

用法两种：
    加载圈()                  —— 只要一个圈，自己摆位置
    加载提示(文本, 居中=True)  —— 圈 + 一行字，setText("正在取数…") 转，
                                setText("数据来源：新浪") 停。
判据就是文字里有没有「正在」或「加载」：有就转，没有就停。
这样全项目所有「正在获取…」的提示都自动带上圈，不用一个个改调用点。
"""

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from 应用 import 主题

# 一秒转一圈多一点。太快像在着急，太慢像卡住了
每秒圈数 = 0.9
帧间隔毫秒 = 16

# 弧有多长（度）。100 度是小圈里最耐看的长度，再长就显笨
弧长 = 100.0


class 加载圈(QWidget):
    """一根会转的细弧。可见时自己转，藏起来自动停，不白烧 CPU。"""

    def __init__(self, 直径: int = 16, 线宽: float = 2.0, 颜色: str = "",
                 父=None):
        super().__init__(父)
        self._直径 = 直径
        self._线宽 = 线宽
        self._颜色 = 颜色            # 留空就跟随主题
        self._角度 = 0.0
        self.setFixedSize(直径, 直径)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._计时 = QTimer(self)
        self._计时.setInterval(帧间隔毫秒)
        self._计时.timeout.connect(self._转一格)

    # ---------------------------------------------------------------- 状态

    def 启动(self):
        if not self._计时.isActive():
            self._计时.start()
        self.update()

    def 停止(self):
        if self._计时.isActive():
            self._计时.stop()
        self.update()

    def 转动中(self) -> bool:
        return self._计时.isActive()

    def 设颜色(self, 颜色: str):
        self._颜色 = 颜色 or ""
        self.update()

    def showEvent(self, 事件):
        super().showEvent(事件)
        self.启动()

    def hideEvent(self, 事件):
        self.停止()
        super().hideEvent(事件)

    def _转一格(self):
        self._角度 = (self._角度 + 360.0 * 每秒圈数 * 帧间隔毫秒 / 1000.0) % 360.0
        self.update()

    # ---------------------------------------------------------------- 绘制

    def paintEvent(self, 事件):
        盘 = 主题.当前调色板()
        笔宽 = self._线宽
        边 = 笔宽 / 2.0 + 0.5
        方框 = QRectF(self.rect()).adjusted(边, 边, -边, -边)
        if 方框.width() <= 0 or 方框.height() <= 0:
            return

        画 = QPainter(self)
        画.setRenderHint(QPainter.Antialiasing, True)

        # 底下一整圈很淡的导轨：让「转到哪」有参照，弧消失时不至于空一块
        导轨 = QColor(盘["边框深"])
        导轨.setAlpha(150)
        轨笔 = QPen(导轨)
        轨笔.setWidthF(笔宽)
        画.setPen(轨笔)
        画.drawEllipse(方框)

        # 上面那段弧：锥形渐变从头到尾淡出，尾部不着痕迹
        头色 = QColor(self._颜色 or 盘["文字2"])
        尾色 = QColor(头色)
        尾色.setAlpha(0)
        中心 = QPointF(方框.center())
        起点 = 90.0 - self._角度          # 0 度在 3 点钟方向，逆时针为正
        渐变 = QConicalGradient(中心, 起点)
        渐变.setColorAt(0.0, 头色)
        渐变.setColorAt((弧长 / 360.0) * 0.82, 尾色)
        渐变.setColorAt(1.0, 尾色)

        弧笔 = QPen(QBrush(渐变), 笔宽)
        弧笔.setCapStyle(Qt.RoundCap)
        画.setPen(弧笔)
        画.drawArc(方框, int(起点 * 16), int(弧长 * 16))
        画.end()


class 加载提示(QWidget):
    """
    一行提示：左边一个小圈，右边一句话。

    对外就是个加强版 QLabel —— setText / text 都有，所以原来
    「来源标注」放在哪、代码里怎么 setText，换了它都不用动。

    文字里带「正在」或「加载」就转圈，否则停。判据写在 _要不要转() 里，
    想加新的关键词只改那一个函数。
    """

    def __init__(self, 文本: str = "", 居中: bool = False, 对象名: str = "来源标注",
                 父=None):
        super().__init__(父)
        self._圈 = 加载圈()
        self._标签 = QLabel(文本 or "")
        self._标签.setObjectName(对象名)
        self._标签.setWordWrap(True)

        if 居中:
            外 = QVBoxLayout(self)
            外.setContentsMargins(0, 0, 0, 0)
            外.setSpacing(0)
            外.addStretch(1)
            行 = QHBoxLayout()
            行.setContentsMargins(0, 0, 0, 0)
            行.setSpacing(8)
            行.addStretch(1)
            行.addWidget(self._圈, 0, Qt.AlignVCenter)
            行.addWidget(self._标签, 0, Qt.AlignVCenter)
            行.addStretch(1)
            外.addLayout(行)
            外.addStretch(1)
        else:
            行 = QHBoxLayout(self)
            行.setContentsMargins(0, 0, 0, 0)
            行.setSpacing(8)
            行.addStretch(1)                          # 左弹簧：转圈时把内容顶到中间
            行.addWidget(self._圈, 0, Qt.AlignVCenter)
            行.addWidget(self._标签, 0)
            行.addStretch(1)                          # 右弹簧
            self._行 = 行
            self._可居中 = True

        self.setText(文本)

        # 文字会换行，所以高度得跟着宽度走。QWidget 默认把 heightForWidth 当
        # 无效，于是窗口一缩窄，标签里那句「数据来源：……」换成两行了，
        # 外层容器却还按一行的 16px 占位，第二行就被裁掉。
        # 把高度对宽度的依赖显式声明出来，布局才会重新给足高度。
        策略 = self.sizePolicy()
        策略.setHeightForWidth(True)
        策略.setVerticalPolicy(QSizePolicy.Minimum)
        self.setSizePolicy(策略)

    # ---------------------------------------------------------------- 几何

    def heightForWidth(self, 宽: int) -> int:
        布局 = self.layout()
        if 布局 is not None and 布局.hasHeightForWidth():
            高 = 布局.heightForWidth(宽)
            if 高 > 0:
                return 高
        # 交 -1 出去会让上层按「没有高度」处理，这里一律退回固定高度
        return self.sizeHint().height()

    def hasHeightForWidth(self) -> bool:
        return True

    # ---------------------------------------------------------------- 对外

    def setText(self, 文本: str):
        文本 = 文本 or ""
        self._标签.setText(文本)
        转 = self._要不要转(文本)
        if 转:
            self._圈.setVisible(True)
            self._圈.启动()
        else:
            self._圈.停止()
            self._圈.setVisible(False)
        self._排齐(转)
        self.updateGeometry()

    def _排齐(self, 转: bool):
        """转圈时把「圈 + 文字」推到这一行的正中间；停下后文字照旧左对齐。

        面板里只有一个提示行时（个股微观、图表块），原来那个圈贴着最左边转，
        看上去像跑到页面外面去了。这一行占满面板宽度，用两个弹簧把它挤到中间
        就是面板的横向中心。
        """
        if not getattr(self, "_可居中", False):
            return
        行 = self._行
        左 = 1 if 转 else 0
        行.setStretch(0, 左)        # 左弹簧
        行.setStretch(2, 0 if 转 else 1)   # 文字：转圈时按自然宽，停下后占满
        行.setStretch(3, 左)        # 右弹簧

    def text(self) -> str:
        return self._标签.text()

    def 圈(self) -> 加载圈:
        return self._圈

    def 设WordWrap(self, 开: bool):
        self._标签.setWordWrap(bool(开))

    def setWordWrap(self, 开: bool):   # 兼容 QLabel 的调用写法
        self.设WordWrap(开)

    def _要不要转(self, 文本: str) -> bool:
        return ("正在" in 文本) or ("加载" in 文本) or ("取数…" in 文本)