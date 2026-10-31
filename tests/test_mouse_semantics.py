"""Dock 鼠标交互回归 —— D-033：左键 = 确认滚轮选中项，与鼠标坐标无关

1. 滚轮选中 A 后，鼠标停在 A 上按左键 → 确认 A
2. 鼠标停在未选中的 B 上按左键 → 仍确认 A（不改选、不忽略）
3. 鼠标停在空白处按左键 → 仍确认 A
4. 滚轮动画未结束（_focus 插值中）立即按左键 → 确认对象 = 逻辑选中项
5. hover 无反馈；⚙/✕/⠿ 独立控件不受影响；一次按下只确认一次
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.dock_strip import DockStrip  # noqa: E402


def make_dock(items=None, target=0.0, focus=None):
    if items is None:
        items = ["b", "p", "m", "f", "d"]
    dock = DockStrip()
    dock._items = list(items)
    dock._target = target
    dock._focus = focus if focus is not None else float(target)
    dock._u = 40.0
    dock._gap = 6.0
    dock._pad_r = 94.0
    return dock


def left_press(dock, x=145.0, y=30.0):
    """合成左键按下事件（坐标任意——确认对象与坐标无关）。"""
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    dock.mousePressEvent(ev)


class TestLeftConfirmTargetOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_confirm_on_selected_key(self):
        """滚轮选 2（A），鼠标停在 2 上按左键 → 确认 2。"""
        dock = make_dock(target=2)
        got = []
        dock.confirm_requested.connect(got.append)
        left_press(dock, 140.0, 30.0)
        self.assertEqual(got, [2])

    def test_confirm_on_unselected_key(self):
        """滚轮选 0（A），鼠标停在未选中的 3（B）上按左键 → 仍确认 0。"""
        dock = make_dock(target=0)
        got = []
        dock.confirm_requested.connect(got.append)
        left_press(dock, 170.0, 30.0)
        self.assertEqual(got, [0])

    def test_confirm_on_blank(self):
        """滚轮选 1（A），鼠标停在空白处按左键 → 仍确认 1。"""
        dock = make_dock(target=1)
        got = []
        dock.confirm_requested.connect(got.append)
        left_press(dock, 400.0, 15.0)
        self.assertEqual(got, [1])

    def test_confirm_during_animation(self):
        """滚轮动画未结束（_focus 插值中）立即左键 → 确认逻辑选中项（_target）。"""
        dock = make_dock(target=3, focus=1.2)     # 焦点还在 1.2，逻辑选中是 3
        got = []
        dock.confirm_requested.connect(got.append)
        left_press(dock, 60.0, 30.0)              # 坐标靠近 1 号（插值位置），仍确认 3
        self.assertEqual(got, [3])

    def test_single_confirm_per_press(self):
        """一次按下只确认一次；两次独立按下 = 两次确认。"""
        dock = make_dock(target=2)
        got = []
        dock.confirm_requested.connect(got.append)
        left_press(dock)                          # 一次按下
        self.assertEqual(got, [2])                # 仅一条
        left_press(dock)                          # 再次按下（独立操作）
        self.assertEqual(got, [2, 2])

    def test_no_candidates_ignored(self):
        """无候选时左键不确认。"""
        dock = make_dock(items=[], target=0)
        got = []
        dock.confirm_requested.connect(got.append)
        left_press(dock)
        self.assertEqual(got, [])

    def test_hover_removed(self):
        """hover 无反馈：无 _hover/事件/跟踪，绘制源码无 hover 分支。"""
        dock = make_dock(target=1)
        self.assertFalse(hasattr(dock, "_hover"))
        self.assertNotIn("mouseMoveEvent", DockStrip.__dict__)
        self.assertNotIn("leaveEvent", DockStrip.__dict__)
        import inspect
        src = inspect.getsource(DockStrip._draw_cap)
        self.assertNotIn("hover =", src)
        self.assertNotIn("if hover", src)
        self.assertNotIn("self._cap_rects", inspect.getsource(DockStrip))  # 命中表代码级已删
        self.assertNotIn("self._hit", inspect.getsource(DockStrip))

    def test_wheel_moves_target(self):
        """滚轮（set_target）切换选中，确认对象随之跟随。"""
        dock = make_dock(target=0)
        got = []
        dock.confirm_requested.connect(got.append)
        dock.set_target(4)
        dock._anim.stop()
        dock._focus = 4.0
        left_press(dock)
        self.assertEqual(got, [4])

    def test_buttons_isolated(self):
        """⚙/✕/⠿ 为独立控件，Dock 点击路径不触碰。"""
        dock = make_dock(target=0)
        self.assertFalse(hasattr(dock, "btn_settings"))
        self.assertFalse(hasattr(dock, "btn_close"))
        self.assertFalse(hasattr(dock, "btn_move"))
        self.assertFalse(hasattr(dock, "focus_moved"))   # 改选信号已不存在


if __name__ == "__main__":
    unittest.main(verbosity=2)
