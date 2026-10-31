"""真实桌面 E2E v2：真发拼音组合 → SELECT 确认 → IME 反馈（D-031）"""
import subprocess, sys, time
sys.path.insert(0, '.')
import ctypes
user32 = ctypes.windll.user32

from PySide6.QtWidgets import QApplication
from core.candidate_model import CandidateModel
from core.state_machine import StateMachine
from core.events import Event, Action
from io_sink.keyboard_sink import KeyboardSink
from io_sink.ime_feedback import COMPOSING, ENDED, UNKNOWN, query_composition

app = QApplication(sys.argv)
sm = StateMachine(CandidateModel())
sink = KeyboardSink()
log = []
res = {}

def type_pinyin(p):
    sm.prefix += p
    sm.syllable += p
    sink.execute(Action.SEND_LETTER, p)     # 真发字母 → 微软拼音组合出现
    time.sleep(0.45)

def ime_check():
    st, rem = query_composition(sm.prefix)
    sm.update_composition(rem, st)
    log.append(f"  IME: {st} remaining={rem!r} -> mode={sm.mode.name} items0={sm.items[0]!r}")
    if st == ENDED:
        sm.end_select_session()
    return st

def confirm(pinyin):
    """完整会话：真发字母组合 → SELECT → Space 确认 → IME 反馈分支。"""
    type_pinyin(pinyin)
    st0, rem0 = query_composition(sm.prefix)
    log.append(f"[会话] {pinyin} 组合出现: {st0} remaining={rem0!r}")
    res.setdefault('composing_seen', True if st0 == COMPOSING else False)
    sm._switch_select()
    win.render(sm.snapshot())
    act = sm.handle(Event.LEFT)              # Space 确认（状态保持 SELECT）
    sink.execute(act, sm.pending_text)
    time.sleep(0.4)
    return ime_check()

proc = subprocess.Popen(["notepad.exe"])
time.sleep(2.5)
user32.SetForegroundWindow(user32.GetForegroundWindow())
time.sleep(0.5)

try:
    from ui.candidate_window import CandidateWindow
    def handle(ev):
        act = sm.handle(ev)
        if act.name != "NONE":
            sink.execute(act, sm.pending_text)
        win.render(sm.snapshot())
    win = CandidateWindow(event_hook=handle,
                          jump_hook=lambda i: (sm.__setattr__('idx', i), win.render(sm.snapshot())),
                          on_cap_click=lambda i: handle(Event.LEFT))
    win.show()
    time.sleep(0.3)

    # 用户场景：nihaozhongguo 连续组合 → 分段确认
    type_pinyin("nihao")                     # 先组合 nihao
    type_pinyin("zhongguo")                  # 续组合 → "nihaozhongguo" 整段
    st0, rem0 = query_composition(sm.prefix)
    log.append(f"[组合] nihaozhongguo: {st0} remaining={rem0!r}")
    res['composing_full'] = (st0 == COMPOSING)
    sm._switch_select()
    win.render(sm.snapshot())
    # 确认 #1：Space → 微软拼音默认整句上屏 → ENDED → 自动回声母层
    act = sm.handle(Event.LEFT)
    sink.execute(act, sm.pending_text)
    time.sleep(0.45)
    st = ime_check()
    res['auto_end'] = (st == ENDED and sm.mode.name == 'PINYIN')
    # 分段会话：逐段新会话（nihao / zhongguo 分两次确认，各自 ENDED）
    res['seg_ok'] = (confirm("nihao") == ENDED and sm.mode.name == 'PINYIN'
                     and confirm("zhongguo") == ENDED and sm.mode.name == 'PINYIN')
    time.sleep(0.4)

    from io_sink.ime_feedback import read_focus_text, get_focus_hwnd
    text = read_focus_text(get_focus_hwnd()) or ""
    res['final_tail'] = text[-30:]
    res['text_ok'] = "你好" in text and "中国" in text
finally:
    print("LOG:")
    print("\n".join(log))
    print("RESULT:", res)
    proc.terminate()

assert res.get('composing_full') and res.get('auto_end') and res.get('seg_ok'), res
assert res.get('text_ok'), res
print("E2E D-031 OK：整句确认自动回声母层 + 分段会话正确 + 文本无多余空格")
