"""io_sink/echo_sink.py —— 阶段一输出：demo 窗口内回显"""

from PySide6.QtCore import Signal, QObject


class EchoSink(QObject):
    """把上屏字符累积回显到 demo 窗口（信号通知 UI）。"""

    text_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.buffer = ""

    def commit(self, ch: str) -> None:
        self.buffer += ch
        self.text_changed.emit(self.buffer)

    def backspace(self) -> None:
        self.buffer = self.buffer[:-1]
        self.text_changed.emit(self.buffer)

    def clear(self) -> None:
        self.buffer = ""
        self.text_changed.emit(self.buffer)
