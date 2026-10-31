"""io_source/pynput_source.py —— P4 全局输入源（T-014，D-003 区域感知 + 热键开关）

全局鼠标钩子（pynput mouse.Listener 守护线程）+ 区域感知 + Ctrl+Alt+M 热键开关
+ 语义事件跨线程投递主线程。demo 阶段的 Qt 窗口事件路径保持为默认；本模块
以 `--global` 启用后成为唯一鼠标事件源（Qt 路径由 CandidateWindow.global_mode
抑制，避免双份处理）。

设计要点（spikes/spike_global_hook.py 真桌面实测定案，7/7 PASS）：
- **解释但不吞**：不改系统事件流。Dock 为分层窗口，收到的事件本就不穿透到
  下层窗口，无需低级钩子吞事件（吞 = raise Listener.suppress_exception，
  不引入——吞错一次会丢用户点击）。
- **区域判定在主线程**：钩子线程只投递「原始按键」，判定与解释在主线程用
  QCursor.pos()（跨屏/混合 DPI 映射始终正确）。spike 中间轮实测：多屏下
  pynput 钩子坐标与 Qt 逻辑坐标存在错位风险（合成点击偏出窗口一个坐标系）。
  主线程判定的事件延迟为毫秒级 queued 信号，用户在 50ms 内"窗外按下瞬间
  移入"的误判概率可忽略，且窗外事件本就无副作用（放行给焦点窗口）。
- **按钮区放行**：指针落在 ⚙/✕/⠿（或其矩形列表）上时不投递语义事件——
  这些独立 QToolButton 的点击继续由 Qt 正常处理。
- **热键**：D-009 手写组合判定（held 集合 + 修饰键检测）。Ctrl+Alt+M =
  输入会话开/关；关闭时 Dock 隐藏、全部鼠标事件零处理放行（防误触），
  再按恢复。
"""

import threading

from PySide6.QtCore import QObject, Signal

from core.events import Event

# pynput button.name → 语义事件（spike 实测 name 取值 'left'/'right'/'x1'/'x2'，
# 不是 "Button.left"——spike 首版映射键写错导致 click 全被过滤，教训固化）
_BUTTON_EVENTS = {
    "left": Event.LEFT,
    "right": Event.RIGHT,
    "x1": Event.X1,
    "x2": Event.X2,
}


def region_of(pt, rect, button_rects) -> str:
    """区域判定纯函数（三态）：'button'（按钮上，放行）/ 'in'（输入区）/
    'out'（窗外，零处理）。pt=(x, y)，rect=(x, y, w, h)，button_rects 同构列表。"""
    x, y = pt
    for r in button_rects or ():
        if r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]:
            return "button"
    if rect is None:
        return "out"
    rx, ry, rw, rh = rect
    if rx <= x < rx + rw and ry <= y < ry + rh:
        return "in"
    return "out"


def event_of(button_name: str) -> Event | None:
    """pynput 按键名 → 语义事件纯函数；未知按键返回 None。"""
    return _BUTTON_EVENTS.get(button_name)


def scroll_event(dy: float) -> Event:
    """滚轮方向 → 语义事件。"""
    return Event.SCROLL_UP if dy > 0 else Event.SCROLL_DOWN


class PynputHookSource(QObject):
    """P4 全局输入源：全局钩子线程采集 → 主线程区域判定与语义投递。"""

    semantic = Signal(object)   # core.events.Event（跨线程 queued → 主线程）
    toggled = Signal(bool)      # 输入会话开/关（Ctrl+Alt+M）

    def __init__(self, rect_fn, button_rects_fn, enabled_fn=None,
                 wheel_sens: int = 2):
        super().__init__()
        self._rect_fn = rect_fn                 # () -> (x,y,w,h) | None（Dock 全局逻辑矩形）
        self._button_rects_fn = button_rects_fn  # () -> [(x,y,w,h), ...]（按钮区，放行）
        self._enabled_fn = enabled_fn or (lambda: True)   # 输入会话开关
        self._wheel_sens = max(2, min(5, int(wheel_sens)))  # 格/项（D-038 档位）
        self._wheel_acc = 0.0       # 滚轮累积（pynput dy 为"格"，高分滚轮可小数）
        self._m_listener = None
        self._k_listener = None
        self._held = set()          # D-009 组合判定的按键集合
        self._started = False

    def set_wheel_sens(self, sens: int) -> None:
        """设置界面同步滚轮灵敏度（D-038 档位 2~5）。"""
        self._wheel_sens = max(2, min(5, int(sens)))

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self._started:
            return
        from pynput import keyboard, mouse
        self._m_listener = mouse.Listener(
            on_click=self._on_click, on_scroll=self._on_scroll)
        self._m_listener.daemon = True
        self._m_listener.start()
        self._k_listener = keyboard.Listener(
            on_press=self._on_key_press, on_release=self._on_key_release)
        self._k_listener.daemon = True
        self._k_listener.start()
        self._started = True

    def stop(self) -> None:
        for l in (self._m_listener, self._k_listener):
            if l is not None:
                try:
                    l.stop()
                except Exception:  # noqa: BLE001
                    pass
        self._m_listener = self._k_listener = None
        self._started = False

    # ---------- 钩子线程（只采集，不做坐标判定） ----------

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        ev = event_of(button.name)
        if ev is not None:
            self.semantic.emit(ev)       # queued → 主线程判定+解释

    def _on_scroll(self, x, y, dx, dy):
        # pynput dy 单位 = 滚轮"格"（wheelDelta/WHEEL_DELTA，高分滚轮可为小数）。
        # delta 累积器与 Qt 路径（candidate_window.wheelEvent，D-028）同构：
        # 累积满 wheel_sens 格才动一项——否则高密度滚轮一次跳多格。
        if not dy:
            return
        self._wheel_acc += dy
        while self._wheel_acc >= self._wheel_sens:
            self.semantic.emit(Event.SCROLL_UP)
            self._wheel_acc -= self._wheel_sens
        while self._wheel_acc <= -self._wheel_sens:
            self.semantic.emit(Event.SCROLL_DOWN)
            self._wheel_acc += self._wheel_sens

    def _on_key_press(self, k):
        # D-009 手写组合判定：held 集合 + 修饰键检测（Ctrl+Alt+M）
        try:
            from pynput import keyboard as kb
            self._held.add(k)
            mods = {kb.Key.ctrl, kb.Key.ctrl_l, kb.Key.ctrl_r,
                    kb.Key.alt, kb.Key.alt_l, kb.Key.alt_r, kb.Key.alt_gr}
            if any(m in self._held for m in mods) and getattr(k, "vk", None) == 77:
                self.toggled.emit(not self._enabled_fn())
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()        # 钩子线程异常必须可见（D-044 教训）

    def _on_key_release(self, k):
        self._held.discard(k)

    # ---------- 主线程（区域判定 + 语义解释；由接收方调用） ----------

    def interpret(self, ev: Event, cursor_pos) -> Event | None:
        """主线程区域判定：返回应处理的语义事件，窗外/按钮上/会话关闭返回 None。
        cursor_pos：QCursor.pos()（Qt 全局逻辑坐标，跨屏正确）。
        （独立方法以便单测；接收方槽函数调用之。）"""
        if not self._enabled_fn():
            return None
        region = region_of((cursor_pos.x(), cursor_pos.y()),
                           self._rect_fn(), self._button_rects_fn())
        if region != "in":
            return None                  # 窗外/按钮上：零处理直接放行（D-003）
        return ev
