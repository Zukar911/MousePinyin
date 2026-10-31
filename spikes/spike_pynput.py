"""T-003 spike: pynput@Py3.13 鼠标钩子/侧键/滚轮/热键实测（判据 S1）

结论（2026-10-20，对话#0）：
- 侧键 x1/x2、滚轮：mouse.Listener 捕获 PASS
- 热键：GlobalHotKeys 在 Py3.13 收键正常但组合匹配不触发（bug），
  改用 keyboard.Listener 手写组合判定 PASS（D-009）
自动化链路：pynput 注入事件 → 低级钩子捕获（SendInput 事件会被 WH_MOUSE_LL 捕获）。
"""
import time
from pynput import mouse, keyboard

captured = {"clicks": [], "scrolls": [], "hotkey": 0}

def on_click(x, y, button, pressed):
    if pressed:
        captured["clicks"].append(str(button))

def on_scroll(x, y, dx, dy):
    captured["scrolls"].append((dx, dy))

MODS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
        keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr}

def on_press(k):
    held.add(k)                     # 先入集合（修饰键也要记录按下状态）
    if k in MODS:
        return
    if any(m in held for m in MODS) and getattr(k, "vk", None) == 77:  # m
        captured["hotkey"] += 1
    held.discard(k)                 # 单发键不保持按下

def on_release(k):
    held.discard(k)

held = set()

ml = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
ml.daemon = True
ml.start()
print("mouse.Listener started:", ml.running)

kh = keyboard.Listener(on_press=on_press, on_release=on_release)
kh.daemon = True
kh.start()
print("keyboard.Listener (manual hotkey) started: ctrl+alt+m")

time.sleep(1.0)

ctl = mouse.Controller()
ctl.position = (2, 2)           # 指针移到屏幕角落，避免注入点击落在用户界面上
ctl.click(mouse.Button.x1)      # 侧键 X1（默认无系统行为，无害）
ctl.click(mouse.Button.x2)      # 侧键 X2（默认无系统行为，无害）
ctl.scroll(0, 2)                # 上滚
ctl.scroll(0, -2)               # 下滚
# 右键注入已移除：真实右键会在指针处弹菜单干扰用户，S4 右键判据改在 T-004 悬浮窗场景验证

kctl = keyboard.Controller()
with kctl.pressed(keyboard.Key.ctrl, keyboard.Key.alt):
    kctl.press("m")
    kctl.release("m")

time.sleep(2.0)
print("captured clicks  :", captured["clicks"])
print("captured scrolls :", captured["scrolls"])
print("captured hotkeys :", captured["hotkey"])

clicks = " ".join(captured["clicks"])
ok_side = ("x1" in clicks) and ("x2" in clicks)
ok_scroll = len(captured["scrolls"]) >= 2
ok_hotkey = captured["hotkey"] >= 1
print(f"S1 side-keys x1/x2 : {'PASS' if ok_side else 'FAIL'}")
print(f"S1 scroll          : {'PASS' if ok_scroll else 'FAIL'}")
print(f"S1 global hotkey   : {'PASS' if ok_hotkey else 'FAIL'}")
print("SPIKE_RESULT:", "PASS" if all([ok_side, ok_scroll, ok_hotkey]) else "FAIL")
