"""spike_ime_read.py —— 验证跨进程读取微软拼音组合状态（D-031 spike）

方法矩阵：
  A. ImmGetContext(其他进程 hwnd) —— 预期无效（文档限定同进程），实测确认
  B. WM_GETTEXT —— 仅经典 Win32 Edit 控件有效（新版记事本无效）
  C. UIA ValuePattern/TextPattern —— 跨进程，现代应用有效

流程：启动真实 notepad 独立进程 → 聚焦 → SendInput 发 'zhong'（微软拼音组合）
→ 读回文本尾部（应含组合拼音 zhong = COMPOSING 证据）→ 发 Space（确认上屏）
→ 读回（拼音消失、出现汉字 = ENDED 证据）→ 结论写入 spikes/ime_read_result.md
"""
import ctypes
import subprocess
import sys
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E


def send_text(text: str) -> None:
    from pynput.keyboard import Controller
    Controller().type(text)


def send_space() -> None:
    from pynput.keyboard import Key, Controller
    kb = Controller()
    kb.press(Key.space)
    kb.release(Key.space)


def get_focus_hwnd() -> int:
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                    ("hwndActive", ctypes.c_void_p), ("hwndFocus", ctypes.c_void_p),
                    ("hwndCapture", ctypes.c_void_p), ("hwndMenuOwner", ctypes.c_void_p),
                    ("hwndMoveSize", ctypes.c_void_p), ("hwndCaret", ctypes.c_void_p),
                    ("rcCaret", ctypes.c_uint * 4)]
    gti = GUITHREADINFO()
    gti.cbSize = ctypes.sizeof(GUITHREADINFO)
    user32.GetGUIThreadInfo(0, ctypes.byref(gti))
    return gti.hwndFocus or 0


def wm_gettext(hwnd) -> str | None:
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if length <= 0:
        return None
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
    return buf.value


def uia_read(hwnd) -> str | None:
    """UIA：对焦点控件 hwnd 取 ElementFromHandle，优先 Value，退化 Text。"""
    try:
        import comtypes.client
        mod = comtypes.client.GetModule("UIAutomationCore.dll")
        iuia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=mod.IUIAutomation)
        el = iuia.ElementFromHandle(hwnd)
        if el is None:
            print("  [UIA] ElementFromHandle -> None")
            return None
        try:
            vp = el.GetCurrentPattern(mod.UIA_ValuePatternId)
            if vp:
                val = vp.QueryInterface(mod.IUIAutomationValuePattern).CurrentValue  # 属性
                if val:
                    return val
                print("  [UIA] ValuePattern ok but empty")
        except Exception as e:
            print(f"  [UIA] ValuePattern: {e!r}")
        try:
            tp = el.GetCurrentPattern(mod.UIA_TextPatternId)
            if tp:
                doc = tp.QueryInterface(mod.IUIAutomationTextPattern).DocumentRange  # 属性
                return doc.GetText(-1)
            print("  [UIA] no TextPattern")
        except Exception as e:
            print(f"  [UIA] TextPattern: {e!r}")
    except Exception as e:
        print(f"  [UIA error] {e!r}")
        return None
    return None


def tail_match(text: str | None, needle: str) -> bool:
    if not text:
        return False
    norm = text.replace("'", "").replace("’", "").lower()
    return needle in norm[-64:]


def main():
    result = []
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(2.5)
    hwnd = get_focus_hwnd()                      # 焦点控件（编辑区），不取 GA_ROOT
    print(f"notepad pid={proc.pid} focus hwnd=0x{hwnd:X}")

    # A. IMM 跨进程
    himc = ctypes.windll.imm32.ImmGetContext(hwnd)
    result.append(("A. ImmGetContext(跨进程)", "NULL（无效）" if not himc else f"himc={himc:#x}"))

    # B. WM_GETTEXT
    b0 = wm_gettext(hwnd)
    result.append(("B. WM_GETTEXT", f"可读，len={len(b0)}" if b0 is not None else "无内容/无效"))

    # C. UIA
    c0 = uia_read(hwnd)
    result.append(("C. UIA Value/Text", f"可读，len={len(c0)}" if c0 is not None else "不可用"))

    reader = (lambda: uia_read(hwnd)) if c0 is not None else (lambda: wm_gettext(hwnd))
    reader_name = "C. UIA" if c0 is not None else "B. WM_GETTEXT"

    send_text("zhong")
    time.sleep(1.2)
    composing = reader()
    composing_ok = tail_match(composing, "zhong")
    result.append((f"{reader_name} 组合中读 'zhong'", f"{'✓ 含 zhong（COMPOSING 可判定）' if composing_ok else '✗ 未读到：' + repr((composing or '')[-40:])}"))

    send_space()
    time.sleep(1.2)
    ended = reader()
    ended_ok = (ended is not None and not tail_match(ended, "zhong"))
    result.append((f"{reader_name} 确认后读", f"{'✓ 拼音消失（ENDED 可判定）尾部=' + repr((ended or '')[-20:]) if ended_ok else '✗ 仍含 zhong'}"))

    print()
    for k, v in result:
        print(f"{k}: {v}")
    proc.terminate()

    with open("spikes/ime_read_result.md", "w", encoding="utf-8") as f:
        f.write("# IME 组合状态跨进程读取 spike 结果\n\n")
        for k, v in result:
            f.write(f"- **{k}**：{v}\n")
        f.write(f"\n结论：采用 {reader_name} 作为组合状态读取通道；"
                f"{'COMPOSING/ENDED 均可判定' if composing_ok and ended_ok else '存在缺口，需保守 UNKNOWN 路径'}。\n")


if __name__ == "__main__":
    main()
