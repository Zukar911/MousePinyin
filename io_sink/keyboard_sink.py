"""io_sink/keyboard_sink.py —— 键盘模拟输出层（D-018 核心输出）

把状态机 Action 翻译为模拟键盘按键（SendInput，pynput Controller）：
输入法视角与真实键盘无差别，由微软拼音完成字库/联想/上屏。

所有 send_* 必须在 Qt 主线程调用（架构约束 02 §2）。
demo 阶段即真实生效（键发往当前焦点窗口——测试时先点开一个输入框）。
"""

from PySide6.QtCore import QObject, Signal

from core.events import Action


class KeyboardSink(QObject):
    sent = Signal(str, bool)       # (兼容描述文本, ok)
    executed = Signal(str, bool)   # (实际执行详情, ok) —— D-030 调试：来自真实执行路径

    def __init__(self):
        super().__init__()
        self._kb = None
        self._keymap = None

    def _controller(self):
        if self._kb is None:
            from pynput.keyboard import Controller
            self._kb = Controller()
        return self._kb

    def _km(self):
        if self._keymap is None:
            from pynput.keyboard import Key
            self._keymap = {
                Action.SEND_UP: Key.up,
                Action.SEND_DOWN: Key.down,
                Action.SEND_SPACE: Key.space,
                Action.SEND_PAGEDOWN: Key.page_down,
                Action.BACKSPACE: Key.backspace,
            }
        return self._keymap

    # ---------- 状态机动作统一入口 ----------

    def execute(self, action: Action, payload: str = "") -> None:
        try:
            if action is Action.SEND_LETTER:
                self._controller().type(payload or "")
                self.sent.emit(payload, True)
                self.executed.emit(f"Unicode type('{payload}') → {len(payload or '')} 字符", True)
            elif action is Action.FIXUP:
                # 三键模式校正（D-049）：payload "N|letters"——先退 N 格再发字母
                try:
                    n_s, letters = (payload or "0|").split("|", 1)
                    n = max(0, int(n_s))
                except ValueError:
                    n, letters = 0, ""
                key = self._km()[Action.BACKSPACE]
                for _ in range(n):
                    self._kb.press(key)
                    self._kb.release(key)
                if letters:
                    self._kb.type(letters)
                self.sent.emit(f"⌫×{n}{letters}", True)
                self.executed.emit(f"校正：Backspace×{n} + type('{letters}')", True)
            elif action is Action.BACKSPACE:
                n = int(payload) if payload.isdigit() else 1   # 支持整音节撤销（多次退格）
                kb = self._controller()
                key = self._km()[Action.BACKSPACE]
                for _ in range(max(1, n)):
                    kb.press(key)
                    kb.release(key)
                self.sent.emit("⌫" * max(1, n), True)
                self.executed.emit(f"Backspace ×{max(1, n)}", True)
            elif action in self._km():
                key = self._km()[action]
                kb = self._controller()
                kb.press(key)
                kb.release(key)
                name = {Action.SEND_UP: "↑", Action.SEND_DOWN: "↓",
                        Action.SEND_SPACE: "Space（上屏）", Action.SEND_PAGEDOWN: "PageDown（翻页）"}[action]
                self.sent.emit({Action.SEND_UP: "↑", Action.SEND_DOWN: "↓",
                                Action.SEND_SPACE: "␣上屏", Action.SEND_PAGEDOWN: "翻页"}[action], True)
                self.executed.emit(f"按键 {name}", True)
            else:
                self.sent.emit("", True)
                self.executed.emit("（无输出动作）", True)
        except Exception as e:  # noqa: BLE001
            self.sent.emit(f"[发键失败:{e}]", False)
            self.executed.emit(f"执行异常：{e!r}", False)

    # ---------- 兼容旧接口（退格按钮直连） ----------

    def backspace(self) -> None:
        self.execute(Action.BACKSPACE)
