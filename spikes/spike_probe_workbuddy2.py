"""spike_probe_workbuddy2.py —— D-053 修复后复测：GetFocusedElement 通道
对 WorkBuddy（Chromium）输入框的读取效果（对比首版 ElementFromHandle 只
读到窗口标题）。3 秒内点击 WorkBuddy 对话输入框（建议打几个字）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    print("请在 3 秒内点击 WorkBuddy 的对话输入框（最好随便打几个字）...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    from io_sink.ime_feedback import (get_focused_text, get_focus_hwnd,
                                      read_focus_text, match_composition)
    # 通道 A：GetFocusedElement（D-053 新增）
    t0 = time.perf_counter()
    a = get_focused_text()
    ta = (time.perf_counter() - t0) * 1000
    print(f"A GetFocusedElement: {'成功' if a is not None else '失败'} "
          f"{ta:.0f}ms 长度={len(a) if a else 0} 尾部={a[-60:]!r}" if a
          else f"A GetFocusedElement: 失败 {ta:.0f}ms")
    # 通道 B：完整 read_focus_text（新顺序）
    hwnd = get_focus_hwnd()
    t0 = time.perf_counter()
    b = read_focus_text(hwnd, retries=1, delay=0.05)
    tb = (time.perf_counter() - t0) * 1000
    print(f"B read_focus_text(快速): {'成功' if b is not None else '失败'} "
          f"{tb:.0f}ms 长度={len(b) if b else 0} 尾部={b[-60:]!r}" if b
          else f"B read_focus_text(快速): 失败 {tb:.0f}ms")
    if b:
        state, rem = match_composition("nihao", b)
        print(f"判定测试（假前缀 nihao）: {state} remaining={rem!r}")
        print("✓ WorkBuddy 输入框可读 → UNKNOWN 概率大降 → 泄漏窗口收窄到确认后 180ms（已有门闸）")
        return 0
    print("✗ 仍不可读 → 泄漏风险仍在 UNKNOWN 路径（门闸只能覆盖确认后首导航）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
