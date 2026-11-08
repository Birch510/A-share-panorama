# -*- coding: utf-8 -*-
"""
双击我就能打开看板（源码运行版）。

不要双击 main.py —— 那个是给打包和命令行用的入口，
这里多做了两件事：缺库时给出清楚的中文提示，出错时窗口不闪退。
"""

import os
import subprocess
import sys

根目录 = os.path.dirname(os.path.abspath(__file__))
os.chdir(根目录)
if 根目录 not in sys.path:
    sys.path.insert(0, 根目录)


def 检查依赖():
    缺 = []
    for 模块名, 包名 in [
        ("PySide6", "PySide6"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("akshare", "akshare"),
        ("requests", "requests"),
        ("openpyxl", "openpyxl"),
    ]:
        try:
            __import__(模块名)
        except Exception:
            缺.append(包名)
    return 缺


def 主():
    缺 = 检查依赖()
    if 缺:
        print("缺少这些运行库：%s" % "、".join(缺))
        print("")
        print("请在命令行里执行下面这一行装好，然后再双击本文件：")
        print("")
        print("    %s -m pip install -r requirements.txt" % sys.executable)
        print("")
        try:
            input("按回车键关闭这个窗口…")
        except Exception:
            pass
        return 1

    print("正在启动 A股全景看板（桌面版）…")
    print("界面是 Qt 原生窗口，不会打开浏览器，也不占用任何端口。")
    print("")

    结果 = subprocess.run([sys.executable, os.path.join(根目录, "main.py")] + sys.argv[1:])
    if 结果.returncode not in (0, None):
        print("")
        print("程序退出，返回码 %s。" % 结果.returncode)
        try:
            input("按回车键关闭这个窗口…")
        except Exception:
            pass
    return 结果.returncode or 0


if __name__ == "__main__":
    sys.exit(主())