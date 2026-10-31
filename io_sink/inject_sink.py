"""io_sink/inject_sink.py —— 阶段二输出：Unicode 注入（P4）

- commit(ch)：pynput keyboard.Controller.type() —— SendInput+KEYEVENTF_UNICODE，
  不要求目标窗口开启输入法（T-004 已实测）。
- backspace()：注入一次退格（X2 侧键撤销）。
- 所有注入调用必须发生在主线程（架构约束，见 02 §2）。
"""

import threading

from PySide6.QtCore import Signal, QObject


class InjectSink(QObject):
    injected = Signal(str, bool)   # (text, ok)

    def __init__(self):
        super().__init__()
        self._kb = None

    def _controller(self):
        if self._kb is None:
            from pynput.keyboard import Controller
            self._kb = Controller()
        return self._kb

    def commit(self, ch: str) -> None:
        try:
            self._controller().type(ch)
            self.injected.emit(ch, True)
        except Exception as e:                       # noqa: BLE001
            self.injected.emit(f"[注入失败:{e}]", False)

    def backspace(self) -> None:
        try:
            from pynput.keyboard import Key
            kb = self._controller()
            kb.press(Key.backspace)
            kb.release(Key.backspace)
            self.injected.emit("", True)
        except Exception as e:                       # noqa: BLE001
            self.injected.emit(f"[退格失败:{e}]", False)
