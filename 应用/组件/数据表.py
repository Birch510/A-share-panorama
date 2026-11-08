# -*- coding: utf-8 -*-
"""
数据表：把 pandas.DataFrame 直接架到 QTableView 上。

桌面版不用 st.dataframe，自己写一个模型有三个好处：
    1. 十万行也不卡（QTableView 只渲染可见的那几十行）
    2. 列宽能按内容自动算，中文不会挤成一团
    3. 涨跌列可以按正负自动染红绿，和 K 线图一致

对外只需要一个函数：数据表(数据框, 高度, ...) -> QWidget
"""

import math
import os

import pandas as pd
from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QRect, QSortFilterProxyModel,
                            Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QBrush, QColor, QFontMetrics, QGuiApplication, QKeySequence,
                           QPainter, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QMenu, QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget)

import config
from 应用 import 主题
from 应用.组件.加载圈 import 加载圈

# 这些关键词出现在列名里，就按数值正负上色（红涨绿跌）
涨跌列关键词 = ("涨跌幅", "涨幅", "跌幅", "净额", "净流入", "净买额", "资金净流入",
                "变动幅度", "业绩变动", "涨跌额", "溢价率", "折价率")


def _是涨跌列(列名: str) -> bool:
    return any(词 in str(列名) for 词 in 涨跌列关键词)


def _格式化(值, 列名: str = "") -> str:
    """把单元格的值变成好看的中文文本。"""
    if 值 is None:
        return ""
    if isinstance(值, float):
        if math.isnan(值):
            return ""
        if math.isinf(值):
            return ""
    if isinstance(值, pd.Timestamp):
        return 值.strftime("%Y-%m-%d %H:%M:%S") if 值.hour or 值.minute else 值.strftime("%Y-%m-%d")
    if isinstance(值, bool):
        return "是" if 值 else "否"

    文本 = str(值).strip()
    if 文本 in ("nan", "NaN", "NaT", "None", "<NA>"):
        return ""

    if isinstance(值, (int, float)):
        绝对值 = abs(float(值))
        if 绝对值 >= 1e8:
            return "%.2f 亿" % (值 / 1e8)
        if 绝对值 >= 1e4 and 绝对值 < 1e8:
            return "%.2f 万" % (值 / 1e4)
        if float(值).is_integer():
            return "{:,}".format(int(值))
        return "{:,.2f}".format(值)

    return 文本


class 数据模型(QAbstractTableModel):
    """把 DataFrame 包成 Qt 能认的表格模型。"""

    def __init__(self, 数据框: pd.DataFrame = None, 父=None):
        super().__init__(父)
        self._数据 = 数据框 if isinstance(数据框, pd.DataFrame) else pd.DataFrame()
        self._涨跌列 = [i for i, c in enumerate(self._数据.columns) if _是涨跌列(c)]

    # ---------- 基础 ----------

    def rowCount(self, 父=QModelIndex()):
        return len(self._数据)

    def columnCount(self, 父=QModelIndex()):
        return len(self._数据.columns)

    def data(self, 索引: QModelIndex, 角色=Qt.DisplayRole):
        if not 索引.isValid():
            return None
        行, 列 = 索引.row(), 索引.column()
        if 行 >= len(self._数据) or 列 >= len(self._数据.columns):
            return None

        if 角色 == Qt.DisplayRole:
            列名 = self._数据.columns[列]
            return _格式化(self._数据.iat[行, 列], 列名)

        if 角色 == Qt.TextAlignmentRole:
            值 = self._数据.iat[行, 列]
            if isinstance(值, (int, float)) and not isinstance(值, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        if 角色 == Qt.ForegroundRole and 列 in self._涨跌列:
            值 = self._数据.iat[行, 列]
            if isinstance(值, (int, float)) and not isinstance(值, bool):
                if isinstance(值, float) and math.isnan(值):
                    return None
                盘 = 主题.当前调色板()
                if 值 > 0:
                    return QBrush(QColor(盘["涨"]))
                if 值 < 0:
                    return QBrush(QColor(盘["跌"]))
            return None

        if 角色 == Qt.ToolTipRole:
            # 长文本（业绩变动原因、细分来源这类）列宽装不下，悬停时给全文
            列名 = self._数据.columns[列]
            文本 = _格式化(self._数据.iat[行, 列], 列名)
            return 文本 if len(文本) > 10 else None

        return None

    def headerData(self, 序号: int, 方向, 角色=Qt.DisplayRole):
        if 角色 != Qt.DisplayRole:
            return None
        if 方向 == Qt.Horizontal:
            if 序号 < len(self._数据.columns):
                return str(self._数据.columns[序号])
            return None
        return str(序号 + 1)

    # ---------- 供导出用 ----------

    def 取数据(self) -> pd.DataFrame:
        return self._数据

    def 单元格文本(self, 行: int, 列: int) -> str:
        """要复制到剪贴板的那份文本 —— 和界面上看到的完全一致。

        不用 DataFrame 的原始值：原始值是 123456789.0 这种，界面显示的是
        「1.23 亿」；复制出去的应是用户眼睛看到的东西，粘到 Excel 里才对得上。
        """
        if 行 < 0 or 列 < 0 or 行 >= len(self._数据) or 列 >= len(self._数据.columns):
            return ""
        return _格式化(self._数据.iat[行, 列], self._数据.columns[列])

    def 换数据(self, 数据框: pd.DataFrame):
        self.beginResetModel()
        self._数据 = 数据框 if isinstance(数据框, pd.DataFrame) else pd.DataFrame()
        self._涨跌列 = [i for i, c in enumerate(self._数据.columns) if _是涨跌列(c)]
        self.endResetModel()


class 排序代理(QSortFilterProxyModel):
    """
    点表头排序。

    注意不能直接用字符串比较 —— 表格里显示的是「1.23 亿」「12.5%」这种文本，
    按文本排会把 9 排到 10 后面。这里回到原始数值去比。
    """

    def lessThan(self, 左: QModelIndex, 右: QModelIndex):
        模型 = self.sourceModel()
        if isinstance(模型, 数据模型):
            列 = 左.column()
            try:
                甲 = 模型._数据.iat[左.row(), 列]
                乙 = 模型._数据.iat[右.row(), 列]
            except Exception:
                return super().lessThan(左, 右)
            try:
                return float(甲) < float(乙)
            except Exception:
                 return str(甲) < str(乙)
        return super().lessThan(左, 右)


# 单元格左右内边距（QSS 里 ::item padding: 3px 7px）加上边框和余量
_内边距 = 20
# 列宽上下限：下限保证表头汉字不被切，上限避免一列长文本把整屏挤没
_最小列宽 = 54
_最大列宽 = 420
# 去掉空列后至少要剩这么多列，不然宁可不删（免得只剩一列没法看）
_至少留列 = 3


def _去掉空列(框: pd.DataFrame) -> tuple:
    """
    把整列都没有值的列拿掉，返回 (新数据框, 被去掉的列名列表)。

    为什么要这一步：
        有些列在数据源那头就是空的，不是我们取错 —— 例如北向资金的
        「当日成交净买额」自 2024-08 起停止日度披露，龙虎榜的「上榜后10日」
        对最近几天也必然为空。留着这些列，表里就是一片空白格，
        用户第一反应是「这里没显示出来」，而不是「这数据本来就没有」。

    判定标准（都算空）：None / NaN / 空串 / 单个 "-" 或 "—"。
    """
    去掉 = []
    if 框 is None or 框.empty:
        return 框, 去掉
    留 = 框.copy()
    for 列 in list(留.columns):
        列值 = 留[列]
        def _空(值) -> bool:
            if 值 is None:
                return True
            try:
                if pd.isna(值):
                    return True
            except (TypeError, ValueError):
                pass
            文 = str(值).strip()
            return 文 in ("", "-", "—", "nan", "None", "NaT")
        有值 = 0
        for 值 in 列值.tolist():
            if not _空(值):
                有值 += 1
                break
        if 有值 == 0:
            去掉.append(列)
    if 去掉 and len(留.columns) - len(去掉) >= _至少留列:
        return 留.drop(columns=去掉), 去掉
    return 框, []


def _估算列宽(模型: 数据模型, 字体, 最多看行: int = 300) -> list:
    """
    按表头和前若干行内容量列宽。

    必须用 QFontMetrics 真量，不能用「中文算 12px」这种估算法 —— 微软雅黑在
    12px 下一个汉字实际 12px，但数字、标点是比例字宽，估算会把股票简称这类
    短列估小 6~10px，界面上就变成「新乳...」被切掉最后半个字。
    """
    度量 = QFontMetrics(字体)
    数据 = 模型.取数据()
    if 数据 is None or len(数据.columns) == 0:
        return []
    行数 = min(len(数据), 最多看行)
    宽度 = []
    for 序, 列名 in enumerate(数据.columns):
        # 表头要额外留出排序小箭头的位子，不然点一次排序表头文字就被挤
        最宽 = 度量.horizontalAdvance(str(列名)) + 18
        for 行 in range(行数):
            文本 = _格式化(数据.iat[行, 序], 列名)
            if not 文本:
                continue
            宽 = 度量.horizontalAdvance(文本)
            if 宽 > 最宽:
                最宽 = 宽
        # 抽样只看前 300 行，长尾里可能还有更宽的，再多给一点余量
        最宽 = int(最宽 * 1.04) + _内边距
        宽度.append(max(_最小列宽, min(最宽, _最大列宽)))
    return 宽度


class 表格加载层(QWidget):
    """
    盖在表格正中央的一层「正在取数」提示。

    为什么做成遮罩而不是换页：换页会让表格尺寸跳一下；
    遮罩跟着 QTableView 走，数据到了原地淡出，视觉上表格没动过。
    背景用不透明的卡片色，顺手把空表头和「暂无数据」一起盖住 ——
    用户看到的就是「一个干净的方框，中间一圈在转」。

    位置是手算的，不用布局管理器。基准取 **viewport（数据区）的正中**，
    而不是整张 QTableView —— 表头有 36 像素高，按整张控件算会整体偏上。
    居中的对象是「圈 + 间距 + 一行字」这一整块：只把圆心压在中线上，
    下面那行字会把视觉重心往下拽，看着反而偏下。
    """

    文字默认 = "正在获取数据…"
    圈直径 = 28
    文字间距 = 10

    def __init__(self, 视图, 文本: str = ""):
        super().__init__(视图)
        self._视图 = 视图
        self.setObjectName("表格加载层")
        self.setAttribute(Qt.WA_StyledBackground, False)  # 底色由 paintEvent 自己画

        self._圈 = 加载圈(直径=self.圈直径, 线宽=2.6, 父=self)
        self._标签 = QLabel(self)
        # 用独立的对象名而不是 #空状态：空状态自带 16 像素内边距，
        # 高度会虚胖一圈，整块居中就算不准
        self._标签.setObjectName("加载说明")
        self._标签.setAlignment(Qt.AlignCenter)
        self._标签.setWordWrap(True)
        self.设文本(文本 or self.文字默认)

    # ---------- 文字 ----------

    def 设文本(self, 文本: str):
        self._文字 = 文本 or self.文字默认
        if hasattr(self, "_标签"):
            self._标签.setText(self._文字)
            self.重排()

    # ---------- 开关 ----------

    def 转起来(self):
        self._贴合()
        self.重排()
        self._圈.启动()

    def _贴合(self):
        """遮罩必须铺满整张 QTableView。

        置加载经常发生在表格刚被 new 出来、还没参与布局的时候，那时视图只有
        100 像素宽；把当时的 rect 记下来，遮罩就一直是窄窄一条，中心算出来
        停在表格最左边。这里每次转圈前按父控件当前尺寸重新贴一次。
        """
        父 = self.parentWidget()
        if 父 is not None and self.geometry() != 父.rect():
            self.setGeometry(父.rect())

    def 停(self):
        self._圈.停止()

    def 转动中(self) -> bool:
        return self._圈.转动中()

    # ---------- 位置 ----------

    def 重排(self):
        """
        把「圈 + 文字」这一整块摆到数据区正中。

        两个细节：
          1. 基准是 viewport（数据区）而不是整张 QTableView —— 表头有 36 像素高，
             按整张控件算中心会整体偏上，看着像没居中。
          2. 居中的是「块」而不是「圆心」：只有圆心压在中线时，下面那行字会把整块
             往下拽，视觉重心反而偏下。块居中才是看起来正中的做法。
        """
        区 = self._视图.viewport().geometry()      # 相对 QTableView，已扣掉表头与滚动条
        宽, 高 = self.width(), self.height()
        if 宽 <= 0 or 高 <= 0:
            return

        直径 = self.圈直径
        圈高 = self._圈.height() or 直径
        文宽 = max(60, 宽 - 24)
        # 文字的「真实」高度用字体度量算，不用 QLabel.sizeHint()：
        # 样式表给的行高比字形高，按 sizeHint 摆会让整块看着偏上几像素
        字 = QFontMetrics(self._标签.font())
        文高 = max(字.height(),
                   字.boundingRect(QRect(0, 0, 文宽, 10000),
                                 int(Qt.TextWordWrap | Qt.AlignLeft),
                                 self._标签.text()).height())
        self._标签.setFixedWidth(文宽)
        self._标签.setFixedHeight(文高)

        # 圈自己压在数据区正中。原先居中的是「圈 + 文字」整块，
        # 文字在圈下面把整块中心往下拽，圈便永远偏上十来像素 —— 看着像没居中。
        圈顶 = 区.center().y() - 圈高 // 2
        # 夹回遮罩内部，避免窗口很矮时整块跑出去
        块高 = 圈高 + self.文字间距 + 文高
        圈顶 = min(max(圈顶, 4), max(4, 高 - 块高 + 圈高 - 4))

        圈左 = 区.center().x() - (self._圈.width() or 直径) // 2
        圈左 = min(max(圈左, 4), max(4, 宽 - (self._圈.width() or 直径) - 4))
        self._圈.move(圈左, 圈顶)

        self._标签.move((宽 - 文宽) // 2, 圈顶 + 圈高 + self.文字间距)
        self.update()

    def resizeEvent(self, 事件):
        super().resizeEvent(事件)
        self.重排()

    def paintEvent(self, 事件):
        # 父控件在这期间变宽过就先贴回去，免得铺不满、露出下面的空表格
        self._贴合()
        # 用纯卡片色铺满，下面的空表格完全看不见
        盘 = 主题.当前调色板()
        画 = QPainter(self)
        画.fillRect(self.rect(), QColor(盘["卡片"]))
        画.end()


class 数据表(QWidget):
    """带导出能力的只读表格。"""

    行双击 = Signal(int)  # 参数是原始数据里的行号（不受排序影响）

    def __init__(self, 数据框: pd.DataFrame = None, 高度: int = 360,
                 标题: str = "", 可导出: bool = True, 父=None):
        super().__init__(父)
        self._标题 = 标题 or "数据"
        self._数据框 = 数据框 if isinstance(数据框, pd.DataFrame) else pd.DataFrame()
        self._加载层 = None

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(4)

        self._模型 = 数据模型(self._数据框, self)
        self._代理 = 排序代理(self)
        self._代理.setSourceModel(self._模型)

        self._视图 = QTableView(self)
        self._视图.setModel(self._代理)
        self._视图.setSortingEnabled(True)
        # 打开排序后 Qt 会先按第 0 列排一遍，且默认序是降序 —— 序号 1、2、3 会变成
        # 倒着显示。这里显式清掉排序，先按数据源原本的顺序显示，用户点表头再排。
        self._视图.sortByColumn(-1, Qt.AscendingOrder)
        self._视图.setAlternatingRowColors(True)
        self._视图.setSelectionBehavior(QAbstractItemView.SelectItems)  # 可选到单元格，才方便只复制「预测指标」那一格
        self._视图.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._视图.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._视图.setShowGrid(False)
        self._视图.verticalHeader().setVisible(False)
        self._视图.verticalHeader().setDefaultSectionSize(28)
        self._视图.horizontalHeader().setStretchLastSection(True)
        self._视图.horizontalHeader().setHighlightSections(False)
        self._视图.setMinimumHeight(高度)
        self._视图.setWordWrap(False)
        self._视图.setToolTip("选中单元格（可拖选一片）后按 Ctrl+C 复制，右键还有更多复制方式")
        self._视图.doubleClicked.connect(self._双击)

        # Ctrl+C 复制：QTableView 自己不会往剪贴板写东西，得手动接
        self._复制键 = QShortcut(QKeySequence.Copy, self._视图)
        self._复制键.setContext(Qt.WidgetWithChildrenShortcut)
        self._复制键.activated.connect(self.复制选中)

        self._视图.setContextMenuPolicy(Qt.CustomContextMenu)
        self._视图.customContextMenuRequested.connect(self._右键菜单)
        布局.addWidget(self._视图, 1)

        # 底部：行数 + 导出
        底 = QHBoxLayout()
        底.setContentsMargins(4, 0, 4, 0)
        self._计数 = QLabel("", self)
        self._计数.setObjectName("来源标注")
        底.addWidget(self._计数)
        底.addStretch(1)

        if 可导出:
            按钮 = QPushButton("导出本表", self)
            按钮.setToolTip("把当前表格存成表格文件，可直接用表格软件打开")
            按钮.clicked.connect(self._导出)
            底.addWidget(按钮)
        布局.addLayout(底)

        self.换数据(self._数据框)

    # ---------- 对外 ----------

    def 换数据(self, 数据框: pd.DataFrame, 去空列: bool = True):
        self._数据框 = 数据框 if isinstance(数据框, pd.DataFrame) else pd.DataFrame()
        # 整列都没有值的列直接不显示：留着只会让用户以为「这里坏了」
        # 例：北向资金 2024-08 起停止日度披露，四列全是 nan；龙虎榜「上榜后10日」也常常全空
        self.被去掉的列 = []
        if 去空列 and not self._数据框.empty:
            self._数据框, self.被去掉的列 = _去掉空列(self._数据框)
        self._模型.换数据(self._数据框)
        self._应用列宽()
        self._计数.setText(self._描述())
        # 数据到了就收掉中央的转圈（不管来的是真数据还是空表）
        self.置加载(False)
        # 布局还没算完时视口宽度是 1，等一轮再决定要不要拉伸最后一列
        QTimer.singleShot(0, self._调拉伸)

    def 数据(self) -> pd.DataFrame:
        return self._模型.取数据()

    def 置加载(self, 开: bool, 文本: str = "正在获取数据…"):
        """在表格数据区正中转圈；换数据时会自动收掉，不用成对调用。"""
        if 开:
            if self._加载层 is None:
                self._加载层 = 表格加载层(self._视图, 文本)
                # 出现/消失滚动条会改 viewport 的几何，位置要跟着重算
                self._视图.viewport().installEventFilter(self)
            else:
                self._加载层.设文本(文本)
            self._加载层.setGeometry(self._视图.rect())
            self._加载层.raise_()
            self._加载层.show()
            self._加载层.重排()
            # 置加载往往发生在页面刚建出来的时候，那时 viewport 还没拿到最终尺寸
            # （只有几十像素宽），按它算出来的中心会停在表格最左边。
            # 等这一轮事件走完再量一次，位置才落在数据区正中。
            QTimer.singleShot(0, self._加载层.重排)
            QTimer.singleShot(30, self._加载层.重排)
            self._加载层.转起来()
            return
        if self._加载层 is not None:
            self._加载层.停()
            self._加载层.hide()

    def 加载中(self) -> bool:
        return bool(self._加载层 is not None and self._加载层.isVisible())

    # ---------- 内部 ----------

    def _随视口(self):
        if self._加载层 is not None and self._加载层.isVisible():
            self._加载层.setGeometry(self._视图.rect())
            self._加载层.重排()

    def eventFilter(self, 对象, 事件):
        if 对象 is self._视图.viewport() and 事件.type() == QEvent.Resize:
            self._随视口()
        return super().eventFilter(对象, 事件)

    def _描述(self) -> str:
        行数 = len(self._数据框)
        if 行数 == 0:
            return "暂无数据"
        基本 = "共 %s 行 · %d 列 ｜ 点表头可排序，可多选后复制" % (
            "{:,}".format(行数), len(self._数据框.columns))
        if getattr(self, "被去掉的列", None):
            基本 += " ｜ 已隐藏 %d 个空列" % len(self.被去掉的列)
        return 基本

    def _应用列宽(self):
        宽 = _估算列宽(self._模型, self._视图.font())
        头 = self._视图.horizontalHeader()
        for 序, 值 in enumerate(宽):
            self._视图.setColumnWidth(序, 值)
        头.setSectionResizeMode(QHeaderView.Interactive)
        self._调拉伸()

    def _调拉伸(self):
        """
        总宽比视口窄时才让最后一列吃满，否则关掉拉伸。

        关掉拉伸这一条很关键：业绩预告那种 11 列的表，一旦最后一列强行拉伸，
        前面的「预测指标 / 业绩变动」就被挤成窄条，用户以为这些列没有。
        关掉之后会出现横向滚动条，所有列都还在，滚一下就能看到。
        """
        列数 = self._模型.columnCount()
        if 列数 == 0:
            return
        总宽 = sum(self._视图.columnWidth(i) for i in range(列数))
        视口 = max(self._视图.viewport().width(), 1)
        self._视图.horizontalHeader().setStretchLastSection(总宽 < 视口)

    def resizeEvent(self, 事件):
        super().resizeEvent(事件)
        self._调拉伸()
        self._随视口()

    def showEvent(self, 事件):
        # 表格在子页里被切出来时也会走这里：那会儿它才拿到真实尺寸，
        # 遮罩要趁机贴一遍，否则会停留在建表时的窄条位置。
        super().showEvent(事件)
        self._随视口()
        QTimer.singleShot(0, self._随视口)

    def _双击(self, 索引):
        源 = self._代理.mapToSource(索引)
        if 源.isValid():
            self.行双击.emit(源.row())

    # ---------- 复制 ----------
    #
    # 表格里的文字（尤其是「业绩变动原因」这种上百字的长句）用户一定想拿去
    # 粘贴到别的地方。QTableView 默认什么都不复制，所以这两条要自己实现：
    #   · 选中若干格 → Ctrl+C / 右键「复制」
    #   · 想连表头一起要 → 右键「复制整表（带表头）」
    # 复制出去的是「界面上看到的那份文本」，用制表符分列、换行分行，
    # 粘进 Excel / WPS 会自动落到格子里。

    def _选中源格(self) -> list:
        """当前选中的单元格，换成 (源行, 源列) 并按行列排好。"""
        选中 = self._视图.selectionModel()
        格 = []
        if 选中 is not None:
            for 索引 in 选中.selectedIndexes():
                源 = self._代理.mapToSource(索引)
                if 源.isValid():
                    格.append((源.row(), 源.column()))
        if not 格:
            当前 = self._视图.currentIndex()
            源 = self._代理.mapToSource(当前) if 当前.isValid() else QModelIndex()
            if 源.isValid():
                格.append((源.row(), 源.column()))
        return sorted(set(格))

    def _剪贴板(self, 文本: str):
        QGuiApplication.clipboard().setText(文本)
        self._计数.setText("已复制 %d 个字符到剪贴板" % len(文本))
        QTimer.singleShot(2600, lambda: self._计数.setText(self._描述()))

    def 复制选中(self) -> str:
        """把选中的一片单元格复制成制表符分隔的文本，返回复制的内容。"""
        格 = self._选中源格()
        if not 格:
            return ""
        行们 = sorted({行 for 行, _列 in 格})
        列们 = list(range(min(列 for _行, 列 in 格), max(列 for _行, 列 in 格) + 1))
        行号 = {行: i for i, 行 in enumerate(行们)}
        表 = [[""] * len(列们) for _ in 行们]
        for 行, 列 in 格:
            表[行号[行]][列 - 列们[0]] = self._模型.单元格文本(行, 列)
        文本 = "\n".join("\t".join(格们) for 格们 in 表)
        self._剪贴板(文本)
        return 文本

    def 复制单元格(self, 行: int, 列: int) -> str:
        """只复制一格。参数是**原始数据**的行列号（不受排序影响）。"""
        文本 = self._模型.单元格文本(行, 列)
        if 文本:
            self._剪贴板(文本)
        return 文本

    def 复制整行(self, 行: int) -> str:
        """复制一整行，不含表头。"""
        数据 = self._模型.取数据()
        if 行 < 0 or 行 >= len(数据):
            return ""
        文本 = "\t".join(self._模型.单元格文本(行, 列) for 列 in range(len(数据.columns)))
        self._剪贴板(文本)
        return 文本

    def 复制整表(self, 带表头: bool = True) -> str:
        """复制整张表。带表头时第一行是列名，粘到 Excel 里能直接当标题行。"""
        数据 = self._模型.取数据()
        if 数据.empty:
            return ""
        行们 = []
        if 带表头:
            行们.append("\t".join(str(名) for 名 in 数据.columns))
        for 行 in range(len(数据)):
            行们.append("\t".join(self._模型.单元格文本(行, 列)
                                 for 列 in range(len(数据.columns))))
        文本 = "\n".join(行们)
        self._剪贴板(文本)
        return 文本

    def _右键菜单(self, 点):
        索引 = self._视图.indexAt(点)
        if 索引.isValid() and not self._视图.selectionModel().isSelected(索引):
            # 右键点在哪一格就先选中它，符合大家的习惯
            self._视图.setCurrentIndex(索引)
        源 = self._代理.mapToSource(索引) if 索引.isValid() else QModelIndex()
        菜单 = QMenu(self)

        项 = QAction("复制（Ctrl+C）", 菜单)
        项.setEnabled(源.isValid())
        项.triggered.connect(self.复制选中)
        菜单.addAction(项)

        if 源.isValid():
            项 = QAction("只复制这一格", 菜单)
            项.triggered.connect(lambda _=False, r=源.row(), c=源.column(): self.复制单元格(r, c))
            菜单.addAction(项)
            项 = QAction("复制这一整行", 菜单)
            项.triggered.connect(lambda _=False, r=源.row(): self.复制整行(r))
            菜单.addAction(项)
            项 = QAction("复制这一列", 菜单)
            项.triggered.connect(lambda _=False, c=源.column(): self._复制整列(c))
            菜单.addAction(项)

        菜单.addSeparator()
        项 = QAction("复制整张表（带表头）", 菜单)
        项.triggered.connect(lambda _=False: self.复制整表(True))
        菜单.addAction(项)
        项 = QAction("复制整张表（不带表头）", 菜单)
        项.triggered.connect(lambda _=False: self.复制整表(False))
        菜单.addAction(项)

        菜单.addSeparator()
        项 = QAction("全选（Ctrl+A）", 菜单)
        项.triggered.connect(self._视图.selectAll)
        菜单.addAction(项)

        菜单.exec(self._视图.viewport().mapToGlobal(点))

    def _复制整列(self, 列: int) -> str:
        数据 = self._模型.取数据()
        if 数据.empty or 列 < 0 or 列 >= len(数据.columns):
            return ""
        文本 = "\n".join(self._模型.单元格文本(行, 列) for 行 in range(len(数据)))
        self._剪贴板(文本)
        return 文本

    def _导出(self):
        数据 = self._模型.取数据()
        if 数据.empty:
            QMessageBox.information(self, "导出", "表格是空的，没有可导出的数据。")
            return
        路径, 筛选 = QFileDialog.getSaveFileName(
            self, "导出表格", "%s.csv" % self._标题,
            "逗号分隔表格 (*.csv);;电子表格 (*.xlsx)")
        if not 路径:
            return
        try:
            if 路径.lower().endswith(".xlsx"):
                数据.to_excel(路径, index=False)
            else:
                数据.to_csv(路径, index=False, encoding=config.导出编码)
            QMessageBox.information(self, "导出成功", "已保存到：\n%s" % 路径)
        except Exception as 错:
            QMessageBox.warning(self, "导出失败", "写文件时出错：\n%s" % 错)


def 只读表格(数据框: pd.DataFrame = None, 高度: int = 360,
             标题: str = "", 可导出: bool = False) -> 数据表:
    """
    不带导出按钮的轻量表格，给「只是个说明性小表」的地方用。

    和 数据表() 的区别只有一个：底部不出现「导出本表」按钮。
    """
    return 数据表(数据框, 高度, 标题, 可导出)