"""调试状态框回归测试 —— D-030（offscreen 平台，FakeSink 不真发键）

验证：记录聚合（滚轮未达阈值即时记录 / 确认操作五段完整 / X2 多次退格 /
执行异常标注 / 100 条上限）、面板显示与清空、诚实声明（未确认标注）。
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.candidate_model import CandidateModel  # noqa: E402
from core.events import Action, Event  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402
from debug.debug_panel import DebugCollector, DebugPanel  # noqa: E402


class FakeSink(QObject):
    """模拟 KeyboardSink 的 executed 信号（不真发键）。"""
    executed = Signal(str, bool)

    def good(self, desc):
        self.executed.emit(desc, True)

    def bad(self, desc):
        self.executed.emit(desc, False)


class TestDebugCollector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.sink = FakeSink()
        self.panel = DebugPanel(None, lambda: "Dock(100,200) 400×80 锚点(300,200) NE160QDM")
        self.panel.show()
        self.collector = DebugCollector(self.sink, self.panel)
        self.sm = StateMachine(CandidateModel())

    def test_wheel_under_threshold_instant_record(self):
        self.collector.raw_op("滚轮 delta=-60 → 累积 -60/120 未达阈值 → 不移动、不发键",
                              instant=True)
        text = self.panel.log.toPlainText()
        self.assertIn("未达阈值", text)
        self.assertIn("无输出动作", text)

    def test_confirm_full_record(self):
        """确认声母：计划/实际/未确认声明齐备。"""
        sm = self.sm
        self.collector.raw_op("左键点击键帽[0] 'd'（已是高亮）→ 确认")
        plan = "发送字母串 'd'"
        self.collector.expect_execution(plan)
        sm.handle(Event.LEFT)
        self.sink.good("Unicode type('d') → 1 字符")
        self.collector.emit("左键点击键帽[0] 'd'", "确认当前项（声母整发）→ 进入韵头选择",
                            "INITIAL→FINAL_HEAD", plan)
        text = self.panel.log.toPlainText()
        self.assertIn("计划：发送字母串 'd'", text)
        self.assertIn("实际：Unicode type('d') → 1 字符", text)
        self.assertIn("目标接收/上屏：未确认", text)
        self.assertIn("INITIAL→FINAL_HEAD", text)

    def test_x2_backspace_times(self):
        sm = self.sm
        sm.handle(Event.LEFT)                    # z
        sm.handle(Event.LEFT)                    # h 组合并直发 → DONE
        plan = "发送 Backspace ×2"
        self.collector.expect_execution(plan)
        sm.handle(Event.X2)                      # 撤销音节 → pending_text="2"
        self.sink.good("Backspace ×2")
        self.collector.emit("侧键 X2 点击", "撤销当前音节（计划退格 ×2）",
                            "DONE→INITIAL", plan)
        text = self.panel.log.toPlainText()
        self.assertIn("Backspace ×2", text)
        self.assertIn("DONE→INITIAL", text)

    def test_failure_marked(self):
        self.collector.expect_execution("发送字母串 'd'")
        self.sink.bad("执行异常：OSError('device gone')")
        self.collector.emit("左键点击键帽[0] 'd'", "确认", "INITIAL→FINAL_HEAD",
                            "发送字母串 'd'")
        text = self.panel.log.toPlainText()
        self.assertIn("输出层报告失败", text)
        self.assertIn("OSError", text)

    def test_highlight_zero_initial_label(self):
        from debug.debug_panel import _fmt_highlight
        snap = self.sm.snapshot()
        self.sm.items = ["d", "", "sh"]
        snap = self.sm.snapshot()
        snap.idx = 1
        self.assertIn("零声母（空字符串）", _fmt_highlight(snap))

    def test_100_record_cap(self):
        for i in range(120):
            self.collector.raw_op(f"操作 {i}", instant=True)
        text = self.panel.log.toPlainText()
        self.assertIn("操作 119", text)
        self.assertNotIn("操作 0\n", text)       # 最老的被挤出

    def test_clear(self):
        self.collector.raw_op("某操作", instant=True)
        self.panel.clear_records()
        self.assertEqual(self.panel.log.toPlainText(), "")

    def test_status_uses_real_snapshot_with_composition(self):
        """D-031/D-055 集成防回归：DONE 层 IME 同步后的快照必须带
        composition 字段——demo 集成层曾因 Snapshot 缺字段而渲染崩溃。"""
        sm = self.sm
        sm.handle(Event.LEFT)                 # z -> FINAL_HEAD
        sm.handle(Event.LEFT)                 # h 组合并直发 -> DONE
        sm.update_composition("h", "COMPOSING")   # D-055：上屏后剩余同步
        snap = sm.snapshot()                  # 必须含 composition/composition_state
        self.assertEqual(snap.composition, "h")
        self.assertEqual(snap.composition_state, "COMPOSING")
        self.panel.update_status(snap, "已发键记录：zh")   # 不得抛 AttributeError


if __name__ == "__main__":
    unittest.main(verbosity=2)
