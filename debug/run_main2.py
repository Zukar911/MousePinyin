# -*- coding: utf-8 -*-
"""限时运行 demo main，traceback 写独立文件（绕过控制台编码）。"""
import sys
import traceback
from pathlib import Path

ERR = Path(__file__).resolve().parent / "_err.txt"
sys.argv = ["demo_main.py"]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

_orig_exec = QApplication.exec


def _timed_exec(self):
    from PySide6.QtCore import QTimer
    QTimer.singleShot(6000, self.quit)
    return _orig_exec(self)


QApplication.exec = staticmethod(_timed_exec)
out = []
try:
    import demo_main
    rc = demo_main.main()
    out.append(f"main returned {rc}")
except SystemExit as e:
    out.append(f"SystemExit {e.code}")
    tb = sys.exc_info()
except BaseException:
    import traceback
    out.append("EXCEPTION:")
    out.append(traceback.format_exc())
ERR.write_text("\n".join(out) or "(无输出——进程被硬终止)", encoding="utf-8")
