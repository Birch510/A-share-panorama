# -*- coding: utf-8 -*-
"""
页面小助手：把「后台取数 → 填进控件」这套重复动作收拢起来。

十个页面里大部分区块都是「一张表 + 一行数据来源」，写法一模一样，
只是取数函数不同。与其抄十遍，不如在这里写一次。
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from 应用.后台任务 import 后台运行
from 应用.组件.基础 import 指标行, 指标行卡, 来源标注
from 应用.组件.数据表 import 数据表
from 应用.组件.加载圈 import 加载提示


def _拆结果(结果):
    """把 (DataFrame, 错误, 来源) 或 (DataFrame, 错误) 拆成三样。"""
    if not isinstance(结果, tuple):
        return 结果, "", ""
    框 = 结果[0] if len(结果) > 0 else None
    错误 = 结果[1] if len(结果) > 1 else ""
    来源 = 结果[2] if len(结果) > 2 else ""
    return 框, (错误 or ""), (来源 or "")


def 加载表格(取数函数, 参数=(), 标题: str = "", 高度: int = 420,
             来源文字: str = "", 可导出: bool = True) -> QWidget:
    """
    建一块「表 + 来源」区域，立刻返回，数据在后台拉，到了自动填。

    取数函数必须返回 (DataFrame, 错误, 来源) 这种三元组（本项目所有取数层都是）。
    """
    块 = 可刷新表格(取数函数, 标题=标题, 高度=高度, 来源文字=来源文字, 可导出=可导出)
    块.刷新(*参数)
    return 块


class 可刷新表格(QWidget):
    """
    带「刷新」按钮的表：参数变了可以重新取一次数。

    有些区块要跟着页面上的日期、条数、关键字一起变（比如涨停股池看哪天），
    这种就不能用一次性的 加载表格，需要拿着这个对象再叫一次 刷新(新参数)。
    """

    def __init__(self, 取数函数, 标题: str = "", 高度: int = 420,
                 来源文字: str = "", 可导出: bool = True, 父=None):
        super().__init__(父)
        self._函数 = 取数函数
        self._来源文字 = 来源文字

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(8)

        self.表 = 数据表(None, 高度=高度, 标题=标题 or "数据", 可导出=可导出)
        布局.addWidget(self.表)
        self.提示 = 来源标注(来源文字 or "正在加载…")
        布局.addWidget(self.提示)
        self.原始 = None      # 上一次拿到的完整数据，供页面自己做筛选/导出
        self._参数 = ()       # 上一次刷新用的参数，全局刷新时原样重放
        self.刷新后 = None    # 可选的收尾回调（比如把关键字筛选重新套一遍）
        self._收尾中 = False  # 防止收尾回调又触发一次收尾

    def 刷新(self, *参数):
        self._参数 = tuple(参数)
        self.提示.setText("正在取数…")
        self.表.置加载(True, "正在获取数据…")
        后台运行(self._函数, 完成=self._到了, 失败=self._失败, 参数=self._参数)

    def 重取(self):
        """按上一次的参数再取一遍。全局刷新按钮走这个入口。"""
        self.刷新(*self._参数)

    def _到了(self, 结果):
        try:
            框, 错误, 来源 = _拆结果(结果)
        except Exception:
            self.表.置加载(False)
            self.提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or getattr(框, "empty", True):
            self.原始 = None
            self.表.换数据(None)
            self.提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        self.原始 = 框
        self._显示(框, 来源)

    def _显示(self, 框, 来源: str = ""):
        self.表.换数据(框)
        self.提示.setText("数据来源：%s ｜ %d 行"
                         % (来源 or self._来源文字 or "未知", len(框)))
        self._收尾()

    def _收尾(self):
        """
        数据换完之后的应用层收尾。

        现在只有一个用处：事件页的表格带着关键字筛选，重新取数以后
        如果没人把筛选再套一遍，表里会突然冒出全量数据，而输入框里的字还在。
        """
        if self.刷新后 is None or self._收尾中:
            return
        self._收尾中 = True
        try:
            self.刷新后()
        except Exception as 错:
            print("刷新收尾失败：", 错)
        finally:
            self._收尾中 = False

    def _失败(self, 错误文本: str):
        self.表.置加载(False)
        self.提示.setText("取数失败：%s" % 错误文本)


def 加载指标(取数函数, 参数=(), 说明: str = "", 每行: int = 4,
             骨架=None, 来源文字: str = "") -> QWidget:
    """
    建一块指标卡区域，取数函数要返回 (字典, 错误) 或 (字典, 错误, 来源)。

    骨架：可选的键列表。传了就先按这些键把卡片画出来（值显示「—」），
    数据回来再逐张换值。不传就退回「先显示一行正在加载…，到了再整块画」。

    为什么要骨架：点进情绪复盘时，涨跌停家数要联网统计几秒。
    如果这几秒页面上只有一行「正在统计当日情绪数据…」，用户会以为这页坏了。
    先摆六张空卡、数字再填进来，观感上就是「在刷新」而不是「没刷新」。
    """
    块 = 可刷新指标(取数函数, 说明=说明, 每行=每行, 骨架=骨架, 来源文字=来源文字)
    块.刷新(*参数)
    return 块


class 可刷新指标(QWidget):
    """带「重取」能力的指标卡区域，参数和骨架的约定同 加载指标。"""

    def __init__(self, 取数函数, 说明: str = "", 每行: int = 4,
                 骨架=None, 来源文字: str = "", 父=None):
        super().__init__(父)
        self._函数 = 取数函数
        self._参数 = ()
        self._每行 = 每行
        self._说明 = 说明
        self._来源文字 = 来源文字
        self._卡片 = []
        self._行 = None

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(8)
        self._布局 = 布局

        self._提示 = None
        if 骨架:
            卡区, 卡片 = 指标行卡([(str(名), "—", "", 0) for 名 in 骨架], 每行=每行)
            布局.addWidget(卡区)
            self._卡片 = 卡片
        else:
            self._提示 = 加载提示(说明 or "正在加载…", 居中=True,
                                  对象名="空状态", 父=self)
            布局.addWidget(self._提示)

        self._来源 = 来源标注(来源文字 or "正在加载…")
        布局.addWidget(self._来源)

    def 刷新(self, *参数):
        self._参数 = tuple(参数)
        self._来源.setText("正在取数…")
        if self._提示 is not None:
            self._提示.setText(self._说明 or "正在取数…")
            self._提示.setVisible(True)
        后台运行(self._函数, 完成=self._到了, 失败=self._失败, 参数=self._参数)

    def 重取(self):
        """按上一次的参数再取一遍。全局刷新按钮走这个入口。"""
        self.刷新(*self._参数)

    def _到了(self, 结果):
        框, 错误, 来源文本 = _拆结果(结果)
        if not isinstance(框, dict) or not 框:
            文本 = "没有取到数据：%s" % (错误 or "接口返回为空")
            if self._提示 is not None:
                self._提示.setText(文本)
                self._提示.setVisible(True)
            else:
                self._来源.setText(文本)
            return
        if self._提示 is not None:
            self._提示.setVisible(False)
        项列表 = [(str(键), _好看(值), "", 0) for 键, 值 in 框.items()]
        if self._卡片 and len(self._卡片) == len(项列表):
            for 卡, (_键, 值, _注, _向) in zip(self._卡片, 项列表):
                卡.换值(值)
        else:
            # 没有骨架、或者条数对不上：整行重画。重画前先把上一版摘掉，
            # 否则每刷新一次就往页面上多叠一行。
            if self._行 is not None:
                try:
                    self._布局.removeWidget(self._行)
                    self._行.deleteLater()
                except Exception:
                    pass
                self._行 = None
            行 = 指标行(项列表, 每行=self._每行)
            self._布局.addWidget(行)
            self._行 = 行
        self._来源.setText("数据来源：%s" % (来源文本 or self._来源文字 or "—"))

    def _失败(self, 错误文本: str):
        文本 = "取数失败：%s" % 错误文本
        if self._提示 is not None:
            self._提示.setText(文本)
            self._提示.setVisible(True)
        else:
            self._来源.setText(文本)


def _好看(值) -> str:
    if isinstance(值, float):
        if 值 != 值:  # NaN
            return "—"
        if abs(值) >= 1e8:
            return "%.2f 亿" % (值 / 1e8)
        if abs(值) >= 1e4:
            return "%.2f 万" % (值 / 1e4)
        return "%.2f" % 值
    if isinstance(值, int):
        return "{:,}".format(值)
    return str(值)


def 加载折线(取数函数, 参数=(), 取值=None, 标题: str = "", 高度: int = 280,
             来源文字: str = "", 说明: str = "") -> QWidget:
    """
    建一块「折线图 + 来源」区域，数据在后台拉，到了自动画。

    取值(数据框) 要返回三元组 (类别列表, 系列列表, 参考线)：
        类别列表 —— X 轴标签，一般是日期或月份
        系列列表 —— [(名称, 值列表, 颜色或 None), ...]
        参考线   —— None，或 (数值, 文字)，例如 PMI 的 (50.0, "荣枯线 50")
    """
    块 = 可刷新折线(取数函数, 取值=取值, 标题=标题, 高度=高度,
                    来源文字=来源文字, 说明=说明)
    块.刷新(*参数)
    return 块


class 可刷新折线(QWidget):
    """带「刷新」能力的折线图：参数变了可以重新取一次数并重画。"""

    def __init__(self, 取数函数, 取值=None, 标题: str = "", 高度: int = 280,
                 来源文字: str = "", 说明: str = "", 父=None):
        super().__init__(父)
        from 应用.组件.折线图 import 折线图

        self._函数 = 取数函数
        self._取值 = 取值
        self._标题 = 标题
        self._来源文字 = 来源文字
        self._说明 = 说明
        self._参数 = ()

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(8)

        self.图 = 折线图(标题, 高度=高度)
        布局.addWidget(self.图)
        self.提示 = 来源标注(来源文字 or "正在加载…")
        布局.addWidget(self.提示)

    def 刷新(self, *参数):
        self._参数 = tuple(参数)
        self.提示.setText("正在取数…")
        后台运行(self._函数, 完成=self._到了, 失败=self._失败, 参数=self._参数)

    def 重取(self):
        """按上一次的参数再取一遍。全局刷新按钮走这个入口。"""
        self.刷新(*self._参数)

    def _到了(self, 结果):
        try:
            框, 错误, 来源 = _拆结果(结果)
        except Exception:
            self.提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or getattr(框, "empty", True):
            self.图.清空("暂无数据：%s" % (错误 or "接口返回为空"))
            self.提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        try:
            类别, 系列, 参考线 = self._取值(框) if self._取值 else (list(框.iloc[:, 0]), [], None)
        except Exception as e:
            self.图.清空("画不出来：%s" % str(e)[:60])
            self.提示.setText("画图失败：%s" % str(e)[:120])
            return
        self.图.换数据(系列, 类别, 参考线=参考线, 标题=self._标题)
        self.提示.setText("数据来源：%s ｜ %d 个数据点%s" % (
            来源 or self._来源文字 or "未知", len(类别),
            ("｜" + self._说明) if self._说明 else ""))

    def _失败(self, 错误文本: str):
        self.图.清空("取数失败")
        self.提示.setText("取数失败：%s" % 错误文本)

    def 置高(self, 高: int, 毫秒: int = 0):
        """把高度转给里面的折线图，图块放大时用。"""
        self.图.置高(高, 毫秒)


def 加载柱状(取数函数, 参数=(), 取值=None, 标题: str = "", 高度: int = 280,
             来源文字: str = "", 横向: bool = False, 小数位: int = 2,
             说明: str = "") -> QWidget:
    """
    建一块「柱状图 + 来源」区域，数据在后台拉，到了自动画。

    取值(数据框) 要返回四元组 (标签列表, 值列表, 逐柱颜色或 None, 值轴标题)。
    逐柱颜色传 None 时按正负自动红涨绿跌；传列表时一根柱一个颜色。
    """
    块 = 可刷新柱状(取数函数, 取值=取值, 标题=标题, 高度=高度, 来源文字=来源文字,
                    横向=横向, 小数位=小数位, 说明=说明)
    块.刷新(*参数)
    return 块


class 可刷新柱状(QWidget):
    """带「刷新」能力的柱状图：参数变了可以重新取一次数并重画。"""

    def __init__(self, 取数函数, 取值=None, 标题: str = "", 高度: int = 280,
                 来源文字: str = "", 横向: bool = False, 小数位: int = 2,
                 说明: str = "", 父=None):
        super().__init__(父)
        from 应用.组件.柱状图 import 柱状图

        self._函数 = 取数函数
        self._取值 = 取值
        self._标题 = 标题
        self._来源文字 = 来源文字
        self._横向 = 横向
        self._小数位 = 小数位
        self._说明 = 说明
        self._参数 = ()

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(0, 0, 0, 0)
        布局.setSpacing(8)

        self.图 = 柱状图(标题, 高度=高度, 横向=横向)
        布局.addWidget(self.图)
        self.提示 = 来源标注(来源文字 or "正在加载…")
        布局.addWidget(self.提示)

    def 刷新(self, *参数):
        self._参数 = tuple(参数)
        self.提示.setText("正在取数…")
        后台运行(self._函数, 完成=self._到了, 失败=self._失败, 参数=self._参数)

    def 重取(self):
        """按上一次的参数再取一遍。全局刷新按钮走这个入口。"""
        self.刷新(*self._参数)

    def _到了(self, 结果):
        try:
            框, 错误, 来源 = _拆结果(结果)
        except Exception:
            self.提示.setText("取数失败：返回格式异常")
            return
        if 框 is None or getattr(框, "empty", True):
            self.图.清空("暂无数据：%s" % (错误 or "接口返回为空"))
            self.提示.setText("没有取到数据：%s" % (错误 or "接口返回为空"))
            return
        try:
            标签, 值, 颜色, 轴名 = self._取值(框) if self._取值 else ([], [], None, "")
        except Exception as e:
            self.图.清空("画不出来：%s" % str(e)[:60])
            self.提示.setText("画图失败：%s" % str(e)[:120])
            return
        self.图.换数据(标签, 值, 标题=self._标题, 小数位=self._小数位,
                      逐柱颜色=颜色, 轴标题=轴名)
        self.提示.setText("数据来源：%s ｜ %d 项%s" % (
            来源 or self._来源文字 or "未知", len(标签),
            ("｜" + self._说明) if self._说明 else ""))

    def _失败(self, 错误文本: str):
        self.图.清空("取数失败")
        self.提示.setText("取数失败：%s" % 错误文本)

    def 置高(self, 高: int, 毫秒: int = 0):
        """把高度转给里面的柱状图，图块放大时用。"""
        self.图.置高(高, 毫秒)