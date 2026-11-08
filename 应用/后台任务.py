# -*- coding: utf-8 -*-
"""
后台取数：把网络请求挪出 UI 线程，界面才不会卡成白屏。

关键约束（之前踩过的坑，务必保留）：**全局只能有一个工作线程**。
akshare 底层的 py_mini_racer 不是线程安全的，两个线程同时调 akshare 会直接
把整个进程带走，报的是 `[FATAL:partition_address_space.cc(243)] Check failed`。
所以这里强制 QThreadPool.setMaxThreadCount(1)：任务排队串行跑，
用户看到的是「一个接一个」，而不是崩溃。

回调为什么要绕这么大一圈：
QRunnable 是 C++ 对象，跑完会被 Qt 自动删掉；如果直接在自己的信号对象上
connect 用户的回调，那个信号对象活不到回调真正执行的那一刻 —— 事件还在队列里，
发送方就没了，回调永远不触发（不报错，只是静默不执行）。
所以统一挂到一个长期存活、且属于主线程的中转对象上：
worker 线程发带编号的信号，中转站排队回到主线程，再取出对应的回调执行。

用法：

    def 取数(代码):
        return data_fetcher.个股日线(代码)

    后台运行(取数, 完成=界面更新, 失败=弹错误, 参数=("600111",))
"""

import itertools
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _桥(QObject):
    """
    主线程上的信号中转站。

    它只在主线程里被创建，跨线程 emit 时 Qt 自动排队到主线程执行槽函数，
    所以界面更新一定发生在 UI 线程。
    """

    完成 = Signal(str, object)
    失败 = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._回调 = {}
        self.完成.connect(self._收完成)
        self.失败.connect(self._收失败)

    def 登记(self, 编号: str, 完成回调, 失败回调):
        self._回调[编号] = (完成回调, 失败回调)

    def 注销(self, 编号: str):
        self._回调.pop(编号, None)

    def _收完成(self, 编号: str, 结果):
        完成回调, _ = self._回调.pop(编号, (None, None))
        try:
            if 完成回调 is not None:
                完成回调(结果)
        except Exception:
            print("界面回调出错（完成）：")
            print(traceback.format_exc())
        finally:
            收尾(编号)

    def _收失败(self, 编号: str, 文本: str):
        _, 失败回调 = self._回调.pop(编号, (None, None))
        try:
            if 失败回调 is not None:
                失败回调(文本)
        except Exception:
            print("界面回调出错（失败）：")
            print(traceback.format_exc())
        finally:
            收尾(编号)


_桥对象 = None


def 桥() -> _桥:
    global _桥对象
    if _桥对象 is None:
        _桥对象 = _桥()
    return _桥对象


def _安全发出(信号, *参数):
    """
    安全地发信号。

    程序退出的瞬间，中转站对象可能已经被 Qt 销毁，这时候 emit 会抛
    RuntimeError: Signal source has been deleted。本来就要退出了，
    结果也没人接，静默丢掉就行，不必让控制台刷一屏红字。
    """
    try:
        信号.emit(*参数)
    except RuntimeError:
        pass
    except Exception:
        pass


class 任务(QRunnable):
    """把一个普通函数丢到后台线程跑，结果通过中转站回到主线程。"""

    def __init__(self, 函数, 参数=(), 关键字=None, 编号: str = ""):
        super().__init__()
        self._函数 = 函数
        self._参数 = 参数
        self._关键字 = 关键字 or {}
        self._编号 = 编号
        self._桥 = 桥()
        # 自己管生命周期：跑完要等主线程把回调执行掉，持有它的集合才会放手
        self.setAutoDelete(False)

    def run(self):
        try:
            结果 = self._函数(*self._参数, **self._关键字)
            _安全发出(self._桥.完成, self._编号, 结果)
        except Exception as 错:
            print("后台任务出错：%s: %s" % (type(错).__name__, 错))
            print(traceback.format_exc())
            _安全发出(self._桥.失败, self._编号, "%s: %s" % (type(错).__name__, 错))


_池 = None
_存活 = {}          # 编号 -> 任务，防止 Python 侧被回收
_在跑 = 0           # 已提交但回调还没执行完的任务数
_编号源 = itertools.count(1)


def 线程池() -> QThreadPool:
    global _池
    if _池 is None:
        池 = QThreadPool.globalInstance()
        池.setMaxThreadCount(1)  # 见文件头说明，绝不能改成 >1
        # 线程过期时间设成 -1（永不过期）：QThreadPool 默认 30 秒没活就销毁工作线程，
        # 下一次任务换个新线程跑。py_mini_racer 的 V8 分区分配器只允许初始化一次，
        # 换线程重新初始化会直接 [FATAL:partition_address_space.cc(243)] 杀进程。
        # 代价只是常驻一个空闲线程，换来的是不会再随机崩。
        池.setExpiryTimeout(-1)
        _池 = 池
    return _池


def 后台运行(函数, 完成=None, 失败=None, 参数=(), 关键字=None):
    """启动一个后台任务，立刻返回，不阻塞界面。"""
    global _在跑
    编号 = "任务%d" % next(_编号源)
    桥().登记(编号, 完成, 失败)
    任务对象 = 任务(函数, 参数, 关键字, 编号)
    _存活[编号] = 任务对象
    _在跑 += 1
    线程池().start(任务对象)
    return 编号


def 收尾(编号: str):
    """回调执行完把任务放掉，并把待办计数减一。"""
    global _在跑
    if _存活.pop(编号, None) is not None:
        _在跑 = max(0, _在跑 - 1)


def 空闲() -> bool:
    """
    当前有没有任务没跑完。

    不能只看 activeThreadCount：任务提交后线程还没被唤醒的那一瞬间它是 0，
    会造成「明明在拉数据却报空闲」。所以自己记一个待办计数。
    """
    return _在跑 == 0 and 线程池().activeThreadCount() == 0


def 等待全部(毫秒: int = 30000) -> bool:
    """给自动化验证用：等后台任务全部结束。"""
    return 线程池().waitForDone(毫秒)