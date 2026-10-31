# -*- coding: utf-8 -*-
"""限时运行 demo main 捕获启动期错误（6 秒自动退出）。"""
import sys
import traceback
from pathlib import Path

sys.argv = ["demo_main.py"]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

_orig_exec = QApplication.exec


def _timed_exec(self):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(6000, self.quit)
    return _orig_exec(self)


QApplication.exec = staticmethod(_timed_exec)

try:
    import demo_main
    rc = demo_main.main()
    print("main returned", rc)
    sys.stdout.flush()
except SystemExit as e:
    print("SystemExit", e.code)
    sys.stdout.flush()
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
