# -*- coding: utf-8 -*-
"""通用小部件：指标卡、分区标题、来源标注、空状态、卡片容器。

这些是十个页面都要用到的最小单元，集中放一处，改一次全站生效。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from 应用 import 主题
from 应用.组件.加载圈 import 加载提示


def _是涨跌文本(文本: str) -> bool:
    return ("涨" in 文本) or ("跌" in 文本) or ("幅" in 文本)


class 指标卡(QFrame):
    """一张小卡：上面指标名、中间大数字、下面一行注释。"""

    def __init__(self, 名称: str, 值: str, 注释: str = "", 涨跌: int = 0, 父=None):
        """
        涨跌：0 中性（默认配色）、1 利好（红）、-1 利空（绿）。
        不传就按数值文本里的正负号自动判断。
        """
        super().__init__(父)
        self.setObjectName("指标卡")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFrameShape(QFrame.NoFrame)

        # 注释那行会换行，窗口拉窄时「-2.73%  -304.41」从一行变两行。
        # 高度在下面用「最少两行」兜住，这里竖直方向仍用 Fixed：
        # 高度一旦交给 heightForWidth，minimumSizeHint 会掉到 1 像素，
        # 整排卡会被压成十几像素高。
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(16, 12, 16, 12)
        布局.setSpacing(4)

        名 = QLabel(名称, self)
        名.setObjectName("指标名")
        布局.addWidget(名)

        self._值 = QLabel(值, self)
        self._值.setObjectName("指标值")
        self._值.setTextInteractionFlags(Qt.TextSelectableByMouse)
        布局.addWidget(self._值)

        self._注释 = QLabel(注释, self)
        self._注释.setObjectName("指标注释")
        self._注释.setWordWrap(True)
        self._注释.setVisible(bool(注释))
        # 注释那行会换行：窗口窄下来时「-2.73%  -304.41」会从一行变两行，
        # 若只按一行留高度，第二行就被切掉。这里一次性留够两行，
        # 四张卡等宽同高，不会因为某张字数多就矮一截。
        # 不靠 heightForWidth 交还高度——QLabel 的换行高度在布局里不被认账，
        # 而且它会让 minimumSizeHint 掉到 1 像素，整排卡直接被压扁。
        self._注释.setMinimumHeight(int(QFontMetrics(self._注释.font()).lineSpacing() * 2))
        布局.addWidget(self._注释)

        self._涨跌 = 涨跌 if 涨跌 != 0 else self._猜方向(值)
        self._上色()

    # ------------------------------------------------------------ 高度

    @staticmethod
    def _猜方向(值文本: str) -> int:
        文本 = str(值文本).strip()
        if 文本.startswith("+") or 文本.startswith("＋"):
            return 1
        if 文本.startswith("-") or 文本.startswith("－"):
            return -1
        return 0

    def _上色(self):
        if self._涨跌 == 0:
            return
        盘 = 主题.当前调色板()
        self._值.setStyleSheet("color: %s;" % (盘["涨"] if self._涨跌 > 0 else 盘["跌"]))

    def 换值(self, 值: str, 注释: str = None, 涨跌: int = None):
        self._值.setText(值)
        if 注释 is not None:
            self._注释.setText(注释)
            self._注释.setVisible(bool(注释))
        if 涨跌 is not None:
            self._涨跌 = 涨跌 if 涨跌 != 0 else self._猜方向(值)
        else:
            self._涨跌 = self._猜方向(值)
        self._值.setStyleSheet("")
        self._上色()


def 指标行(项列表, 每行: int = 4) -> QWidget:
    """
    一排指标卡。

    项列表的每一项是 (名称, 值, 注释) 或 (名称, 值, 注释, 涨跌)。
    超过「每行」就自动换行，避免挤成一条看不清。
    """
    外层, _卡 = 指标行卡(项列表, 每行)
    return 外层


def 指标行卡(项列表, 每行: int = 4):
    """
    和 指标行 一样，但额外把每张卡的引用返回，方便数据回来时只改数值。

    用途：页面先用「—」占位把卡片画出来，后台拿到了再逐张 换值()。
    这样点进页面瞬间就能看到骨架，不会盯着「正在统计…」以为坏了。
    """
    外层 = QWidget()
    纵向 = QVBoxLayout(外层)
    纵向.setContentsMargins(0, 0, 0, 0)
    纵向.setSpacing(12)

    卡列表 = []
    缓冲 = []
    for 项 in 项列表:
        名称, 值 = 项[0], 项[1]
        注释 = 项[2] if len(项) > 2 else ""
        涨跌 = 项[3] if len(项) > 3 else 0
        卡 = 指标卡(名称, 值, 注释, 涨跌)
        卡列表.append(卡)
        缓冲.append(卡)

        if len(缓冲) == 每行:
            纵向.addLayout(_排(缓冲))
            缓冲 = []

    if 缓冲:
        while len(缓冲) < 每行:  # 补齐，让同一行卡片等宽
            缓冲.append(QWidget())
        纵向.addLayout(_排(缓冲))

    return 外层, 卡列表


def _排(卡片列表) -> QHBoxLayout:
    行 = QHBoxLayout()
    行.setContentsMargins(0, 0, 0, 0)
    行.setSpacing(8)
    for 卡 in 卡片列表:
        行.addWidget(卡, 1)
    return 行


class 分区标题(QWidget):
    """一段内容的标题 + 一行灰色说明。

    说明那行永远建出来（没文字时先隐藏），因为成分股区要靠它显示
    「正在获取…」「共 485 只 · 数据来源：新浪概念库」这种动态文字。
    """

    def __init__(self, 标题: str, 说明: str = "", 父=None):
        super().__init__(父)
        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 16, 0, 4)
        布局.setSpacing(4)

        主 = QLabel(标题, self)
        主.setObjectName("分区标题")
        布局.addWidget(主)

        self._副 = QLabel(说明, self)
        self._副.setObjectName("分区说明")
        self._副.setWordWrap(True)
        self._副.setVisible(bool(说明))
        布局.addWidget(self._副)

    def 设说明(self, 文本: str):
        self._副.setText(文本 or "")
        self._副.setVisible(bool(文本))


def 分区(标题: str, 说明: str = "") -> 分区标题:
    return 分区标题(标题, 说明)


def 来源标注(来源: str, 说明: str = "") -> 加载提示:
    """
    表格/图下面的「数据来源」一行。

    返回的是 加载提示 而不是纯 QLabel：它上面带一个小圈，
    文字里出现「正在」或「加载」就自己转起来，数据回来改成
    「数据来源：新浪」就自动停。对外 setText / text 都有，用法和 QLabel 一样。
    """
    文本 = "数据来源：%s" % (来源 or "未知")
    if 说明:
        文本 += " ｜ %s" % 说明
    return 加载提示(文本)


def 空状态(文本: str = "暂无数据") -> 加载提示:
    """空区域里那一句居中提示，同样是带圈的。"""
    return 加载提示(文本, 居中=True, 对象名="空状态")


def 卡片(内容: QWidget, 内边距: int = 16) -> QFrame:
    """把一个控件装进带边框的圆角卡片里。"""
    框 = QFrame()
    框.setObjectName("卡片")
    框.setFrameShape(QFrame.NoFrame)
    布局 = QVBoxLayout(框)
    布局.setContentsMargins(内边距, 内边距, 内边距, 内边距)
    布局.setSpacing(8)
    布局.addWidget(内容)
    return 框


def 横排(*控件, 间距: int = 8) -> QWidget:
    """把几个控件横向排一行（左对齐，右侧留白）。"""
    外层 = QWidget()
    行 = QHBoxLayout(外层)
    行.setContentsMargins(0, 0, 0, 0)
    行.setSpacing(间距)
    for 件 in 控件:
        if 件 is None:
            continue
        行.addWidget(件)
    行.addStretch(1)
    return 外层


class 分段选择器(QWidget):
    """
    一排互斥按钮，当前选中那个是实心底。

    用它代替网页里的标签页 —— 桌面上按钮更好点，而且能一眼看出现在在第几页。
    """

    选择变化 = Signal(str)

    def __init__(self, 选项: list, 当前: str = "", 父=None):
        super().__init__(父)
        self._选项 = list(选项)
        self._当前 = 当前 or (self._选项[0] if self._选项 else "")

        行 = QHBoxLayout(self)
        行.setContentsMargins(0, 0, 0, 0)
        行.setSpacing(8)

        self._组 = QButtonGroup(self)
        self._组.setExclusive(True)
        for 名 in self._选项:
            钮 = QPushButton(名, self)
            钮.setObjectName("主题按钮")
            钮.setCheckable(True)
            钮.setCursor(Qt.PointingHandCursor)
            钮.setChecked(名 == self._当前)
            钮.clicked.connect(lambda _=False, n=名: self._点了(n))
            self._组.addButton(钮)
            行.addWidget(钮)
        行.addStretch(1)

    def _点了(self, 名: str):
        if 名 == self._当前:
            return
        self._当前 = 名
        self.选择变化.emit(名)

    def 当前(self) -> str:
        return self._当前

    def 设当前(self, 名: str):
        if 名 not in self._选项:
            return
        self._当前 = 名
        for 钮 in self._组.buttons():
            钮.setChecked(钮.text() == 名)