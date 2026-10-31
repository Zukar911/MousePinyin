"""tests/test_pynput_source.py —— T-014 全局输入源纯函数与区域判定单测

不起 pynput Listener（钩子行为由 spikes/spike_global_hook.py 真桌面验证，
7/7 PASS）；本文件覆盖主线程侧纯逻辑：区域三态 / 按键映射 / 滚轮方向 /
interpret 判定链（会话开关 / 窗外零处理 / 按钮放行）。
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint

from core.events import Event
from io_source.pynput_source import (PynputHookSource, event_of, region_of,
                                     scroll_event)

RECT = (100, 200, 400, 80)
BTN = [(420, 210, 26, 26)]      # ⚙ 按钮区（rect 内右侧）


class TestRegionOf(unittest.TestCase):
    def test_in(self):
        self.assertEqual(region_of((100, 200), RECT, BTN), "in")
        self.assertEqual(region_of((300, 279), RECT, BTN), "in")   # 下边界内

    def test_out(self):
        self.assertEqual(region_of((99, 200), RECT, BTN), "out")   # 左界外
        self.assertEqual(region_of((300, 280), RECT, BTN), "out")  # 下界外
        self.assertEqual(region_of((300, 100), None, BTN), "out")  # 无 rect

    def test_button_zone_inside_rect(self):
        # 按钮在 rect 内：优先判定为 button（放行），不是 in
        self.assertEqual(region_of((430, 220), RECT, BTN), "button")


class TestEventOf(unittest.TestCase):
    def test_mapping(self):
        # spike 教训：pynput button.name 是 'left'/'right'/'x1'/'x2'
        self.assertIs(event_of("left"), Event.LEFT)
        self.assertIs(event_of("right"), Event.RIGHT)
        self.assertIs(event_of("x1"), Event.X1)
        self.assertIs(event_of("x2"), Event.X2)

    def test_unknown(self):
        self.assertIsNone(event_of("middle"))
        self.assertIsNone(event_of("nope"))


class TestScrollEvent(unittest.TestCase):
    def test_direction(self):
        self.assertIs(scroll_event(120), Event.SCROLL_UP)
        self.assertIs(scroll_event(-120), Event.SCROLL_DOWN)
        self.assertIs(scroll_event(0.0001), Event.SCROLL_UP)


def make_source(enabled=True):
    state = {"on": enabled}
    src = PynputHookSource(lambda: RECT, lambda: BTN,
                           enabled_fn=lambda: state["on"])
    return src, state


def btn(name):
    """构造 button mock：pynput Button 的 .name 是普通属性（Mock(name=) 是
    Mock 自身命名参数而非属性值，经典陷阱）。"""
    b = mock.Mock()
    b.name = name
    return b


class TestInterpret(unittest.TestCase):
    """主线程判定链：interpret(ev, cursor_pos)（不起钩子线程）。"""

    def test_inside_delivers(self):
        src, _ = make_source()
        self.assertIs(src.interpret(Event.LEFT, QPoint(300, 240)), Event.LEFT)
        self.assertIs(src.interpret(Event.SCROLL_UP, QPoint(101, 201)),
                      Event.SCROLL_UP)

    def test_outside_zero_processing(self):
        src, _ = make_source()
        self.assertIsNone(src.interpret(Event.LEFT, QPoint(50, 240)))
        self.assertIsNone(src.interpret(Event.SCROLL_DOWN, QPoint(300, 500)))

    def test_button_zone_pass_through(self):
        src, _ = make_source()
        self.assertIsNone(src.interpret(Event.LEFT, QPoint(430, 220)))

    def test_disabled_session(self):
        src, _ = make_source(enabled=False)
        self.assertIsNone(src.interpret(Event.LEFT, QPoint(300, 240)))

    def test_hook_thread_emits_and_interpret_chain(self):
        # 模拟钩子线程 emit → 主线程 interpret 全链（不启动真 Listener）
        src, _ = make_source()
        received = []
        src.semantic.connect(lambda ev: received.append(
            src.interpret(ev, QPoint(300, 240))))
        src._on_click(300, 240, btn("left"), True)
        self.assertEqual(received, [Event.LEFT])
        # 未按下的释放事件不投递
        src._on_click(300, 240, btn("left"), False)
        self.assertEqual(len(received), 1)
        # 未知按键不投递
        src._on_click(300, 240, btn("middle"), True)
        self.assertEqual(len(received), 1)

    def test_key_toggle_emits(self):
        src, state = make_source()
        states = []
        src.toggled.connect(states.append)
        src.toggled.connect(lambda on: state.__setitem__("on", on))  # 接回状态
        # 合成键对象：vk=77（M）且修饰键在 held 集合
        from pynput import keyboard as kb
        src._held.add(kb.Key.ctrl)
        src._held.add(kb.Key.alt)
        m_key = mock.Mock(vk=77)
        src._on_key_press(m_key)
        self.assertEqual(states, [False])   # enabled=True → toggle 为 False
        self.assertIsNone(src.interpret(Event.LEFT, QPoint(300, 240)))
        # 再按恢复
        src._on_key_press(m_key)
        self.assertEqual(states, [False, True])
        # 非 M 键不触发
        q_key = mock.Mock(vk=81)
        src._on_key_press(q_key)
        self.assertEqual(states, [False, True])
        # 无修饰键不触发
        src._held.clear()
        src._on_key_press(m_key)
        self.assertEqual(states, [False, True])


class TestWheelAccumulator(unittest.TestCase):
    """钩子源滚轮 delta 累积（与 Qt 路径 D-028 同构；高分滚轮小数格）。"""

    def test_accumulates_to_sens(self):
        src, _ = make_source()
        seen = []
        src.semantic.connect(seen.append)
        src._wheel_sens = 2
        for _ in range(3):                  # 3 个小数格（高分滚轮 dy=1 累积）
            src._on_scroll(0, 0, 0, 1.0)
        self.assertEqual(seen, [Event.SCROLL_UP])   # 满 2 格才动一项

    def test_down_direction(self):
        src, _ = make_source()
        seen = []
        src.semantic.connect(seen.append)
        src._wheel_sens = 2
        src._on_scroll(0, 0, 0, -2.0)
        self.assertEqual(seen, [Event.SCROLL_DOWN])

    def test_fractional_deltas(self):
        src, _ = make_source()
        seen = []
        src.semantic.connect(seen.append)
        src._wheel_sens = 2
        for _ in range(4):                  # 4×0.5 = 2 格 → 一项
            src._on_scroll(0, 0, 0, 0.5)
        self.assertEqual(seen, [Event.SCROLL_UP])

    def test_sens_clamped(self):
        src, _ = make_source()
        src.set_wheel_sens(1)               # D-038：第一档 = 2
        self.assertEqual(src._wheel_sens, 2)
        src.set_wheel_sens(9)
        self.assertEqual(src._wheel_sens, 5)


if __name__ == "__main__":
    unittest.main()
