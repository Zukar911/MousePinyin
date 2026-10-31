"""io_sink/ime_feedback.py —— 跨进程读取微软拼音组合状态（D-031/D-053）

读取通道（spike_ime_read.py 真实 notepad + 微软拼音验证）：
  0. UIA GetFocusedElement（D-053 新增）——**直接取 UIA 树的焦点元素**，
     对 Chromium/Electron 应用（WorkBuddy 等）远比 ElementFromHandle(hwndFocus)
     准确：后者常拿到容器/顶层元素（spike_probe_workbuddy 实测只读到窗口
     标题 "WorkBuddy" 而非输入框内容），导致 UNKNOWN → SELECT 模式停留 →
     导航键（↑↓/Space/PgDn）漏进输入框（聊天输入框 ↑ = 调出上一条已发送
     消息全文——用户实测报告的泄漏路径）。
  1. UIA TextPattern / ValuePattern（焦点控件 hwnd 直取）——现代应用（新记事本等）
  2. WM_GETTEXT（焦点控件）——经典 Win32 Edit 兜底
判定（match_composition，纯函数可测）：
  COMPOSING —— 目标文本尾部仍含程序已发送拼音的某个后缀（剩余可确定）
  ENDED     —— 文本存在但拼音尾部已消失（确认的汉字已上屏）
  UNKNOWN   —— 读不到文本 / 无法比对（如非内联组合、密码框、非标准控件）

诚实原则：读取不到就返回 UNKNOWN，绝不拿内部缓冲冒充剩余组合。
ImmGetContext 跨进程无效（spike 实测 NULL），已排除；不使用候选窗存在性、
固定延时或候选字数推算。
"""

import ctypes
import time

COMPOSING = "COMPOSING"
ENDED = "ENDED"
UNKNOWN = "UNKNOWN"

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
_user32 = ctypes.windll.user32

# UIA 会话缓存（comtypes CreateObject 开销大——每次重建数十 ms，D-053）
_uia_cache: dict = {"iuia": None}


def _get_iuia():
    """进程内缓存的 IUIAutomation 实例（创建失败返回 None）。"""
    if _uia_cache["iuia"] is not None:
        return _uia_cache["iuia"]
    try:
        import comtypes.client
        mod = comtypes.client.GetModule("UIAutomationCore.dll")
        iuia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=mod.IUIAutomation)
        _uia_cache["iuia"] = iuia
        _uia_cache["mod"] = mod
        return iuia
    except Exception:
        return None


def _uia_pattern_text(el) -> str | None:
    """从 UIA 元素提取文本（ValuePattern → TextPattern）。"""
    mod = _uia_cache.get("mod")
    if el is None or mod is None:
        return None
    try:
        vp = el.GetCurrentPattern(mod.UIA_ValuePatternId)
        if vp:
            val = vp.QueryInterface(mod.IUIAutomationValuePattern).CurrentValue
            if val:
                return val
    except Exception:
        pass
    try:
        tp = el.GetCurrentPattern(mod.UIA_TextPatternId)
        if tp:
            doc = tp.QueryInterface(mod.IUIAutomationTextPattern).DocumentRange
            return doc.GetText(-1)
    except Exception:
        pass
    return None


def get_focused_text() -> str | None:
    """UIA GetFocusedElement 通道（D-053）：直接读 UIA 树的焦点元素文本。
    对 Chromium/Electron 深层输入框比 ElementFromHandle(hwndFocus) 准确。"""
    iuia = _get_iuia()
    if iuia is None:
        return None
    try:
        el = iuia.GetFocusedElement()
        if el is None:
            return None
        name = _uia_pattern_text(el)
        if name:
            return name
        # Value/Text 都没有时退回元素 Name（输入框常有可读 Name，但
        # 静态标签会误报——只接受非空且变化过的值由上层比对兜底）
        return None
    except Exception:
        return None


def get_focus_hwnd() -> int:
    """前台线程的焦点控件 hwnd（跨进程，GetGUIThreadInfo）。"""
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                    ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                    ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                    ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                    ("rcCaret", ctypes.c_uint * 4)]
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    _user32.GetGUIThreadInfo(0, ctypes.byref(gti))
    return gti.hwndFocus or 0


def _uia_read(hwnd) -> str | None:
    """UIA 焦点元素文本（ValuePattern → TextPattern）。异常返回 None。"""
    iuia = _get_iuia()
    if iuia is None:
        return None
    try:
        el = iuia.ElementFromHandle(hwnd)
        return _uia_pattern_text(el)
    except Exception:
        return None


def _wm_gettext(hwnd) -> str | None:
    """WM_GETTEXT 读取（经典 Win32 Edit 控件）。"""
    try:
        length = _user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
        if length <= 0:
            return None
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
        return buf.value
    except Exception:
        return None


def read_focus_text(hwnd: int | None = None, retries: int = 4,
                    delay: float = 0.15) -> str | None:
    """读焦点控件文本：GetFocusedElement → UIA(hwnd) → WM_GETTEXT；带重试。
    重试原因：确认键后 IME 候选/组合窗会短暂成为焦点元素（无 Value/Text
    pattern），等其消失后编辑区文本才可读（D-031 实测）。"""
    for _ in range(max(1, retries)):
        # D-053：GetFocusedElement 优先（Chromium 深层输入框唯一可靠通道）
        text = get_focused_text()
        if text is None and hwnd:
            text = _uia_read(hwnd)
        if text is None:
            h = hwnd or get_focus_hwnd()
            if h:
                text = _wm_gettext(h)
        if text is not None:
            return text
        time.sleep(delay)
        hwnd = hwnd or get_focus_hwnd()
    return None


def normalize(s: str) -> str:
    """归一化：去隔音符/空格，转小写（拼音比对用）。"""
    return s.replace("'", "").replace("’", "").replace(" ", "").lower()


def match_composition(prefix: str, text: str | None) -> tuple[str, str | None]:
    """纯函数：比对目标文本与程序已发送拼音，判定组合状态。

    返回 (state, remaining)：
      (COMPOSING, "zhongguo") —— 文本尾部含 prefix 的最长后缀（剩余可确定）
      (ENDED, None)           —— 文本存在但拼音尾已消失
      (UNKNOWN, None)         —— 文本不可读或无法比对
    """
    if not prefix or text is None:
        return UNKNOWN, None
    norm_text = normalize(text)[-128:]           # 只看尾部，避开长文档
    p = normalize(prefix)
    if not p:
        return UNKNOWN, None
    # 找最长 k：norm_text 以 prefix 的长度 k 后缀结尾（该后缀 = 当前组合剩余）
    for k in range(min(len(p), 32), 0, -1):
        if norm_text.endswith(p[-k:]):
            return COMPOSING, p[-k:]
    return ENDED, None


def query_composition(prefix: str, hwnd: int | None = None,
                      retries: int = 4, delay: float = 0.15) -> tuple[str, str | None]:
    """便捷入口：读焦点文本（带重试）→ 判定。返回 (state, remaining)。"""
    text = read_focus_text(hwnd, retries=retries, delay=delay)
    if text is None:
        return UNKNOWN, None
    return match_composition(prefix, text)
