"""spike_global_hook.py —— T-014 前置：pynput 全局鼠标钩子行为验证（真桌面）

验证点（程序化自测，合成事件经过真实系统钩子链）：
  V1 全局钩子收到合成滚轮/左键/右键/移动事件（Py3.13 + pynput Listener）
  V2 区域感知：指针在目标窗口矩形内 → 投递语义事件；窗外 → 零处理
  V3 Ctrl+Alt+M 热键 toggle（D-009 手写组合判定方案的复用验证）
  V4 钩子线程 → Qt 主线程投递（槽执行线程 == 主线程）
  V5 DoesNotAcceptFocus 窗口上合成点击不切前台（注入安全前提）
语义：**解释但不吞**（不改系统事件流——Dock 分层窗口本身不穿透，
无需低级钩子吞事件；吞事件需要 raise Listener.suppress_exception，
本次不引入）。
"""
import ctypes
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget

u32 = ctypes.windll.user32


def _fw_title() -> str:
    import ctypes.wintypes as wt
    h = u32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(h, buf, 256)
    return f"hwnd={h} title={buf.value!r}"


class HookSource(QObject):
    """P4 输入源原型：全局鼠标钩子 + 区域感知 + 热键开关。"""
    semantic = Signal(object)      # core 语义事件（跨线程 queued）
    raw = Signal(str)              # 观测记录（任何事件，供统计）

    def __init__(self, rect_fn):
        super().__init__()
        self._rect_fn = rect_fn
        self.enabled = True
        self.main_thread = threading.main_thread()
        self.slots_thread = None

    def start(self):
        from pynput import keyboard, mouse
        self._ml = mouse.Listener(
            on_move=self._on_move, on_click=self._on_click,
            on_scroll=self._on_scroll)
        self._ml.daemon = True
        self._ml.start()
        self._held = set()
        self._kl = keyboard.Listener(on_press=self._on_key,
                                     on_release=self._on_key_rel)
        self._kl.daemon = True
        self._kl.start()

    # ---- 钩子线程 ----
    def _in_rect(self):
        from pynput.mouse import Controller as MController
        pt = MController().position
        r = self._rect_fn()
        return (r[0] <= pt[0] < r[0] + r[2] and r[1] <= pt[1] < r[1] + r[3]), pt

    def _emit(self, kind, ev=None):
        inside, pt = self._in_rect()
        self.raw.emit(f"{kind}@({pt[0]},{pt[1]}) inside={inside}")
        if not inside or not self.enabled:
            return                      # 区域感知：窗外零处理直接放行
        if ev is not None:
            self.slots_thread = threading.current_thread()
            self.semantic.emit(ev)      # 跨线程 queued → 主线程槽

    def _on_move(self, x, y):
        pass                            # move 不投递语义（仅 raw 统计可选）

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        from core.events import Event
        # pynput button.name = 'left' / 'right' / 'x1' / 'x2'（非 Button.left）
        m = {"left": Event.LEFT, "right": Event.RIGHT,
             "x1": Event.X1, "x2": Event.X2}
        if button.name in m:
            self._emit(f"click:{button.name}", m[button.name])

    def _on_scroll(self, x, y, dx, dy):
        from core.events import Event
        self._emit(f"scroll:{'up' if dy > 0 else 'down'}",
                   Event.SCROLL_UP if dy > 0 else Event.SCROLL_DOWN)

    def _on_key(self, k):
        # D-009 手写组合判定：held 集合 + 修饰键检测（Ctrl+Alt+M）
        from pynput import keyboard as kb
        self._held.add(k)
        mods = {kb.Key.ctrl, kb.Key.ctrl_l, kb.Key.ctrl_r,
                kb.Key.alt, kb.Key.alt_l, kb.Key.alt_r, kb.Key.alt_gr}
        if any(m in self._held for m in mods) and getattr(k, "vk", None) == 77:
            self.semantic.emit("TOGGLE")

    def _on_key_rel(self, k):
        self._held.discard(k)


def main():
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                       | Qt.WindowDoesNotAcceptFocus | Qt.Tool)
    win.setAttribute(Qt.WA_ShowWithoutActivating)
    win.setAttribute(Qt.WA_TranslucentBackground)   # 与真实 Dock 一致（分层窗口）
    win.setStyleSheet("background:rgba(80,80,120,120);border-radius:12px;")
    geo = app.primaryScreen().availableGeometry()
    win.setGeometry(geo.center().x() - 200, geo.bottom() - 140, 400, 80)
    win.show()
    app.processEvents()
    g = win.frameGeometry()
    rect_fn = lambda: (g.x(), g.y(), g.width(), g.height())
    print(f"窗口逻辑几何: {g.x()},{g.y()} {g.width()}x{g.height()}  "
          f"DPR={app.primaryScreen().devicePixelRatio()}")
    from pynput.mouse import Controller as _MC
    _pos = _MC().position
    _qt = win.mapFromGlobal(__import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(*_pos))
    print(f"pynput 原始位置: {_pos} → Qt mapFromGlobal: {_qt.x()},{_qt.y()}")

    src = HookSource(rect_fn)
    events, raws, slot_threads = [], [], []
    src.semantic.connect(lambda ev: (events.append(ev),
                                     slot_threads.append(threading.current_thread())))
    src.raw.connect(lambda s: raws.append(s))
    src.start()
    time.sleep(0.3)

    from pynput.keyboard import Controller as KController, Key
    from pynput.mouse import Button, Controller as MController
    mc, kc = MController(), KController()
    fw_before = u32.GetForegroundWindow()

    # V1a+V2a：窗内左键（DoesNotAcceptFocus 安全）
    cx, cy = g.x() + g.width() // 2, g.y() + g.height() // 2
    mc.position = (cx, cy); time.sleep(0.2)
    mc.click(Button.left); time.sleep(0.3)

    # V1b：窗内滚轮
    mc.scroll(0, 120); time.sleep(0.3)

    # V1c：窗内右键
    mc.click(Button.right); time.sleep(0.3)

    # V2b：窗外移动 + 滚轮（零投递验证；不合成窗外点击——避免点到用户其他窗口）
    out_x, out_y = g.x() - 150, g.y() - 150
    mc.position = (out_x, out_y); time.sleep(0.25)
    mc.scroll(0, 120); time.sleep(0.3)
    mc.position = (cx, cy)                    # 移回，后续测试不受影响

    # V3：Ctrl+Alt+M 合成（组合键不会向焦点输入框打字）
    kc.press(Key.ctrl); kc.press(Key.alt); kc.press("m")
    time.sleep(0.15)
    kc.release("m"); kc.release(Key.alt); kc.release(Key.ctrl)
    time.sleep(0.4)

    app.processEvents()

    fw_after = u32.GetForegroundWindow()
    sem_kinds = [e.name if hasattr(e, "name") else str(e) for e in events]
    checks = []
    checks.append(("V1a 窗内左键投递", "LEFT" in sem_kinds))
    checks.append(("V1b 窗内滚轮投递", "SCROLL_UP" in sem_kinds))
    checks.append(("V1c 窗内右键投递", "RIGHT" in sem_kinds))
    checks.append(("V2 窗外零投递（滚轮）",
                   sem_kinds.count("SCROLL_UP") == 1))
    checks.append(("V3 Ctrl+Alt+M toggle", "TOGGLE" in sem_kinds))
    ok_thread = all(t is threading.main_thread() for t in slot_threads)
    checks.append(("V4 槽均在主线程执行", ok_thread and bool(slot_threads)))
    checks.append(("V5 DoesNotAcceptFocus 点击不切前台", fw_before == fw_after))

    print("=" * 56)
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 56)
    print("语义事件:", sem_kinds)
    print("原始钩子观测:", raws)
    print("前台窗口变化:", "无" if fw_before == fw_after else "有（异常）")
    print("  前台 before:", _fw_title())
    print("  前台 after :", _fw_title())
    # 结论落盘
    out = Path(__file__).parent / "global_hook_result.md"
    lines = ["# spike_global_hook 结论（真桌面）", ""]
    for name, ok in checks:
        lines.append(f"- {'PASS' if ok else 'FAIL'}  {name}")
    lines += ["", f"语义事件序列: {sem_kinds}", f"原始观测: {raws}",
              "语义: 解释但不吞（不改系统事件流）", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"结论已写入 {out}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
