"""core/events.py —— 统一事件与动作定义（F-001 v2：双模式架构）

模式：PINYIN（拼字：Dock 导航字母前缀树，逐字母模拟键盘发键）
     SELECT（选字：模拟 ↑↓/空格/PgDn 操作微软拼音候选窗）

架构（D-018）：鼠标操作 → 软件模拟键盘按键 → 系统输入法完成字库/联想/上屏。
"""

from enum import Enum, auto


class Event(Enum):
    SCROLL_UP = auto()      # 滚轮上
    SCROLL_DOWN = auto()    # 滚轮下
    LEFT = auto()           # 左键：确认
    RIGHT = auto()          # 右键：拼字=切选字；选字=翻页
    X1 = auto()             # 侧键1：拼字↔选字模式切换
    X2 = auto()             # 侧键2：退格（拼字=删字母回退树；选字=回退拼音/删字）


class Mode(Enum):
    PINYIN = auto()   # 拼字模式
    SELECT = auto()   # 选字模式


class Stage(Enum):
    """拼字模式内部阶段（声母整发 + 韵母两级渐进 + 整句流，D-024）。"""

    INITIAL = auto()     # 选声母
    FINAL_HEAD = auto()  # 选韵头组（a/o/e/i/u/ü，不发键）
    FINAL_TAIL = auto()  # 选该组下韵尾 → 确认时整发韵母
    DONE = auto()        # 音节完成（选字 or 下一声母）


class Action(Enum):
    """状态机对外动作（由输出层 KeyboardSink 执行为键盘模拟）。"""

    NONE = auto()
    SEND_LETTER = auto()      # 发送字母键（payload: sm.pending_text）
    SEND_UP = auto()          # 候选高亮上移
    SEND_DOWN = auto()        # 候选高亮下移
    SEND_SPACE = auto()       # 空格上屏
    SEND_PAGEDOWN = auto()    # 候选翻页
    BACKSPACE = auto()        # 退格
    FIXUP = auto()            # 三键模式校正：payload "N|letters"（先退 N 格再发字母）
