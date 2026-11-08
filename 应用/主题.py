# -*- coding: utf-8 -*-
"""
界面主题：浅色 / 深色 / 跟随系统 / 随时间变化。

Qt 的样式表（QSS）没有 CSS 变量，所以这里用「一套 QSS 模板 + 两个调色板字典」：
模板里用 @底色 这种占位符，渲染前按需替换。想改配色只改下面两个字典，
其余一行都不用动。

四种模式：
    浅色      —— 固定浅色
    深色      —— 固定深色
    跟随系统  —— 监听 Qt 的 colorSchemeChanged 信号，系统切主题时立即跟着变
    随时间变化 —— 北京时间 7:00–19:00 浅色，其余深色，每 60 秒查一次
"""

import datetime

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication

import config

# ================================================================ 调色板 ====

浅色 = {
    "底色": "#fbfbfc",
    "卡片": "#ffffff",
    "侧栏": "#f6f7f9",
    "边框": "#e3e6ea",
    "边框深": "#cfd4dc",
    "文字1": "#101418",
    "文字2": "#565e6b",
    "文字3": "#666e7b",
    "导航文字": "#565e6b",
    "实心": "#111827",
    "实心文字": "#ffffff",
    "悬停": "#eef0f3",
    "选中": "#e4e8ec",
    "涨": "#d32029",
    "跌": "#0a7a33",
    "平": "#565e6b",
    "表头": "#f6f7f9",
    "隔行": "#fafbfc",
    "输入底": "#ffffff",
}

深色 = {
    "底色": "#0f1115",
    "卡片": "#171a1f",
    "侧栏": "#14171c",
    "边框": "#2a2f39",
    "边框深": "#3a414c",
    "文字1": "#e8eaed",
    "文字2": "#a4acb8",
    "文字3": "#8f97a3",
    "导航文字": "#a4acb8",
    "实心": "#e8eaed",
    "实心文字": "#0f1115",
    "悬停": "#1c2027",
    "选中": "#252b34",
    "涨": "#ef6b72",
    "跌": "#45c98a",
    "平": "#a4acb8",
    "表头": "#1b1f25",
    "隔行": "#1a1e24",
    "输入底": "#171a1f",
}

# ================================================================ QSS 模板 ====

模板 = """QWidget {
    background: @底色;
    color: @文字1;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}

/* 字号只有五档：11 / 12 / 13 / 18 / 22
   字重只有两档：400 / 600
   间距只有四档：4 / 8 / 12 / 16 / 24（都是 4 的倍数）
   这三条是硬约束，改样式时别再引入新数值。 */

/* ---------- 主窗口 ---------- */
QMainWindow, QDialog {
    background: @底色;
}

/* ---------- 左侧导航 ---------- */
#导航栏 {
    background: @侧栏;
    border-right: 1px solid @边框;
}
#品牌名 {
    font-size: 18px;
    font-weight: 600;
    color: @文字1;
    background: transparent;
    letter-spacing: 0.2px;
}
#品牌说明 {
    font-size: 11px;
    color: @文字3;
    background: transparent;
    letter-spacing: 0.2px;
}
#侧栏小标题 {
    font-size: 11px;
    font-weight: 600;
    color: @文字3;
    background: transparent;
    letter-spacing: 0.4px;
}
#侧栏说明 {
    font-size: 11px;
    color: @文字3;
    background: transparent;
}
#侧栏分隔线 {
    background: @边框;
    max-height: 1px;
    min-height: 1px;
    border: none;
}

QPushButton#导航项 {
    text-align: left;
    padding: 8px 12px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    color: @导航文字;
    font-size: 13px;
    font-weight: 400;
    min-height: 18px;
}
QPushButton#导航项:hover {
    background: @悬停;
    color: @文字1;
}
QPushButton#导航项:checked {
    background: @实心;
    color: @实心文字;
    border-color: @实心;
    font-weight: 600;
}

QPushButton#主题按钮 {
    padding: 4px 8px;
    border: 1px solid @边框;
    border-radius: 8px;
    background: @卡片;
    color: @导航文字;
    font-size: 12px;
    min-height: 16px;
}
QPushButton#主题按钮:hover {
    border-color: @边框深;
    color: @文字1;
    background: @悬停;
}
QPushButton#主题按钮:checked {
    background: @实心;
    color: @实心文字;
    border-color: @实心;
    font-weight: 600;
}

/* ---------- 内容区 ---------- */
#顶条 {
    background: @底色;
}
#退出按钮 {
    padding: 0px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    color: @文字3;
    font-size: 18px;
    font-weight: 600;
}
#退出按钮:hover {
    background: @悬停;
    border-color: @边框;
    color: @涨;
}
#退出按钮:pressed {
    background: @选中;
    color: @涨;
}
#刷新按钮 {
    padding: 0px 12px;
    min-width: 52px;
    min-height: 28px;
    max-height: 28px;
    border: 1px solid @边框;
    border-radius: 8px;
    background: transparent;
    color: @文字2;
    font-size: 12px;
}
#刷新按钮:hover {
    background: @悬停;
    border-color: @边框深;
    color: @文字1;
}
#刷新按钮:pressed {
    background: @选中;
    color: @文字1;
}
#刷新按钮:disabled {
    color: @文字3;
    border-color: @边框;
}
#内容区 {
    background: @底色;
}
#页面标题 {
    font-size: 22px;
    font-weight: 600;
    color: @文字1;
    background: transparent;
    letter-spacing: 0px;
}
#页面说明 {
    font-size: 13px;
    color: @文字2;
    background: transparent;
}
#分区标题 {
    font-size: 13px;
    font-weight: 600;
    color: @文字1;
    background: transparent;
}
#分区说明 {
    font-size: 12px;
    color: @文字2;
    background: transparent;
}
#来源标注 {
    font-size: 11px;
    color: @文字3;
    background: transparent;
}
#空状态 {
    font-size: 12px;
    color: @文字2;
    background: transparent;
    padding: 16px;
}
/* 加载提示里那行字是自己套的 QLabel，样式不会从容器往下传，得单独指一遍 */
#来源标注 QLabel {
    font-size: 11px;
    color: @文字3;
    background: transparent;
}
#空状态 QLabel {
    font-size: 12px;
    color: @文字2;
    background: transparent;
}
/* 表格中央那圈下面的说明文字：不带内边距，高度就等于一行字，
   这样「圈 + 间距 + 字」整块算出来的中心才是真的中心 */
#加载说明 {
    font-size: 13px;
    color: @文字2;
    background: transparent;
    padding: 0px;
}

/* ---------- 指标卡 ---------- */
#指标卡 {
    background: @卡片;
    border: 1px solid @边框;
    border-radius: 12px;
}
#指标名 {
    font-size: 12px;
    color: @文字2;
    background: transparent;
}
#指标值 {
    font-size: 18px;
    font-weight: 600;
    color: @文字1;
    background: transparent;
}
#指标注释 {
    font-size: 11px;
    color: @文字3;
    background: transparent;
}

/* ---------- 卡片容器 ---------- */
#卡片 {
    background: @卡片;
    border: 1px solid @边框;
    border-radius: 12px;
}

/* ---------- 表格 ---------- */
QTableView {
    background: @卡片;
    alternate-background-color: @隔行;
    border: 1px solid @边框;
    border-radius: 10px;
    gridline-color: @卡片;
    selection-background-color: @选中;
    selection-color: @文字1;
    color: @文字1;
    font-size: 12px;
}
QTableView::item {
    padding: 4px 12px;
    border: none;
    border-bottom: 1px solid @隔行;
}
QHeaderView::section {
    background: @表头;
    color: @文字2;
    border: none;
    border-bottom: 1px solid @边框;
    padding: 8px 12px;
    font-size: 12px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: @表头;
    border: none;
}

/* ---------- 输入控件 ---------- */
QComboBox, QLineEdit, QDateEdit, QSpinBox, QDoubleSpinBox {
    background: @输入底;
    color: @文字1;
    border: 1px solid @边框深;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    min-height: 20px;
}
QComboBox:hover, QLineEdit:hover, QDateEdit:hover {
    border-color: @文字3;
}
QComboBox:focus, QLineEdit:focus, QDateEdit:focus {
    border-color: @文字2;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox QAbstractItemView {
    background: @卡片;
    color: @文字1;
    border: 1px solid @边框深;
    border-radius: 8px;
    selection-background-color: @选中;
    selection-color: @文字1;
    outline: none;
}

QPushButton {
    background: @卡片;
    color: @文字1;
    border: 1px solid @边框深;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 12px;
    min-height: 18px;
}
QPushButton:hover {
    border-color: @文字3;
    background: @悬停;
}
QPushButton:pressed {
    background: @选中;
}
QPushButton:disabled {
    color: @文字3;
    border-color: @边框;
}
QPushButton#主按钮 {
    background: @实心;
    color: @实心文字;
    border-color: @实心;
    font-weight: 600;
}
QPushButton#主按钮:hover {
    background: @实心;
    border-color: @实心;
}

QCheckBox, QRadioButton {
    color: @文字1;
    background: transparent;
    spacing: 8px;
    font-size: 12px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid @边框深;
    background: @卡片;
}
QCheckBox::indicator {
    border-radius: 4px;
}
QRadioButton::indicator {
    border-radius: 8px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: @实心;
    border-color: @实心;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: @边框深;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: @文字3;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: @边框深;
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover {
    background: @文字3;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ---------- 其它 ---------- */
QToolTip {
    background: @卡片;
    color: @文字1;
    border: 1px solid @边框深;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 11px;
}
QSplitter::handle {
    background: @边框;
}
QProgressBar {
    background: @卡片;
    border: 1px solid @边框;
    border-radius: 8px;
    text-align: center;
    color: @文字2;
    font-size: 11px;
    max-height: 6px;
}
QProgressBar::chunk {
    background: @实心;
    border-radius: 8px;
}
"""


def _渲染(调色板: dict) -> str:
    """把模板里的 @占位符换成实际颜色。"""
    文本 = 模板
    # 长的键先替换，避免 @文字1 把 @文字10 之类截断（当前没有，但保险）
    for 键 in sorted(调色板, key=len, reverse=True):
        文本 = 文本.replace("@" + 键, 调色板[键])
    return 文本


def 样式表(深: bool) -> str:
    return _渲染(深色 if 深 else 浅色)


def 调色板(深: bool) -> dict:
    return 深色 if 深 else 浅色


# ================================================================ 主题控制 ====

def 北京时间() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)


def 系统是否深色() -> bool:
    """
    读操作系统的深浅色偏好。

    Qt 6.5 起提供了 QStyleHints.colorScheme()，跨平台可用。
    老版本没有这个方法时退回浅色。
    """
    提示 = QGuiApplication.styleHints()
    if not hasattr(提示, "colorScheme"):
        return False
    return 提示.colorScheme().name.lower() == "dark"


def 按时间判定() -> bool:
    """白天（7:00–19:00）用浅色，其余深色。"""
    时 = 北京时间().hour
    return not (config.白天起始小时 <= 时 < config.白天结束小时)


class 主题控制(QObject):
    """
    持有当前主题状态，负责四种模式的解析、应用与自动切换。

    用法：
        控制 = 主题控制(应用)
        控制.设为("深色")          # 切换模式
        控制.是否深色              # 当前实际是深还是浅
        控制.变化.connect(回调)    # 主题真正变了（含跟随系统/随时间自动变）时通知
    """

    变化 = Signal(bool)  # True = 深色

    def __init__(self, 应用: QApplication, 父=None):
        super().__init__(父)
        self._应用 = 应用
        self._模式 = "浅色"
        self._深 = False

        应用.setFont(QFont("Microsoft YaHei UI", 9))

        # 跟随系统：Qt 自己会发信号
        提示 = QGuiApplication.styleHints()
        if hasattr(提示, "colorSchemeChanged"):
            try:
                提示.colorSchemeChanged.connect(self._系统主题变了)
            except Exception:
                pass

        # 随时间变化：每 60 秒查一次，跨过 7 点 / 19 点才真的重绘
        self._计时器 = QTimer(self)
        self._计时器.setInterval(60 * 1000)
        self._计时器.timeout.connect(self._巡检查时)
        self._计时器.start()

    # ---------------- 对外 ----------------

    @property
    def 模式(self) -> str:
        return self._模式

    @property
    def 是否深色(self) -> bool:
        return self._深

    def 设为(self, 模式: str) -> bool:
        """切换模式，返回实际是否深色。"""
        if 模式 not in config.主题模式选项:
            模式 = "浅色"
        self._模式 = 模式
        return self._应用当前()

    def 重新应用(self) -> bool:
        """外部改了系统/时间之后重算一次。"""
        return self._应用当前()

    # ---------------- 内部 ----------------

    def _解析(self) -> bool:
        if self._模式 == "深色":
            return True
        if self._模式 == "浅色":
            return False
        if self._模式 == "跟随系统":
            return 系统是否深色()
        return 按时间判定()  # 随时间变化

    def _应用当前(self) -> bool:
        深 = self._解析()
        变了 = (深 != self._深)
        self._深 = 深
        self._应用.setStyleSheet(样式表(深))
        棋盘 = getattr(self._应用, "_主题调色板", None)
        self._应用._主题调色板 = 调色板(深)
        if 变了:
            self.变化.emit(深)
        return 深

    def _系统主题变了(self, *_) -> None:
        if self._模式 == "跟随系统":
            self._应用当前()

    def _巡检查时(self) -> None:
        if self._模式 == "随时间变化":
            self._应用当前()

    def 状态说明(self) -> str:
        """侧边栏下方的一行说明，让用户知道现在实际生效的是深还是浅。"""
        if self._模式 == "跟随系统":
            return "由系统决定，系统切换时自动跟随"
        if self._模式 == "随时间变化":
            return "当前按北京时间判定为%s（%d–%d 点用浅色）" % (
                "深色" if self._深 else "浅色", config.白天起始小时, config.白天结束小时)
        return "固定%s" % self._模式


def 当前调色板() -> dict:
    """给需要自己上色的控件（比如 K 线图）取当前配色。"""
    应用 = QApplication.instance()
    return getattr(应用, "_主题调色板", 浅色) if 应用 else 浅色