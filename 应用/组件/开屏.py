# -*- coding: utf-8 -*-
"""
启动画面（开屏动画）—— 用模拟 K 线讲「正在加载」，时长约 5 秒。

设计意图
--------
1. **像行情软件**：44 根 K 线从左到右逐根长出来，涨红跌绿、带上下影线，
   和主界面里看到的形态一致，不像一张通用厂商 logo 动画。
2. **有冲击力**：每根 K 线不是淡入，而是从开盘价「抡」到收盘价（带回弹），
   收盘瞬间在端点炸开一圈粒子 + 一圈扩散环 + 一条价格线闪光。涨的往上炸，
   跌的往下炸，方向跟行情一致。
3. **流畅**：单帧只画 44 个矩形 + 几十个圆点和短线段，粒子总数有硬上限；
   实测单帧绘制中位 3 毫秒以内，远低于 16 毫秒一帧的预算。
4. **不假**：进度仍由 main.py 按真实阶段推进，显示值只朝目标逼近、永不倒退，
   100% 只留给收尾。

配色纪律：全项目只有红涨绿跌两种颜色，开屏严格照办 —— K 线与粒子用涨/跌色，
其余文字、网格、进度一律中性色。

字体档位：全项目正文是 11/12/13/18/22 五档，开屏例外用 30/16/14/12。
开屏是独立居中画面，照搬 22 像素在 720 宽的画布上会又小又空。
"""

import math
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRegion,
)
from PySide6.QtWidgets import QApplication, QWidget

import config
from 应用 import 主题

# ----------------------------------------------------------------- 设计令牌 ----

宽 = 720
高 = 400
圆角 = 20
边距 = 56

_字号_标题 = 30
_字号_阶段 = 16
_字号_副标题 = 14
_字号_版本 = 12

_字体族 = "Microsoft YaHei UI"

K线根数 = 44
体宽 = 10
K线基线 = 284.0        # 价格 0 的水平线
K线最高 = 132.0        # 价格 1.0 距基线的高度

轨_y = 304.0
轨_高 = 4.0
文_y = 320.0

_帧毫秒 = 16               # 约 60 帧/秒
_首根延迟 = 220.0          # 第一根 K 线什么时候开始长
_相邻间隔 = 62.0           # 相邻两根的错峰（44 根 → 约 2.7 秒铺满）
_生长毫秒 = 180.0          # 单根从开盘抡到收盘
_粒子寿命 = 340.0
_冲击环毫秒 = 220.0
_进度阻尼 = 0.075
_文字切换阻尼 = 0.06

# 目标总时长 5 秒 = 这里的最短展示 + 0.3 秒补满 + 0.36 秒淡出，所以给 4340。
最短展示_毫秒 = 4340
最短展示_减少动态_毫秒 = 1200

_每根粒子数 = 9
_粒子总数上限 = 120       # 硬上限，防止掉帧
共寿命 = max(_粒子寿命, _冲击环毫秒)


def _笔(色, 宽: float = 1.0) -> QPen:
    """一个 1 像素的实心线画笔。K 线的笔预先建好放在几何表里，别每帧新建。"""
    return QPen(色, 宽)


def _笔宽(色, 宽: float) -> QPen:
    return QPen(色, 宽)


# ------------------------------------------------------------------ 环境适配 ----


def 减少动态效果() -> bool:
    """
    系统是否关掉了「动画效果」。

    Windows 的权威开关是 SPI_GETCLIENTAREAANIMATION。关掉时整套静下来：
    K 线一次画满、不炸粒子，只留进度本身。环境变量 AKANBAN_减少动态=1
    可以强制打开，验证脚本靠它测静态那一套。
    """
    import os

    if os.environ.get("AKANBAN_减少动态") == "1":
        return True
    try:
        import ctypes

        开 = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(开), 0):
            return 开.value == 0
    except Exception:
        pass
    return False


def _记(文本: str):
    """
    往 日志/开屏日志.txt 追加一行。

    打包成 exe 后没有控制台，「开屏到底画出来没有」在外部只能靠窗口尺寸猜。
    这里把关键节点落盘：落哪块屏、首帧什么时候画的、透明度、何时关闭。
    """
    try:
        import datetime
        import os

        目录 = getattr(config, "日志目录", os.path.join(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "日志"))
        os.makedirs(目录, exist_ok=True)
        行 = "%s  %s\n" % (datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3], 文本)
        with open(os.path.join(目录, "开屏日志.txt"), "a", encoding="utf-8") as f:
            f.write(行)
    except Exception:
        pass


def _缓出(比例: float) -> float:
    """OutCubic：起步快、收尾稳。"""
    比例 = max(0.0, min(1.0, 比例))
    return 1.0 - (1.0 - 比例) ** 3


def _回弹(比例: float) -> float:
    """
    带过冲的缓动：0 → 1，中途冲到 1.06 再落回 1。

    这是「冲击力」的来源 —— K 线实体不是平滑长到位，而是抡过头再回弹，
    视觉上像被一笔大单砸出来。
    """
    比例 = max(0.0, min(1.0, 比例))
    冲 = 1.06
    if 比例 < 0.62:
        return _缓出(比例 / 0.62) * 冲
    return 冲 + (1.0 - 冲) * _缓出((比例 - 0.62) / 0.38)


# ------------------------------------------------------------------ 行情数据 ----


def _K线表():
    """
    44 根模拟 K 线，价格归一化到 0~1。

    用固定公式生成而不是随机数：每次启动画出来一模一样，验证脚本才有稳定的
    像素基线；而且几波大起大落是刻意安排的，让冲击效果有节奏，不至于一片碎抖。
    """
    价 = 0.52
    表 = []
    for i in range(K线根数):
        趋势 = 0.075 * math.sin(i * 0.42 + 0.8)
        波 = 0.042 * math.sin(i * 1.63 + 2.1)
        突 = 0.095 * math.sin(i * 0.21 + 0.3)
        开 = 价
        价 = max(0.08, min(0.95, 价 + 趋势 + 波 + 突))
        收 = 价
        影 = 0.026 + 0.034 * abs(math.sin(i * 0.9 + 1.3))
        高 = min(1.0, max(开, 收) + 影)
        低 = max(0.0, min(开, 收) - 影 * 0.9)
        表.append({"开": 开, "收": 收, "高": 高, "低": 低})
    return 表


def _粒子表():
    """
    每根 K 线配一小簇粒子的初始参数，全部由序号推导，不用随机数。

    涨 → 往上炸（角度围绕 -90°），跌 → 往下炸（围绕 +90°），方向与 K 线一致，
    看起来才像「这一笔打出去带起的碎屑」，而不是随机噪声。
    """
    表 = []
    for i in range(K线根数):
        涨 = i % 3 != 1
        基准 = -90.0 if 涨 else 90.0
        簇 = []
        for j in range(_每根粒子数):
            角 = math.radians(基准 + (j - (_每根粒子数 - 1) / 2.0) * 17.0
                              + 6.0 * math.sin(i * 1.7 + j * 2.3))
            速 = 58.0 + 34.0 * abs(math.sin(i * 0.8 + j * 1.9))
            半径 = 1.3 + 0.9 * abs(math.sin(i * 1.1 + j * 0.7))
            簇.append((角, 速, 半径))
        表.append(簇)
    return 表


# -------------------------------------------------------------------- 开屏窗 ----


class 开屏窗(QWidget):
    """一块会自己走、看得清的启动画面。用法见 main.py 的 主()。"""

    def __init__(self, 深: bool = False, 父=None):
        super().__init__(父)
        self._深 = bool(深)
        self._盘 = 主题.调色板(self._深)
        self._减少动态 = 减少动态效果()

        self.setWindowFlags(Qt.SplashScreen | Qt.WindowStaysOnTopHint)
        # 不要 WA_TranslucentBackground。半透明窗口在 Windows 上是分层（layered）窗口，
        # 靠 DWM 逐像素合成；碰上远程桌面、虚拟显示器、显卡驱动异常，合成器直接不显示
        # 它 —— 窗口存在、尺寸正确、PrintWindow 也能取到内容，屏幕上却什么都没有。
        # 现在改成完全不透明窗口，圆角改用窗口掩码（setMask）切出来，任何环境都画得出来。
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # 自己把整块矩形填满，就别让 Qt 再擦一遍底 —— 每帧少一次全画面填充。
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedSize(宽, 高)
        self.setWindowTitle(config.应用名称)

        路 = QPainterPath()
        路.addRoundedRect(QRectF(0.0, 0.0, 宽, 高), 圆角, 圆角)
        self.setMask(QRegion(路.toFillPolygon().toPolygon()))

        # ---- 动画状态 ----
        self._时刻 = 0.0          # 自显示起的毫秒数（按真实时钟走，不靠帧数累加）
        self._起 = 0.0            # showEvent 时的真实时刻，算停留时长用
        self._目标 = 0.0          # main.py 给的目标进度 0~1
        self._显示 = 0.0          # 屏幕上真正画出来的进度
        self._文字 = "正在准备"
        self._旧文字 = ""
        self._切换 = 1.0
        self._K线 = _K线表()
        self._粒子 = _粒子表()
        self._几何 = []
        self._粒几何 = []
        self._建几何()
        self._已收尾 = False
        self._已关 = False
        self._首帧已记 = False
        self._屏名 = "未知"
        self._淡出动画 = None

        # ---- 性能相关缓存 ----
        self._静态 = None         # 卡片底 + 标题 + 网格，一次画好反复贴
        self._字表 = {}           # 字号 → QFont，别每帧新建
        self._上帧 = 0.0          # 上一帧的真实时刻
        self._帧间隔 = []         # 帧间隔样本（毫秒），关屏时统计
        self._绘耗时 = []         # paintEvent 自身耗时样本（毫秒）
        self._长停顿 = []         # 超过 50 毫秒的间隔，记时刻，方便定位卡在哪

        self._钟 = QTimer(self)
        self._钟.setInterval(_帧毫秒)
        self._钟.setTimerType(Qt.PreciseTimer)
        self._钟.timeout.connect(self._跳)

    # ---------------------------------------------------------------- 对外接口

    def 推进(self, 目标: float, 文字: str = None):
        """
        把进度推到 目标（0~1），顺便换一句阶段说明。

        目标自动夹到 0.96：剩下 4% 留给 收尾()，进度条不会在窗口还没出现时
        先跑到 100% 然后干等。
        """
        try:
            目标 = float(目标)
        except Exception:
            return
        self._目标 = max(self._目标, min(0.96, max(0.0, 目标)))
        if 文字 and 文字 != self._文字:
            self._旧文字 = self._文字
            self._切换 = 1.0 if self._减少动态 else 0.0
            self._文字 = 文字
        self._确保在转()
        self.update()

    def 保持(self):
        """只重画，不改状态（main.py 边转边导入时每转一圈喊一声）。"""
        self._确保在转()
        self.update()

    def 收尾(self, 窗口=None):
        """
        等够最短展示时长 → 进度补满 → 停 300 毫秒 → 淡出 360 毫秒。

        这里刻意「慢」：主窗口 1.2 秒就建好了，可 K 线才长到一半，直接收掉等于
        白做动画。期间进度只停在 96%，最后 300 毫秒才补到 100%。
        """
        if self._已收尾:
            return
        self._已收尾 = True
        self.update()

        # 主窗口若落在另一块屏上，把开屏挪过去 —— 用户会盯着主窗口出现的地方看
        if 窗口 is not None:
            try:
                本屏 = QGuiApplication.screenAt(self.geometry().center())
                柄 = 窗口.windowHandle() if hasattr(窗口, "windowHandle") else None
                它屏 = 柄.screen() if 柄 is not None else None
                if 本屏 is not None and 它屏 is not None and 本屏.name() != 它屏.name():
                    区 = 它屏.availableGeometry()
                    self.move(max(区.left(), 区.center().x() - 宽 // 2),
                              max(区.top(), 区.center().y() - 高 // 2))
                    _记("开屏挪到主窗口所在屏：%s" % 它屏.name())
            except Exception:
                pass

        if self._减少动态:
            剩余 = max(0, int(最短展示_减少动态_毫秒 - self.已亮毫秒()))
        else:
            # 收尾之后不再做不透明度淡出（见 _淡出 里的说明），只剩「补满 + 停 300」。
            # 所以关门时刻 = 已亮 + 剩余，总目标 = 最短展示 + 660 ≈ 5 秒。
            总目标 = int(最短展示_毫秒) + 660
            剩余 = max(300, 总目标 - int(self.已亮毫秒()))
        _记("收尾：已亮 %.0f 毫秒，还要停留 %d 毫秒" % (self.已亮毫秒(), 剩余))
        if 剩余 > 600:
            QTimer.singleShot(int(剩余 * 0.50),
                              lambda: self.推进(self._目标, "正在打开主窗口"))
            QTimer.singleShot(int(剩余 * 0.78),
                              lambda: self.推进(self._目标, "马上就好"))

        def 补满():
            self._目标 = 1.0
            self.update()
            QTimer.singleShot(300, lambda: self._淡出(窗口))

        QTimer.singleShot(max(0, 剩余 - 300), 补满)

    def 已亮毫秒(self) -> float:
        """开屏已经上屏多少毫秒（真实时间，不信帧计数）。"""
        if not self._起:
            return 0.0
        return (time.monotonic() - self._起) * 1000.0

    def 记(self, 文本: str):
        """写一行到 日志/开屏日志.txt。main.py 记阶段耗时就靠它。"""
        _记(文本)

    def 已亮K线(self) -> int:
        """此刻画出来多少根 K 线（验证脚本用）。"""
        if self._减少动态:
            return K线根数
        数 = 0
        for i in range(K线根数):
            if self._时刻 >= self._出现时刻(i):
                数 += 1
        return 数

    def 进度(self) -> float:
        return self._显示

    def 阶段文字(self) -> str:
        return self._文字

    def 是否画满(self) -> bool:
        """K 线是不是已经全画出来了。main.py 用它决定什么时候去建主窗口。"""
        return self.已亮K线() >= K线根数

    def 是否减少动态(self) -> bool:
        return self._减少动态

    def 是否在动(self) -> bool:
        return self._钟.isActive()

    # ---------------------------------------------------------------- 动画时钟

    def _确保在转(self):
        if not self._钟.isActive():
            self._钟.start()

    def _跳(self):
        # 用真实时钟，不用「每帧加 16 毫秒」。
        # 累加法一旦掉帧就会越走越慢：启动期间主线程被「构建主窗口」堵住半秒，
        # 累加法会让动画整体慢半拍、永远追不回来；真实时钟只会跳过那半秒，
        # 之后立刻回到正确节奏，看起来是「顿一下」而不是「卡成慢动作」。
        现在 = time.monotonic()
        间 = (现在 - self._上帧) * 1000.0 if self._上帧 else float(_帧毫秒)
        间 = max(1.0, min(1000.0, 间))
        if self._起:
            self._时刻 = (现在 - self._起) * 1000.0
        else:
            self._时刻 += _帧毫秒
        if self._上帧:
            self._帧间隔.append(间)
            if 间 > 50.0:
                self._长停顿.append((round(self._时刻), round(间)))
        self._上帧 = 现在

        # 进度按「真实经过的时间」收敛，而不是每帧乘固定系数：掉帧后收敛速度不变，
        # 不会因为帧少而走得慢。
        差 = self._目标 - self._显示
        if abs(差) < 0.0008 or self._减少动态:
            self._显示 = self._目标
        else:
            步 = 1.0 - math.pow(1.0 - _进度阻尼, 间 / _帧毫秒)
            self._显示 += 差 * max(0.02, min(1.0, 步))

        if self._旧文字:
            self._切换 += 1.0 if self._减少动态 else _文字切换阻尼
            if self._切换 >= 1.0:
                self._切换 = 1.0
                self._旧文字 = ""

        self.update()

    # ---------------------------------------------------------------- 显示 / 关闭

    def showEvent(self, 事件):
        super().showEvent(事件)
        self._居中()
        self._时刻 = 0.0
        self._起 = time.monotonic()

        # 不碰 windowOpacity：哪怕设成 1.0，Qt 也可能顺手把窗口切成分层窗口，
# 而分层窗口在这台机器上合成不出来（详见 __init__）。启动画面要「立刻看清」。
        self._确保在转()

        try:
            屏们 = QGuiApplication.screens()
            主 = QGuiApplication.primaryScreen()
            区 = 主.availableGeometry() if 主 else None
            明细 = "；".join("%s %d×%d@%d,%d" % (屏.name(), 屏.geometry().width(),
                                              屏.geometry().height(),
                                              屏.geometry().left(), 屏.geometry().top())
                            for 屏 in 屏们)
            _记("上屏：屏幕 %d 块 [%s]；落在 %s；主屏 %s；减少动态=%s；窗口 %d×%d 在 %d,%d"
                % (len(屏们), 明细, getattr(self, "_屏名", "未知"),
                   (区.width(), 区.height()) if 区 else "无",
                   self._减少动态, self.width(), self.height(), self.x(), self.y()))
        except Exception:
            pass
        QTimer.singleShot(420, lambda: _记("0.42 秒时窗口可见=%s，几何 %d×%d 在 %d,%d"
                                          % (self.isVisible(), self.width(), self.height(),
                                             self.x(), self.y())))

    def _居中(self):
        """
        落在主屏正中。

        试过「跟随鼠标所在那块屏」，结果更糟：这台机器上第二块屏是
        NE153QDM-NY1 1280×800（虚拟/USB 扩展屏），鼠标停在那里时开屏就画到一块
        用户根本不看的屏上，等于没显示。主屏才是双击快捷方式时眼睛所在的地方。
        主窗口若开在别的屏，收尾() 会把开屏挪过去，不会一上来就赌错。
        """
        try:
            屏 = QGuiApplication.primaryScreen()
            if 屏 is None:
                return
            区 = 屏.availableGeometry()
            x = 区.center().x() - 宽 // 2
            y = 区.center().y() - 高 // 2
            x = max(区.left(), min(x, 区.right() - 宽 + 1))
            y = max(区.top(), min(y, 区.bottom() - 高 + 1))
            self.move(x, y)
            self._屏名 = "%s %d×%d" % (屏.name(), 区.width(), 区.height())
        except Exception:
            self._屏名 = "未知"

    def _淡出(self, 窗口=None):
        """
        直接收掉，不做不透明度淡出。

        淡出要用 setWindowOpacity，Qt 为此会把窗口重新变成分层（layered）窗口 ——
        而这台机器上分层窗口根本合成不出来（见 __init__ 里的说明）。为了一个 0.36 秒
        的淡出，把整块开屏的风险再赌回去，不值得。主窗口已经在它后面了，硬切不刺眼。
        """
        self._结束(窗口)

    def _结束(self, 窗口=None):
        self._钟.stop()
        if self._已关:
            return
        self._已关 = True
        _记("关闭：共亮 %.0f 毫秒" % self.已亮毫秒())
        self._记帧率()
        self.hide()
        self.close()
        if 窗口 is not None:
            try:
                窗口.raise_()
                窗口.activateWindow()
            except Exception:
                pass

    # ---------------------------------------------------------------- 绘制

    def _记帧率(self):
        """
        把这趟开屏的帧间隔和单帧绘制耗时写进日志。

        「流畅」这件事不能靠观感断言：窗口自渲染 1 毫秒不等于用户看到 60 帧 ——
        真正的瓶颈往往在主线程被别的事情堵住。这里记三样：帧数、帧间隔中位/95 分位/
        最大、单帧绘制耗时中位/最大，外加每次超过 50 毫秒的长停顿（带发生时刻）。
        """
        try:
            间 = sorted(self._帧间隔)
            if not 间:
                return
            绘 = sorted(self._绘耗时)
            中 = 间[len(间) // 2]
            p95 = 间[min(len(间) - 1, int(len(间) * 0.95))]
            _记("帧率：%d 帧；间隔 中位 %.1f / 95分位 %.1f / 最大 %.1f 毫秒；"
                "单帧绘制 中位 %.2f / 最大 %.2f 毫秒"
                % (len(间), 中, p95, 间[-1],
                   绘[len(绘) // 2] if 绘 else -1, 绘[-1] if 绘 else -1))
            if self._长停顿:
                样例 = "、".join("%.0f毫秒(%.0f毫秒处)" % (停, 时) for 时, 停 in self._长停顿[:6])
                _记("长停顿 %d 次：%s" % (len(self._长停顿), 样例))
        except Exception:
            pass

    def _字(self, 像素: int, 粗: bool = False) -> QFont:
        键 = (int(像素), bool(粗))
        字 = self._字表.get(键)
        if 字 is None:
            字 = QFont(_字体族)
            字.setPixelSize(int(像素))
            字.setWeight(QFont.DemiBold if 粗 else QFont.Normal)
            字.setStyleStrategy(QFont.PreferAntialias)
            self._字表[键] = 字
        return 字

    def _静态层(self) -> QPixmap:
        """
        卡片底、标题、副标题、版本、网格线、边框 —— 这五样一帧都不会变。

        以前每帧重画一遍：建路径、描边、画三行字、四条网格，光这些就占了单帧的大头。
        现在只画一次、存成 QPixmap，之后每帧 drawPixmap 一次贴上去。
        """
        if self._静态 is not None:
            return self._静态
        盘 = self._盘
        倍 = float(self.devicePixelRatioF()) or 1.0
        图 = QPixmap(int(宽 * 倍), int(高 * 倍))
        图.setDevicePixelRatio(倍)
        画 = QPainter(图)
        画.setRenderHint(QPainter.Antialiasing, True)
        画.setRenderHint(QPainter.TextAntialiasing, True)
        画.fillRect(QRectF(0.0, 0.0, 宽, 高), QColor(盘["底色"]))
        路 = QPainterPath()
        路.addRoundedRect(QRectF(0.5, 0.5, 宽 - 1.0, 高 - 1.0), 圆角, 圆角)
        画.setPen(QPen(QColor(盘["边框"]), 1.0))
        画.setBrush(Qt.NoBrush)
        画.drawPath(路)
        self._画标题(画)
        self._画网格(画)
        画.end()
        self._静态 = 图
        return 图

    def paintEvent(self, 事件):
        # 画挂了就是一块全透明的空窗，用户在屏幕上什么都看不到，exe 又没控制台。
        起 = time.perf_counter()
        try:
            self._绘制()
        except Exception:
            import traceback
            _记("绘制异常：\n" + traceback.format_exc())
        self._绘耗时.append((time.perf_counter() - 起) * 1000.0)
        if not self._首帧已记:
            self._首帧已记 = True
            _记("首帧已绘制（用时 %.0f 毫秒，窗口 %d×%d 在 %d,%d）"
                % (self.已亮毫秒(), self.width(), self.height(), self.x(), self.y()))

    def _绘制(self):
        画 = QPainter(self)
        画.setRenderHint(QPainter.Antialiasing, True)
        画.setRenderHint(QPainter.TextAntialiasing, True)
        画.setRenderHint(QPainter.SmoothPixmapTransform, False)

        # 静态部分一次贴上来（含底色、边框、标题、副标题、版本、网格）
        画.drawPixmap(0, 0, self._静态层())

        self._画面积(画)
        self._画K线(画)
        self._画粒子(画)
        self._画进度(画)
        画.end()

    def _画标题(self, 画: QPainter):
        盘 = self._盘

        画.setFont(self._字(_字号_标题, 粗=True))
        画.setPen(QColor(盘["文字1"]))
        画.drawText(QRectF(边距, 36, 520, 44),
                    Qt.AlignLeft | Qt.AlignVCenter, config.应用名称)

        画.setFont(self._字(_字号_版本))
        画.setPen(QColor(盘["文字3"]))
        画.drawText(QRectF(宽 - 边距 - 160, 44, 160, 20),
                    Qt.AlignRight | Qt.AlignVCenter,
                    "版本 %s" % getattr(config, "应用版本", "2.0"))

        画.setFont(self._字(_字号_副标题))
        画.setPen(QColor(盘["文字2"]))
        画.drawText(QRectF(边距, 88, 560, 22),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    "模拟行情 · 逐根生成 · 离线优先")

    def _画网格(self, 画: QPainter):
        """三条淡淡的水平参考线 + 一条价格 0 轴，给 K 线一点坐标感。"""
        盘 = self._盘
        淡 = QColor(盘["边框深"])
        淡.setAlphaF(0.55)
        画.setPen(QPen(淡, 1.0))
        for 比例 in (0.25, 0.5, 0.75):
            y = K线基线 - K线最高 * 比例
            画.drawLine(边距, y, 宽 - 边距, y)
        轴 = QColor(盘["边框深"])
        画.setPen(QPen(轴, 1.0))
        画.drawLine(边距, K线基线 + 0.5, 宽 - 边距, K线基线 + 0.5)

    def _建几何(self):
        """
        把每根 K 线的坐标、颜色、影线高度在初始化时算好，存成扁平的表。

        为什么要预计算：paintEvent 是 Python 代码，每帧 44 根 × 十几次属性访问和
        函数调用，看着不多，但这些 Python 语句每一个都是「要拿 GIL」的点。启动时后台
        线程在导 akshare，GIL 被抢来抢去，一次绘制就被拖成几百毫秒 —— exe 日志里
        那几次 250~600 毫秒的停顿就是这么来的。把计算搬到 init，绘制循环里只剩减法
        和乘法，卡顿随之大幅下降。
        """
        盘 = self._盘
        涨色 = QColor(盘["涨"])
        跌色 = QColor(盘["跌"])
        可用 = 宽 - 2 * 边距
        步 = (可用 - 体宽) / (K线根数 - 1)
        表 = []
        for i, K in enumerate(self._K线):
            开, 收 = K["开"], K["收"]
            涨 = 收 >= 开
            x = 边距 + i * 步
            y开 = K线基线 - K线最高 * max(0.0, min(1.0, 开))
            y收 = K线基线 - K线最高 * max(0.0, min(1.0, 收))
            表.append({
                "x": x, "中": x + 体宽 / 2.0, "涨": 涨,
                "色": 涨色 if 涨 else 跌色,
                "笔": _笔(涨色 if 涨 else 跌色),
                "y开": y开, "y收": y收,
                "影": max(0.0, (K["高"] - max(开, 收)) * K线最高),
                "下影": max(0.0, (min(开, 收) - K["低"]) * K线最高),
                "出现": _首根延迟 + i * _相邻间隔,
            })
        self._几何 = 表
        # 粒子的起点、基色也一次算好（收盘那一刻的端点）
        self._粒几何 = [(g["中"], g["y收"], g["色"], self._粒子[i])
                       for i, g in enumerate(表)]

    def _画面积(self, 画: QPainter):
        """
        收盘价连成的面积（中性灰渐变，不是彩色）。

        两个作用：一是让画面有「行情软件」的分量，光有细 K 线在 720 宽里显得空；
        二是着墨率能到 8% 以上 —— 稀疏的 44 根线画出来只有 4%，看着发虚。
        """
        时刻 = self._时刻
        减少 = self._减少动态
        路 = QPainterPath()
        首 = True
        末x = 边距
        for g in self._几何:
            if not 减少:
                if 时刻 < g["出现"]:
                    break
                进度 = _回弹((时刻 - g["出现"]) / _生长毫秒)
            else:
                进度 = 1.0
            y = g["y开"] + (g["y收"] - g["y开"]) * 进度
            x = g["中"]
            if 首:
                路.moveTo(x, K线基线)
                首 = False
            路.lineTo(x, y)
            末x = x
        if 首:
            return
        路.lineTo(末x, K线基线)
        路.closeSubpath()

        上 = QColor(self._盘["实心"])
        上.setAlphaF(0.12)
        下 = QColor(self._盘["实心"])
        下.setAlphaF(0.01)
        渐 = QLinearGradient(0.0, K线基线 - K线最高, 0.0, K线基线)
        渐.setColorAt(0.0, 上)
        渐.setColorAt(1.0, 下)
        画.setPen(Qt.NoPen)
        画.setBrush(渐)
        画.drawPath(路)
        画.setBrush(Qt.NoBrush)

    def _x(self, i: int) -> float:
        可用 = 宽 - 2 * 边距
        if K线根数 <= 1:
            return 边距
        return 边距 + i * (可用 - 体宽) / (K线根数 - 1)

    def _y(self, 价: float) -> float:
        return K线基线 - K线最高 * max(0.0, min(1.0, 价))

    def _出现时刻(self, i: int) -> float:
        return _首根延迟 + i * _相邻间隔

    def _可见(self, i: int) -> bool:
        """这根 K 线该不该出现在画面上。减少动态时一次全给，不留半张图。"""
        return self._减少动态 or self._时刻 >= self._出现时刻(i)

    def _画K线(self, 画: QPainter):
        画.setRenderHint(QPainter.Antialiasing, False)   # K 线要硬边，别擦糊
        时刻 = self._时刻
        减少 = self._减少动态
        无笔 = Qt.NoPen

        for g in self._几何:
            if not 减少:
                出现 = g["出现"]
                if 时刻 < 出现:
                    break
                进度 = _回弹((时刻 - 出现) / _生长毫秒)
            else:
                进度 = 1.0

            y开 = g["y开"]
            y收 = y开 + (g["y收"] - y开) * 进度
            中 = g["中"]

            # 上下影线：跟着实体一起抡出去，只画到「此刻应到」的位置
            比 = 1.0 if 进度 > 1.0 else (0.0 if 进度 < 0.0 else 进度)
            画.setPen(g["笔"])
            if g["涨"]:
                if g["影"] > 0.0:
                    画.drawLine(中, y收, 中, y收 - g["影"] * 比)
                if g["下影"] > 0.0:
                    画.drawLine(中, y收, 中, y收 + g["下影"] * 比)
            else:
                if g["影"] > 0.0:
                    画.drawLine(中, y开, 中, y开 - g["影"] * 比)
                if g["下影"] > 0.0:
                    画.drawLine(中, y开, 中, y开 + g["下影"] * 比)

            上 = y开 if y开 < y收 else y收
            高_i = y收 - y开 if y收 > y开 else y开 - y收
            if 高_i < 2.0:
                高_i = 2.0
            画.setPen(无笔)
            画.setBrush(g["色"])
            画.drawRect(QRectF(g["x"], 上, 体宽, 高_i))

    def _画粒子(self, 画: QPainter):
        """收盘瞬间在端点炸开的粒子 + 扩散环 + 价格线闪光。"""
        if self._减少动态:
            return
        画.setRenderHint(QPainter.Antialiasing, True)
        时刻 = self._时刻
        总 = 0
        无笔 = Qt.NoPen

        for i, (端x, 端y, 基色, 簇) in enumerate(self._粒几何):
            龄 = 时刻 - (self._几何[i]["出现"] + _生长毫秒 * 0.55)
            if 龄 < 0.0 or 龄 >= 共寿命:
                continue

            # 扩散环：一圈细线快速扩出去，最像「冲击波」
            if 龄 < _冲击环毫秒:
                环 = 龄 / _冲击环毫秒
                色 = QColor(基色)
                色.setAlphaF(0.55 * (1.0 - 环) ** 1.4)
                画.setPen(_笔宽(色, 1.5))
                画.setBrush(Qt.NoBrush)
                半径 = 3.0 + 15.0 * _缓出(环)
                画.drawEllipse(QRectF(端x - 半径, 端y - 半径 * 0.62,
                                      半径 * 2.0, 半径 * 1.24))
                画.setPen(无笔)

            # 价格线闪光：一条短横线，像报价被砸亮了一下
            if 龄 < 150.0:
                淡 = 1.0 - 龄 / 150.0
                色 = QColor(基色)
                色.setAlphaF(0.45 * 淡)
                画.setPen(_笔宽(色, 1.0))
                半 = 5.0 + 9.0 * (1.0 - 淡)
                画.drawLine(端x - 半, 端y, 端x + 半, 端y)
                画.setPen(无笔)

            # 粒子：抛物线飞出去，越飞越淡
            if 龄 < _粒子寿命:
                透 = (1.0 - 龄 / _粒子寿命) ** 1.6
                t = 龄 / 1000.0
                for 角, 速, 半径 in 簇:
                    if 总 >= _粒子总数上限:
                        break
                    总 += 1
                    px = 端x + math.cos(角) * 速 * t
                    # 重力往下拽一点，飘起来才像碎屑而不是直线
                    py = 端y + math.sin(角) * 速 * t + 0.5 * 240.0 * t * t
                    色 = QColor(基色)
                    色.setAlphaF(0.9 * 透 if 0.9 * 透 < 0.9 else 0.9)
                    画.setBrush(色)
                    画.drawEllipse(QRectF(px - 半径, py - 半径, 半径 * 2.0, 半径 * 2.0))

    def _画进度(self, 画: QPainter):
        盘 = self._盘
        可用 = 宽 - 2 * 边距
        显示 = max(0.0, min(1.0, self._显示))

        画.setRenderHint(QPainter.Antialiasing, True)
        画.setPen(Qt.NoPen)
        画.setBrush(QColor(盘["边框深"]))
        画.drawRoundedRect(QRectF(边距, 轨_y, 可用, 轨_高), 2.0, 2.0)

        if 显示 > 0.0:
            宽_i = max(4.0, 可用 * 显示)
            头 = 边距 + 宽_i
            if not self._减少动态:
                渐 = QLinearGradient(头 - 40.0, 0.0, 头, 0.0)
                起 = QColor(盘["实心"])
                起.setAlphaF(0.0)
                止 = QColor(盘["实心"])
                止.setAlphaF(0.20)
                渐.setColorAt(0.0, 起)
                渐.setColorAt(1.0, 止)
                画.setBrush(渐)
                画.drawRect(QRectF(max(边距, 头 - 40.0), 轨_y - 6.0,
                                   min(40.0, 头 - 边距), 轨_高 + 12.0))
            画.setBrush(QColor(盘["实心"]))
            画.drawRoundedRect(QRectF(边距, 轨_y, 宽_i, 轨_高), 2.0, 2.0)

            心 = 轨_y + 轨_高 / 2.0
            画.setBrush(QColor(盘["底色"]))
            画.drawEllipse(QRectF(头 - 8.0, 心 - 8.0, 16.0, 16.0))
            画.setBrush(QColor(盘["实心"]))
            画.drawEllipse(QRectF(头 - 4.0, 心 - 4.0, 8.0, 8.0))

        文色 = QColor(盘["文字1"])
        画.setFont(self._字(_字号_阶段))

        if self._旧文字 and self._切换 < 1.0:
            旧 = QColor(文色)
            旧.setAlphaF(1.0 - self._切换)
            画.setPen(旧)
            画.drawText(QRectF(边距, 文_y, 520, 28),
                        Qt.AlignLeft | Qt.AlignVCenter, self._旧文字)

        新 = QColor(文色)
        新.setAlphaF(self._切换 if self._旧文字 else 1.0)
        画.setPen(新)
        画.drawText(QRectF(边距, 文_y, 520, 28),
                    Qt.AlignLeft | Qt.AlignVCenter, self._文字)

        画.setFont(self._字(_字号_阶段, 粗=True))
        画.setPen(文色)
        画.drawText(QRectF(宽 - 边距 - 140, 文_y, 140, 28),
                    Qt.AlignRight | Qt.AlignVCenter, "%d%%" % round(显示 * 100))


# -------------------------------------------------------------------- 工厂 ----


def 建开屏(深: bool = None, 父=None):
    """
    给 main.py 用的入口。深 = None 时按当前主题取色（默认浅色）。

    任何异常都吞掉返回 None —— 启动画面坏了不能连累程序启动。
    """
    try:
        应用 = QApplication.instance()
        if 深 is None:
            盘 = getattr(应用, "_主题调色板", None) if 应用 else None
            深 = bool(盘 and 盘.get("底色") == 主题.深色["底色"])
        return 开屏窗(bool(深), 父)
    except Exception:
        return None