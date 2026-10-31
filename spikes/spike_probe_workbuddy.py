"""spike_probe_workbuddy.py —— 探测 WorkBuddy 聊天输入框的文本可读性

背景：用户报告在 WorkBuddy 输入框测试时，偶发"调出之前发送的信息全文"。
主嫌疑 = SELECT 模式导航键（↑↓/Space/PgDn）在组合已结束时漏进输入框。
泄漏概率取决于：WorkBuddy 输入框能否被 ime_feedback 读取（读不到 = UNKNOWN
= 持续停在 SELECT = 持续泄漏）。

方法：启动后 3 秒内**点击 WorkBuddy 输入框**（不抢焦点，读当前焦点控件），
输出控件类名/读取通道/文本长度，判定可读性。
"""
import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

u32 = ctypes.windll.user32


def class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def main():
    print("请在 3 秒内点击 WorkBuddy 的对话输入框（随便点一下即可）...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    from io_sink.ime_feedback import (get_focus_hwnd, read_focus_text,
                                      match_composition)
    hwnd = get_focus_hwnd()
    if not hwnd:
        print("FAIL: 无焦点控件")
        return 1
    print(f"焦点 hwnd={hwnd} class={class_name(hwnd)!r}")
    t0 = time.perf_counter()
    text = read_focus_text(hwnd, retries=2, delay=0.1)
    dt = (time.perf_counter() - t0) * 1000
    if text is None:
        print(f"结果: 不可读（UIA 与 WM_GETTEXT 均失败）耗时 {dt:.0f}ms")
        print("结论: WorkBuddy 输入框 = UNKNOWN → MSI 会持续停留在 SELECT → "
              "导航键持续漏进输入框（泄漏实锤路径）")
        return 1
    show = text[-80:] if len(text) > 80 else text
    print(f"结果: 可读 通道耗时 {dt:.0f}ms 长度 {len(text)} 尾部={show!r}")
    state, rem = match_composition("nihao", text)
    print(f"判定测试（假前缀 nihao）: state={state} remaining={rem!r}")
    print("结论: 可读 → ENDED 判定可用 → 泄漏只发生在确认后 180ms 窗口内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
