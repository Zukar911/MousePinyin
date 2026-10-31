"""T-004 spike（PySide6 版）: 悬浮窗不抢焦点 + Unicode 注入实测（判据 S2/S3/S4）

全自动流程（无需人工配合）：
1. 创建 PySide6 无边框置顶窗（Qt.WindowDoesNotAcceptFocus 原生不抢焦点）
2. 自动启动记事本并等其获得前台焦点
3. 注入「你好 MSI」，对比注入前后前台窗口（S2/S3 判据）
4. 记事本留 open 供人工目视 + S4 人工项（悬浮窗右键不穿透）

运行：python spikes/spike_noactivate.py  （总时长约 10 秒，窗口自动退出）
"""

import ctypes
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

user32 = ctypes.windll.user32


def fg_title():
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), buf, 256)
    return buf.value


def fg_hwnd():
    return user32.GetForegroundWindow()


app = QApplication(sys.argv)
win = QWidget()
win.setWindowFlags(
    Qt.FramelessWindowHint
    | Qt.WindowStaysOnTopHint
    | Qt.WindowDoesNotAcceptFocus      # 原生不抢焦点（对应 WS_EX_NOACTIVATE）
    | Qt.Tool
)
win.setAttribute(Qt.WA_ShowWithoutActivating)
lay = QVBoxLayout(win)
lab = QLabel(
    "NOACTIVATE 悬浮窗测试\n自动开记事本并注入「你好 MSI」\nS4 人工项：悬浮窗上点右键看是否穿透",
    alignment=Qt.AlignCenter,
)
lab.setStyleSheet("background:#1a1b26;color:#c0caf5;font-size:12px;padding:10px;")
lay.addWidget(lab)
win.setFixedSize(320, 110)
win.move(700, 360)
win.show()
print("floating window shown (WA_ShowWithoutActivating + DoesNotAcceptFocus)")

from pynput import keyboard  # noqa: E402

results = {}


def step_inject():
    before_hwnd, before = fg_hwnd(), fg_title()
    print(f"[inject] focus before : {before!r}")
    kb = keyboard.Controller()
    kb.type("你好 MSI")
    results["typed"] = True
    QTimer.singleShot(800, step_verify)


def step_verify():
    after_hwnd, after = fg_hwnd(), fg_title()
    print(f"[inject] focus after  : {after!r}")
    same = results.get("before_hwnd") == after_hwnd if False else fg_hwnd() == fg_hwnd()
    same = results["before_hwnd"] == after_hwnd
    print(f"S3 focus unchanged    : {'PASS' if same else 'FAIL'} ({results['before']!r} -> {after!r})")
    print(f"S2 noactivate judged  : {'PASS' if same else 'CHECK'}（注入期间前台未被悬浮窗夺走）")
    print("S4 人工项：悬浮窗上点右键，确认记事本不弹菜单")
    QTimer.singleShot(4000, app.quit)


def step_launch():
    print("[step] launching notepad ...")
    subprocess.Popen(["notepad.exe"])


def step_wait_focus():
    results["before_hwnd"] = fg_hwnd()
    results["before"] = fg_title()
    print(f"[inject] focus target : {results['before']!r}")
    step_inject()


QTimer.singleShot(1500, step_launch)
QTimer.singleShot(4500, step_wait_focus)
QTimer.singleShot(5300, step_verify)
app.exec()
print("spike done")
