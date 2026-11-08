# -*- coding: utf-8 -*-
"""
主窗口：左边一条导航，右边一个内容区。

两条设计原则：

1. **页面懒加载**。十个模块只有第一次点开时才创建，之后缓存住。
   否则启动时十个页面一起初始化，光建控件就要好几秒，还白拉一堆网络数据。

2. **切换不重建**。点回已经看过的模块，直接把它从 QStackedWidget 里翻出来，
   屏幕上瞬间就变，不会闪一下再重画。
"""

import importlib
import os
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel, QMainWindow, QPushButton, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

import config
from 应用 import 主题
from 应用.组件.基础 import 分区


class 主窗口(QMainWindow):
    # 关窗口前要不要弹确认。自检 / 诊断这些无人值守的模式会把它改成 False，
    # 否则模态框会把进程挂死在没人点的机器上。
    要确认退出 = True

    def __init__(self):
        super().__init__()
        self._页面缓存 = {}
        self._当前键 = None
        self._淡入动画 = None
        # 全局刷新的状态：忙标志、起跑时刻、轮询定时器、连续空闲次数
        self._刷新中 = False
        self._刷新起 = 0.0
        self._刷新计时 = None
        self._刷新空转 = 0
        self._刷新次数 = 0

        self.setWindowTitle("%s v%s" % (config.应用名称, config.应用版本))
        self.resize(1440, 920)
        self.setMinimumSize(1120, 720)
        self._设置图标()

        self.主题控制 = 主题.主题控制(_应用实例(), self)
        self.主题控制.变化.connect(self._主题变了)

        根 = QWidget(self)
        根布局 = QHBoxLayout(根)
        根布局.setContentsMargins(0, 0, 0, 0)
        根布局.setSpacing(0)
        根布局.addWidget(self._建导航栏())

        右侧 = QWidget(根)
        右布局 = QVBoxLayout(右侧)
        右布局.setContentsMargins(0, 0, 0, 0)
        右布局.setSpacing(0)

        # 顶部一条窄条，右上角放退出按钮。
        # 为什么单独占一条而不是直接浮在内容上：内容右上角是指标卡，
        # 浮上去会盖住数据；占一条以后滚动内容时它也稳稳定在原地。
        顶条 = QWidget(右侧)
        顶条.setObjectName("顶条")
        顶布局 = QHBoxLayout(顶条)
        顶布局.setContentsMargins(0, 12, 16, 0)
        顶布局.setSpacing(0)
        顶布局.addStretch(1)
        self._刷新按钮 = QPushButton("刷新", 顶条)
        self._刷新按钮.setObjectName("刷新按钮")
        self._刷新按钮.setFixedHeight(28)
        self._刷新按钮.setMinimumWidth(64)
        self._刷新按钮.setCursor(Qt.PointingHandCursor)
        self._刷新按钮.setToolTip("重新拉取所有打开过的页面的数据")
        self._刷新按钮.clicked.connect(self.刷新全部)
        顶布局.addWidget(self._刷新按钮)
        顶布局.addSpacing(8)
        self._退出按钮 = QPushButton("✕", 顶条)
        self._退出按钮.setObjectName("退出按钮")
        self._退出按钮.setFixedSize(28, 28)
        self._退出按钮.setCursor(Qt.PointingHandCursor)
        self._退出按钮.setToolTip("退出程序")
        self._退出按钮.clicked.connect(self.请求退出)
        顶布局.addWidget(self._退出按钮)
        右布局.addWidget(顶条)

        self.页面栈 = QStackedWidget(右侧)
        self.页面栈.setObjectName("内容区")
        右布局.addWidget(self.页面栈, 1)

        根布局.addWidget(右侧, 1)

        self.setCentralWidget(根)
        self.主题控制.设为("浅色")
        self.切换模块(config.模块配置[0]["键"])

    # ------------------------------------------------------------ 退出

    def 请求退出(self):
        """点右上角的叉，或按 Alt+F4 / 标题栏那个系统关闭，都走这里。"""
        if not self._确认退出():
            return
        self.要确认退出 = False   # 已经问过了，closeEvent 不要再问一遍
        self.close()

    def _确认退出(self) -> bool:
        """退出前问一句。用自己做的圆角小窗，不用系统方角对话框。"""
        if not getattr(self, "要确认退出", True):
            return True
        from 应用.组件.退出框 import 询问

        return 询问(self,
                    标题="退出 %s？" % config.应用名称,
                    正文="正在拉取的行情会中断，未完成的导出也一并取消。",
                    补充="已经缓存的数据下次打开还在，不用重新下载。")

    def closeEvent(self, 事件):
        if not self._确认退出():
            事件.ignore()
            return
        事件.accept()

    # ------------------------------------------------------------ 界面搭建

    def _设置图标(self):
        路径 = getattr(config, "页面图标", "")
        if 路径 and os.path.exists(路径):
            self.setWindowIcon(QIcon(路径))

    def _建导航栏(self) -> QFrame:
        栏 = QFrame(self)
        栏.setObjectName("导航栏")
        栏.setFixedWidth(232)
        栏.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        布局 = QVBoxLayout(栏)
        布局.setContentsMargins(16, 20, 16, 16)
        布局.setSpacing(4)

        # ---- 品牌 ----
        图标路径 = getattr(config, "页面图标", "")
        品牌行 = QHBoxLayout()
        品牌行.setContentsMargins(0, 0, 0, 0)
        品牌行.setSpacing(8)
        if 图标路径 and os.path.exists(图标路径):
            图标标签 = QLabel(栏)
            图 = QPixmap(图标路径).scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            图标标签.setPixmap(图)
            图标标签.setFixedSize(26, 26)
            品牌行.addWidget(图标标签)
        品牌文字 = QVBoxLayout()
        品牌文字.setContentsMargins(0, 0, 0, 0)
        品牌文字.setSpacing(0)
        名 = QLabel(config.应用名称, 栏)
        名.setObjectName("品牌名")
        品牌文字.addWidget(名)
        副 = QLabel("全品类 · 全数据量", 栏)
        副.setObjectName("品牌说明")
        品牌文字.addWidget(副)
        品牌行.addLayout(品牌文字, 1)
        布局.addLayout(品牌行)

        布局.addSpacing(24)

        # ---- 主题 ----
        小标题 = QLabel("界面主题", 栏)
        小标题.setObjectName("侧栏小标题")
        布局.addWidget(小标题)
        布局.addSpacing(8)

        # 四种主题排成 2×2。排成一行的话「随时间变化」五个字会被挤到按钮外面
        # （实测需要 65px，一行四等分只给到 54px，字直接裁掉）。
        主题格 = QGridLayout()
        主题格.setContentsMargins(0, 0, 0, 0)
        主题格.setHorizontalSpacing(8)
        主题格.setVerticalSpacing(8)
        self._主题按钮组 = QButtonGroup(self)
        self._主题按钮组.setExclusive(True)
        for 序, 模式 in enumerate(config.主题模式选项):
            按钮 = QPushButton(模式, 栏)
            按钮.setObjectName("主题按钮")
            按钮.setCheckable(True)
            按钮.setCursor(Qt.PointingHandCursor)
            按钮.setMinimumWidth(按钮.sizeHint().width())
            按钮.clicked.connect(lambda _=False, m=模式: self._换主题(m))
            self._主题按钮组.addButton(按钮)
            主题格.addWidget(按钮, 序 // 2, 序 % 2)
        布局.addLayout(主题格)

        self._主题说明 = QLabel("", 栏)
        self._主题说明.setObjectName("侧栏说明")
        self._主题说明.setWordWrap(True)
        布局.addWidget(self._主题说明)

        布局.addSpacing(16)
        布局.addWidget(_分隔线(栏))
        布局.addSpacing(8)

        # ---- 模块导航 ----
        模块标题 = QLabel("功能模块", 栏)
        模块标题.setObjectName("侧栏小标题")
        布局.addWidget(模块标题)
        布局.addSpacing(8)

        self._模块按钮组 = QButtonGroup(self)
        self._模块按钮组.setExclusive(True)
        for 模 in config.模块配置:
            按钮 = QPushButton(模["名称"], 栏)
            按钮.setObjectName("导航项")
            按钮.setCheckable(True)
            按钮.setCursor(Qt.PointingHandCursor)
            按钮.setToolTip(模["说明"])
            按钮.clicked.connect(lambda _=False, k=模["键"]: self.切换模块(k))
            self._模块按钮组.addButton(按钮)
            布局.addWidget(按钮)

        布局.addStretch(1)
        布局.addWidget(_分隔线(栏))
        布局.addSpacing(16)

        # ---- 底部状态 ----
        self._状态标签 = QLabel("", 栏)
        self._状态标签.setObjectName("侧栏说明")
        self._状态标签.setWordWrap(True)
        布局.addWidget(self._状态标签)

        免责 = QLabel("数据仅供参考，不构成投资建议。", 栏)
        免责.setObjectName("侧栏说明")
        免责.setWordWrap(True)
        布局.addWidget(免责)

        self._刷新状态()
        return 栏

    def _刷新状态(self):
        """
        侧栏底部的交易状态。

        分两步：先把时间立刻显示出来（纯算术，零耗时），
        交易日和开闭市状态丢后台 —— 首次调用要联网取交易日历，
        而且会顺带触发 akshare 的首次 import，放在主线程里就是肉眼可见的卡顿。
        """
        self._状态标签.setText("北京时间 %s" % 主题.北京时间().strftime("%m-%d %H:%M"))
        try:
            from 应用 import 后台任务 as 后台

            后台.后台运行(self._取状态文字, 完成=self._状态到了)
        except Exception:
            pass

    def _取状态文字(self) -> str:
        import data_fetcher
        开市, 状态文本 = data_fetcher.是否交易时段()
        日 = data_fetcher.最近交易日()
        return "%s · %s\n北京时间 %s" % (
            状态文本 or ("交易中" if 开市 else "休市"),
            日,
            主题.北京时间().strftime("%m-%d %H:%M"),
        )

    def _状态到了(self, 文字):
        try:
            self._状态标签.setText(str(文字))
        except Exception:
            pass

    # ------------------------------------------------------------ 全局刷新

    def 刷新全部(self) -> int:
        """
        重新拉一遍所有打开过的页面，返回发出的取数次数。

        三件事：清掉 data_fetcher 的内存缓存（不清的话 60 秒内的实时快照
        会原样还回来，点了跟没点一样）、让每个页面重放自己上一次的取数参数、
        顺手更新侧栏的交易状态。

        页面自己那套取数不用在这里逐个点名 —— 页面基.刷新 会扫「带重取 的块」，
        各页再用 super().刷新() 补上自己私有的那几次。
        """
        if self._刷新中:
            return 0

        import data_fetcher
        from 应用 import 后台任务 as 后台

        self._刷新中 = True
        self._刷新空转 = 0
        self._刷新起 = time.monotonic()
        self._刷新次数 = 0
        self._刷新按钮.setEnabled(False)
        self._刷新按钮.setText("刷新中…")

        清掉 = data_fetcher.清空缓存()
        次数 = 0
        for 键, 页面 in list(self._页面缓存.items()):
            try:
                次数 += int(页面.刷新() or 0)
            except Exception as 错:
                print("刷新「%s」失败：%r" % (键, 错))
        self._刷新次数 = 次数
        print("全局刷新：清掉缓存 %d 条，发出取数 %d 次" % (清掉, 次数))
        self._刷新状态()

        if self._刷新计时 is None:
            self._刷新计时 = QTimer(self)
            self._刷新计时.setInterval(200)
            self._刷新计时.timeout.connect(self._看刷新)
        self._刷新计时.start()
        self._看刷新()
        return 次数

    def _看刷新(self):
        """每 200 毫秒问一次后台：活干完没有。"""
        if not self._刷新中:
            if self._刷新计时 is not None:
                self._刷新计时.stop()
            return
        from 应用 import 后台任务 as 后台

        if 后台.空闲():
            self._刷新空转 += 1
            # 连着三次都空着才算真干完。板块页是「先取成分股，拿到了再取板块 K 线」，
            # 两步之间队列会短暂空一下，这时候收工就会漏掉后半段。
            if self._刷新空转 >= 3:
                self._收刷新("已刷新")
            return
        self._刷新空转 = 0
        if time.monotonic() - self._刷新起 > 120.0:
            self._收刷新("刷新超时")

    def _收刷新(self, 文字: str):
        if self._刷新计时 is not None:
            self._刷新计时.stop()
        self._刷新中 = False
        self._刷新按钮.setEnabled(True)
        self._刷新按钮.setText(文字)
        self._刷新按钮.setToolTip("上次刷新 %s，共发出 %d 次取数"
                              % (主题.北京时间().strftime("%H:%M"), self._刷新次数))
        QTimer.singleShot(1400, self._复位刷新按钮)

    def _复位刷新按钮(self):
        if not self._刷新中:
            self._刷新按钮.setText("刷新")

    # ------------------------------------------------------------ 导航

    def 切换模块(self, 键: str):
        if 键 == self._当前键:
            return

        模 = next((m for m in config.模块配置 if m["键"] == 键), None)
        if 模 is None:
            return

        if 键 not in self._页面缓存:
            页面 = self._创建页面(模)
            self._页面缓存[键] = 页面
            self.页面栈.addWidget(页面)

        self.页面栈.setCurrentWidget(self._页面缓存[键])
        self._当前键 = 键
        self._淡入(self._页面缓存[键])

        for 按钮 in self._模块按钮组.buttons():
            if 按钮.text() == 模["名称"]:
                按钮.setChecked(True)
                break

        self._刷新状态()

    def _淡入(self, 控件: QWidget, 毫秒: int = 130):
        """
        切页面时来一下极短的淡入。

        为什么只有 130 毫秒：再长就变成「动画」，点导航会觉得慢；
        130 毫秒只是盖掉切换那一帧的突变，手感上是「立刻出现」。

        动画结束立刻把透明度特效摘掉 —— 留着它会让整棵子树走软件绘制路径，
        大表格滚动明显掉帧。
        """
        try:
            特效 = QGraphicsOpacityEffect(控件)
            控件.setGraphicsEffect(特效)
            动画 = QPropertyAnimation(特效, b"opacity", self)
            动画.setDuration(毫秒)
            动画.setStartValue(0.35)
            动画.setEndValue(1.0)
            动画.setEasingCurve(QEasingCurve.OutCubic)

            def _收尾():
                try:
                    控件.setGraphicsEffect(None)
                except Exception:
                    pass

            动画.finished.connect(_收尾)
            self._淡入动画 = 动画
            动画.start(QPropertyAnimation.DeleteWhenStopped)
        except Exception:
            pass

    def _创建页面(self, 模: dict) -> QWidget:
        入口 = str(模.get("文件", 模["键"])).rsplit(".", 1)[0]
        try:
            模块 = importlib.import_module("应用.页面.%s" % 入口)
            return 模块.页面()
        except Exception as 错:
            import traceback
            print("页面创建失败：%s" % 模["键"], 错)
            print(traceback.format_exc())
            占位 = QWidget()
            布局 = QVBoxLayout(占位)
            布局.setContentsMargins(28, 24, 28, 24)
            布局.addWidget(分区(模["名称"], 模["说明"]))
            标签 = QLabel("这个页面加载失败：\n%s: %s" % (type(错).__name__, 错))
            标签.setObjectName("空状态")
            标签.setWordWrap(True)
            布局.addWidget(标签)
            布局.addStretch(1)
            return 占位

    # ------------------------------------------------------------ 主题

    def _换主题(self, 模式: str):
        self.主题控制.设为(模式)
        self._主题说明.setText(self.主题控制.状态说明())
        self._同步主题按钮()

    def _同步主题按钮(self):
        for 按钮 in self._主题按钮组.buttons():
            按钮.setChecked(按钮.text() == self.主题控制.模式)
        self._主题说明.setText(self.主题控制.状态说明())

    def _主题变了(self, 深: bool):
        """主题真正切换后，通知那些需要自己上色的页面重画（比如 K 线）。"""
        self._同步主题按钮()
        for 页面 in self._页面缓存.values():
            处理 = getattr(页面, "应用主题变化", None)
            if callable(处理):
                try:
                    处理()
                except Exception as 错:
                    print("页面主题刷新失败：", 错)


def _分隔线(父) -> QFrame:
    线 = QFrame(父)
    线.setObjectName("侧栏分隔线")
    线.setFixedHeight(1)
    线.setFrameShape(QFrame.HLine)
    return 线


def _应用实例():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()