# -*- coding: utf-8 -*-
"""
A股全景看板 · 桌面版入口。

直接双击 运行.py 或打包后的 exe 即可，不启动任何浏览器、不起本地服务，
所有界面都是 Qt 原生窗口。

命令行参数：
    --主题=深色/浅色/跟随系统/随时间变化   启动时用哪个主题
    --模块=stock                       启动时直接打开哪个模块
    --自检=路径                         跑一遍十个模块并写报告（无人值守）
    --诊断=路径                         只测几个接口通不通并写报告
"""

import os
import sys
import time
import traceback

# 必须放在最前面：PyInstaller 的 windowed（无控制台）模式下 sys.stdout 和
# sys.stderr 是 None。akshare 内部进度条会往 stdout 写，一旦是 None 就抛
# AttributeError: 'NoneType' object has no attribute 'write'，
# 症状是「源码跑得好好的，打成 exe 后新浪系接口全部取不到数」。
if sys.stdout is None or sys.stderr is None:
    _空流 = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = _空流
    if sys.stderr is None:
        sys.stderr = _空流

# 让标准输出在中文 Windows 控制台里不乱码（打包成 exe 后这行也不会有副作用）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

根目录 = os.path.dirname(os.path.abspath(__file__))
if 根目录 not in sys.path:
    sys.path.insert(0, 根目录)

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt, QThread  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import config  # noqa: E402


def _解析参数() -> dict:
    参数 = {"主题": None, "模块": None, "自检": None, "诊断": None}
    for 项 in sys.argv[1:]:
        if 项.startswith("--主题="):
            参数["主题"] = 项.split("=", 1)[1].strip()
        elif 项.startswith("--模块="):
            参数["模块"] = 项.split("=", 1)[1].strip()
        elif 项.startswith("--自检="):
            参数["自检"] = 项.split("=", 1)[1].strip()
        elif 项.startswith("--诊断="):
            参数["诊断"] = 项.split("=", 1)[1].strip()
    return 参数


def _写日志(文本: str):
    """打包成 exe 后没有控制台，print 会丢，必须落盘。"""
    try:
        os.makedirs(config.日志目录, exist_ok=True)
        路径 = os.path.join(config.日志目录, "异常.txt")
        with open(路径, "a", encoding="utf-8") as f:
            f.write(时间戳() + "\n" + 文本 + "\n\n")
    except Exception:
        pass


def 时间戳() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _装上异常兜底(窗口引用):
    """没接住的异常不能静默退出，得让用户看到是什么错了。"""
    原钩子 = sys.excepthook

    def 钩子(类型, 值, 栈):
        文本 = "".join(traceback.format_exception(类型, 值, 栈))
        print("程序出错：\n" + 文本, file=sys.stderr)
        _写日志(文本)
        try:
            QMessageBox.critical(
                窗口引用[0], "程序出错",
                "出现了一个未处理的错误：\n\n%s: %s\n\n"
                "详细信息已写入 日志\\异常.txt。\n\n%s"
                % (类型.__name__, 值, 文本[-1500:]))
        except Exception:
            pass
        原钩子(类型, 值, 栈)

    sys.excepthook = 钩子


def _跑自检(输出路径: str) -> int:
    """把十个模块挨个打开一遍，记录每页取到多少行数据，写文件后退出。

    打包成 exe 后没有控制台，验证「exe 里能不能真取到数」只能靠这个。
    用法：A股全景看板.exe --自检=C:\\某个路径\\自检.txt
    """
    import time

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QLabel, QTableView

    from 应用 import 后台任务 as 后台

    from 应用.主窗口 import 主窗口

    窗口 = 主窗口()
    # 自检是无人值守跑的，退出确认框没人点，会把进程挂死
    窗口.要确认退出 = False
    窗口.show()

    def 泵(次数: int = 1):
        for _ in range(次数):
            QCoreApplication.processEvents()
            time.sleep(0.05)

    def 统计() -> tuple:
        页 = 窗口.页面栈.currentWidget()
        if 页 is None:
            return 0, 0, 0
        视图们 = 页.findChildren(QTableView)
        行数 = 0
        for 视图 in 视图们:
            代理 = 视图.model()
            if 代理 is not None:
                行数 += 代理.rowCount()
        # 有些子页（情绪概览、个股 K 线）是卡片和图表，没有表格，
        # 光看表格行数会误判成"没数据"，所以把标签数也报出来。
        标签数 = len(页.findChildren(QLabel))
        return len(视图们), 行数, 标签数

    记录 = []

    def 落盘():
        """每跑完一个模块就写一次，卡住时也能看出卡在哪。"""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(输出路径)), exist_ok=True)
            with open(输出路径, "w", encoding="utf-8") as f:
                f.write("A股全景看板 · 运行自检\n")
                f.write("时间：%s\n" % 时间戳())
                f.write("程序根目录：%s\n" % config.项目根目录)
                f.write("数据目录：%s\n" % config.数据目录)
                f.write("离线库文件：%d 个\n" % (
                    len(os.listdir(config.数据目录)) if os.path.isdir(config.数据目录) else 0))
                f.write("界面翻译：%s\n" % ("已装中文包" if _翻译 is not None else "未装，按钮会是英文"))
                f.write("退出按钮：%s\n" % (
                    "已就位，%d×%d" % (窗口._退出按钮.width(), 窗口._退出按钮.height())
                    if getattr(窗口, "_退出按钮", None) is not None else "缺失"))
                f.write("刷新按钮：%s\n" % (
                    "已就位，%d×%d" % (窗口._刷新按钮.width(), 窗口._刷新按钮.height())
                    if getattr(窗口, "_刷新按钮", None) is not None else "缺失"))
                f.write("-" * 56 + "\n")
                f.write("\n".join(记录) + "\n")
        except Exception as e:
            print("写自检文件失败：%s" % e, file=sys.stderr)

    模块们 = [模["键"] for 模 in config.模块配置]
    for 键 in 模块们:
        开始 = time.time()
        try:
            窗口.切换模块(键)
        except Exception as e:
            记录.append("%-12s 切换失败：%s" % (键, e))
            落盘()
            continue

        # 动态等：表格行数连续 6 次不变（约 0.6 秒）且线程池空闲，就认为取完了；最多等 25 秒
        上次 = (-1, -1, -1)
        稳定 = 0
        结束 = 开始 + 25
        while time.time() < 结束:
            泵(1)
            现在 = 统计()
            if 现在 == 上次 and 后台.空闲():
                稳定 += 1
                if 稳定 >= 6:
                    break
            else:
                稳定 = 0
                上次 = 现在
        后台.等待全部(15000)
        泵(10)

        表格数, 行数, 标签数 = 统计()
        行 = ("%-12s %5.1f 秒  表格 %d 个／%d 行  标签 %d 个"
              % (键, time.time() - 开始, 表格数, 行数, 标签数))
        # 页面建不起来时，真正的错误通常写在某个标签里，一并带出来便于排查
        try:
            页 = 窗口.页面栈.currentWidget()
            if 页 is not None and 表格数 == 0:
                文本们 = [x.text() for x in 页.findChildren(QLabel)
                          if x.text().strip()][:4]
                if 文本们:
                    行 += "  文本：" + " ｜ ".join(
                        t.replace("\n", " ")[:70] for t in 文本们)
        except Exception:
            pass
        记录.append(行)
        落盘()

    文本 = "\n".join(记录)
    落盘()
    print(文本)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    # 自检是无人值守的诊断模式，不能因为 Qt 还有后台线程就赖着不退出
    os._exit(0)


def _跑诊断(输出路径: str) -> int:
    """只测几个代表性接口通不通，把原始错误文本写出来。

    专门用于「源码能跑、exe 不能跑」这类问题定位：
    如果这里 exe 和源码报同一个错，那是网络/接口问题；
    报不同的错，才是打包问题。
    """
    import time

    import data_fetcher as F

    def 试(名称, 函数, 参数=(), 关键字=None):
        开始 = time.time()
        try:
            结果 = 函数(*参数, **(关键字 or {}))
        except Exception as e:
            return "%-12s 抛异常 %-28s %s" % (
                名称, type(e).__name__, str(e)[:120])
        用时 = time.time() - 开始
        如果元组 = isinstance(结果, tuple)
        if 如果元组:
            框 = 结果[0]
            错 = str(结果[1]) if len(结果) > 1 else ""
            源 = str(结果[2]) if len(结果) > 2 else ""
            行数 = 0 if 框 is None else len(框)
            return "%-12s %5.1f 秒  行数 %-6s 来源 %-10s 错误 %s" % (
                名称, 用时, 行数, 源 or "-", (错 or "无")[:110])
        行数 = 0 if 结果 is None else len(结果)
        return "%-12s %5.1f 秒  行数 %s" % (名称, 用时, 行数)

    清单 = [
        ("重点关注指数", F.重点关注指数),
        ("全市场快照", F.全市场快照),
        ("交易日历", F.交易日历),
        ("个股日线", F.个股日线, ("600111", "20260901", "20261030", "qfq")),
        ("个股分钟", F.个股分钟, ("600111", "5")),
        ("行业估值表", None),
        ("PMI", None),
    ]

    import fetch_valuation as V
    import fetch_macro as M

    行 = []
    for 项 in 清单:
        名称 = 项[0]
        函数 = 项[1]
        if 名称 == "行业估值表":
            函数 = V.行业估值表
        elif 名称 == "PMI":
            函数 = M.PMI
        行.append(试(名称, 函数, 项[2] if len(项) > 2 else ()))

    头 = [
        "A股全景看板 · 网络诊断",
        "时间：%s" % 时间戳(),
        "Python：%s" % sys.version.split()[0],
        "是否打包运行：%s" % getattr(sys, "frozen", False),
        "项目根目录：%s" % config.项目根目录,
        "数据目录：%s" % config.数据目录,
        "akshare 版本：%s" % getattr(F.ak, "__version__", "未导入") if F.有AK else "akshare 未导入",
        "-" * 56,
    ]
    全部 = "\n".join(头 + 行)
    try:
        with open(输出路径, "w", encoding="utf-8") as f:
            f.write(全部 + "\n")
    except Exception as e:
        print("写诊断文件失败：%s" % e, file=sys.stderr)
    print(全部)
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)


def _启动是否深色(模式) -> bool:
    """按 --主题 参数（没传就按配置里的默认值）算出开屏该用哪套配色。"""
    try:
        from 应用 import 主题 as 主题模块

        模式 = 模式 or getattr(config, "主题模式默认", "浅色")
        if 模式 == "深色":
            return True
        if 模式 == "浅色":
            return False
        if 模式 == "跟随系统":
            return 主题模块.系统是否深色()
        return 主题模块.按时间判定()
    except Exception:
        return False


def _开启动画面(主题参数=None):
    """
    先把画面亮出来，再去加载重度依赖。

    真正花钱的是下面 主() 里那句 import：akshare 首次导入约 1.8 秒（它要
    初始化 py_mini_racer 才能跑新浪的 JS 加密）。旧版是一张静态图，用户
    盯着不动的画面两秒多会以为程序卡死。现在这块画面自己有进度、有阶段
    说明、有会走的扫描光，见 应用\\组件\\开屏.py。

    返回 None 表示开屏没建起来 —— 任何异常都不能连累程序启动。
    """
    try:
        from PySide6.QtWidgets import QApplication

        from 应用.组件 import 开屏

        窗 = 开屏.建开屏(_启动是否深色(主题参数))
        if 窗 is not None:
            窗.show()
            应用 = QApplication.instance()
            if 应用 is not None:
                应用.processEvents()   # 立刻上屏：后面那 0.9 秒的导入不会等它
        return 窗
    except Exception:
        # 静默失败过一次：开屏建起来了却忘了 show，界面上什么都没有，
        # 打包后的 exe 又没有控制台，根本查不出来。以后一律落盘。
        try:
            import os as _os

            import traceback as _traceback

            _os.makedirs(config.日志目录, exist_ok=True)
            with open(_os.path.join(config.日志目录, "启动画面.txt"), "a",
                      encoding="utf-8") as f:
                f.write(时间戳() + "\n" + _traceback.format_exc() + "\n\n")
        except Exception:
            pass
        return None


class _导入线程(QThread):
    """在工作线程里导入一个重模块；错误带回来给主线程抛。"""

    def __init__(self, 模块名: str):
        super().__init__()
        self._模块名 = 模块名
        self.错误 = None

    def run(self):
        try:
            import importlib

            importlib.import_module(self._模块名)
        except BaseException as 错:  # noqa: BLE001 - 原样带回主线程
            self.错误 = 错


def _边转边导入(模块名: str, 启动画面, 应用) -> None:
    """
    导入一个重模块，期间让开屏继续动。

    为什么敢放到线程里：实测 `import akshare` 只加载 Python 模块，全程一个
    py_mini_racer.MiniRacer 实例都不会建（V8 要到真正调新浪接口时才初始化），
    所以线程亲和性风险不发生在这一步 —— 这是挂了钩子数过的，不是猜的。

    导入失败会原样抛回主线程，行为和同步写法一致；没有开屏时退回同步导入。
    """
    import time

    线程 = _导入线程(模块名)
    线程.start()
    if 启动画面 is None:
        线程.wait()
    else:
        while 线程.isRunning():
            启动画面.保持()
            应用.processEvents()
            time.sleep(0.008)
        线程.wait()
    if 线程.错误 is not None:
        raise 线程.错误


def _收尾后台():
    """退出前给后台线程两秒，让它把手上的请求收干净，少打一堆退出报错。"""
    try:
        from 应用 import 后台任务 as 后台
        后台.等待全部(2500)
    except Exception:
        pass
    # 然后直接硬退。要是还有线程卡在网络请求里，正常退出会去析构 py_mini_racer，
    # 那个库在多线程下析构会 FATAL 崩掉，Windows 会弹一个「程序已停止工作」——
    # 用户明明是自己点的退出，却看见崩溃提示，没法解释。os._exit 跳过所有清理。
    os._exit(0)


_翻译 = None


def _翻译目录候选() -> list:
    """翻译包可能在好几个地方，挨个试。打包后路径和源码不一样。"""
    候选 = []
    try:
        from PySide6.QtCore import QLibraryInfo
        候选.append(QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    except Exception:
        pass
    try:
        import PySide6
        候选.append(os.path.join(os.path.dirname(PySide6.__file__), "translations"))
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        for 根 in (getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)):
            if 根:
                候选.append(os.path.join(根, "PySide6", "translations"))
                候选.append(os.path.join(根, "translations"))
    好的 = []
    for 目 in 候选:
        if 目 and os.path.isdir(目) and 目 not in 好的:
            好的.append(目)
    return 好的


def _装中文翻译(应用) -> None:
    """
    装上 Qt 自带的中文翻译包。

    不装的话，Qt 标准对话框里的按钮是英文的 OK / Cancel / Yes / No ——
    对一个全中文的软件来说很扎眼。qtbase_zh_CN.qm 是 PySide6 自带的，
    装上以后「确定」「取消」「是」「否」「打开」「保存」全变中文。

    QTranslator 必须留一个全局引用，被回收掉翻译就失效了。
    """
    global _翻译
    from PySide6.QtCore import QTranslator

    for 目录 in _翻译目录候选():
        译 = QTranslator()
        if 译.load("qtbase_zh_CN", 目录):
            应用.installTranslator(译)
            _翻译 = 译          # 保住引用，别被回收
            return


def 主():
    # 把 GIL 的切换粒度从默认 5 毫秒压到 0.5 毫秒。
    # `import akshare` 跑在后台线程里，但导入机制是连续持锁的：默认粒度下主线程
    # （开屏动画）会被成片饿死 —— 日志实测单次 paintEvent 被卡 601 毫秒，调到 1 毫秒
    # 后降到 254 毫秒。开屏绘制里每个 Python 语句都要摸一次 GIL，粒度越小，单次绘制
    # 被切碎后的总等待越短；0.5 毫秒是「停顿」和「后台导入速度」之间的平衡点
    # （实测导入耗时 1544~1685 毫秒，各档差别在误差内）。
    try:
        sys.setswitchinterval(0.0005)
    except Exception:
        pass

    应用 = QApplication(sys.argv)
    应用.setApplicationName(config.应用名称)
    应用.setApplicationDisplayName(config.应用名称)
    应用.setApplicationVersion(config.应用版本)
    应用.setFont(QFont("Microsoft YaHei UI", 9))
    _装中文翻译(应用)

    参数 = _解析参数()

    # 自检模式：无人值守，跑完十个模块写报告就退出。
    # 这里刻意不装那个弹 QMessageBox 的兜底 —— 模态框会把无人值守的进程挂死。
    if 参数["诊断"]:
        try:
            return _跑诊断(参数["诊断"])
        except Exception:
            _写日志(traceback.format_exc())
            return 1

    if 参数["自检"]:
        try:
            return _跑自检(参数["自检"])
        except Exception:
            文本 = traceback.format_exc()
            _写日志(文本)
            try:
                with open(参数["自检"], "a", encoding="utf-8") as f:
                    f.write("\n自检出错：\n" + 文本 + "\n")
            except Exception:
                pass
            return 1

    窗口引用 = [None]
    _装上异常兜底(窗口引用)

    启动画面 = _开启动画面(参数["主题"])

    def _推进(比例, 文字):
        """开屏的进度由真实阶段驱动；每推一次就地画一帧，避免画面停在上一格。"""
        if 启动画面 is None:
            return
        启动画面.推进(比例, 文字)
        应用.processEvents()

    _推进(0.18, "正在加载行情组件")
    # 先把数据层导进来：akshare 的首次导入在这里发生，是整个启动最重的一段
    # （实测 1.6~2.0 秒）。放到工作线程里导，主线程只负责泵事件循环，开屏照常动。
    _t = time.monotonic()
    _边转边导入("data_fetcher", 启动画面, 应用)
    if 启动画面 is not None:
        启动画面.记("导入行情组件 用时 %.0f 毫秒" % ((time.monotonic() - _t) * 1000.0))

    _推进(0.55, "正在构建界面")
    # 建主窗口是一次 0.3~0.4 秒的硬阻塞（首屏要建表格和图表，实测 342 毫秒），
    # 这段时间动画是停的。它落在哪一段，决定用户觉得「卡」还是「在加载」：
    # 卡在 K 线还在长的时候最刺眼（画面正热闹，突然定住）；等 44 根长完再建，
    # 屏幕上已经是完整的图、只有进度条在爬，同一段停顿看起来就是「正在构建界面」。
    # 最多等 3.2 秒，别把启动拖长。
    if 启动画面 is not None and not 启动画面.是否画满():
        截止 = time.monotonic() + 3.2
        while not 启动画面.是否画满() and time.monotonic() < 截止:
            应用.processEvents()
            time.sleep(0.004)

    from 应用.主窗口 import 主窗口
    _t = time.monotonic()
    窗口 = 主窗口()
    窗口引用[0] = 窗口
    if 启动画面 is not None:
        启动画面.记("构建主窗口 用时 %.0f 毫秒" % ((time.monotonic() - _t) * 1000.0))

    if 参数["主题"]:
        窗口._换主题(参数["主题"])
    if 参数["模块"]:
        窗口.切换模块(参数["模块"])

    _推进(0.86, "正在恢复界面状态")
    _t = time.monotonic()
    窗口.show()
    if 启动画面 is not None:
        启动画面.记("主窗口首次显示 用时 %.0f 毫秒" % ((time.monotonic() - _t) * 1000.0))
        启动画面.收尾(窗口)

    应用.aboutToQuit.connect(_收尾后台)
    return 应用.exec()


if __name__ == "__main__":
    sys.exit(主())