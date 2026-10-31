"""状态机单元测试 —— F-001 v4 行为矩阵（声母整发 + 韵母两级渐进 + 整句流 + 双模式）

运行：python -m unittest tests.test_state_machine -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.events import Action, Event, Mode, Stage  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402


class FakeModel:
    """固定数据：z→韵母[h,a,ai,ao,ang]（h 组单项合并直发；a 组四项走两级）、f→[a]。"""

    def initials(self):
        return ["z", "f"]

    def finals(self, initial):
        return {"z": ["h", "a", "ai", "ao", "ang"], "f": ["a"]}.get(initial, [])


def make():
    return StateMachine(FakeModel())


class TestInitialStage(unittest.TestCase):
    def test_initial_state(self):
        sm = make()
        snap = sm.snapshot()
        self.assertEqual(snap.mode, Mode.PINYIN)
        self.assertEqual(snap.stage, Stage.INITIAL)
        self.assertEqual(snap.prefix, "")
        self.assertEqual(snap.items, ["z", "f"])

    def test_left_sends_whole_initial(self):
        sm = make()
        sm.handle(Event.SCROLL_DOWN)               # f
        act = sm.handle(Event.LEFT)
        self.assertEqual(act, Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "f")     # 整声母一次发
        self.assertEqual(sm.snapshot().stage, Stage.FINAL_HEAD)
        self.assertEqual(sm.snapshot().syllable, "f")

    def test_zh_sends_two_letters_at_once(self):
        sm = make()
        act = sm.handle(Event.LEFT)                # z（假数据 z 单字母）
        self.assertEqual(sm.pending_text, "z")
        self.assertEqual(act, Action.SEND_LETTER)


class TestFinalHeadStage(unittest.TestCase):
    def setUp(self):
        self.sm = make()
        self.sm.handle(Event.LEFT)                 # z -> FINAL_HEAD

    def test_head_groups(self):
        # 韵头组 = 首字符分组、组内最高频排序：h(0) → a(1)
        self.assertEqual(self.sm.snapshot().items, ["h", "a"])
        self.assertEqual(self.sm.snapshot().stage, Stage.FINAL_HEAD)

    def test_single_tail_group_merges_direct_send(self):
        act = self.sm.handle(Event.LEFT)           # h 组仅 1 项 → 合并直发
        self.assertEqual(act, Action.SEND_LETTER)
        snap = self.sm.snapshot()
        self.assertEqual(snap.stage, Stage.DONE)
        self.assertEqual(snap.prefix, "zh")
        self.assertEqual(self.sm.pending_text, "h")
        # DONE 列表 = 选字入口 + 下一声母（整句流，D-057：↕选字为唯一上屏途径）
        self.assertEqual(snap.items[0], "↕ 选字")
        self.assertEqual(snap.items[1:], ["z", "f"])

    def test_x2_from_head_cancels_initial(self):
        act = self.sm.handle(Event.X2)             # 撤销声母
        self.assertEqual(act, Action.BACKSPACE)
        self.assertEqual(self.sm.pending_text, "1")
        self.assertEqual(self.sm.snapshot().stage, Stage.INITIAL)

    def test_x1_idle_any_stage(self):
        """D-055：选字模式移除后 X1 闲置（无动作、状态不变）。"""
        act = self.sm.handle(Event.X1)             # 拼了一半按 X1
        self.assertIs(act, Action.NONE)
        self.assertEqual(self.sm.snapshot().stage, Stage.FINAL_HEAD)


class TestFinalTailStage(unittest.TestCase):
    def setUp(self):
        self.sm = make()
        self.sm.handle(Event.LEFT)                 # z -> FINAL_HEAD
        self.sm.handle(Event.SCROLL_DOWN)          # 高亮 a 组
        self.sm.handle(Event.LEFT)                 # a 组 4 项 -> FINAL_TAIL

    def test_tail_items_in_freq_order(self):
        self.assertEqual(self.sm.snapshot().stage, Stage.FINAL_TAIL)
        self.assertEqual(self.sm.snapshot().items, ["a", "ai", "ao", "ang"])

    def test_left_commits_full_final(self):
        self.sm.handle(Event.SCROLL_DOWN)          # 高亮 ai
        act = self.sm.handle(Event.LEFT)
        self.assertEqual(act, Action.SEND_LETTER)
        snap = self.sm.snapshot()
        self.assertEqual(snap.stage, Stage.DONE)
        self.assertEqual(self.sm.pending_text, "ai")  # 整发完整韵母
        self.assertEqual(snap.prefix, "zai")
        self.assertEqual(snap.syllable, "zai")

    def test_x2_back_to_initial_full_display(self):
        act = self.sm.handle(Event.X2)             # 宪法 F-001：X2=撤销音节回声母层
        self.assertEqual(act, Action.BACKSPACE)
        self.assertEqual(self.sm.pending_text, "1")  # 只发过声母 z，1 次退格
        snap = self.sm.snapshot()
        self.assertEqual(snap.stage, Stage.INITIAL)
        self.assertEqual(snap.prefix, "")
        self.assertEqual(snap.items, ["z", "f"])     # 声母层全显


class TestDoneStage(unittest.TestCase):
    def setUp(self):
        self.sm = make()
        self.sm.handle(Event.LEFT)                 # z
        self.sm.handle(Event.LEFT)                 # h 组单项合并直发 -> DONE (prefix "zh")

    def test_done_first_item_select(self):
        """D-057：DONE 首项 = ↕选字（唯一上屏途径），左键进入候选导航。"""
        act = self.sm.handle(Event.LEFT)           # ↕ 选字
        self.assertIs(act, Action.NONE)
        self.assertEqual(self.sm.snapshot().mode, Mode.SELECT)
        self.assertEqual(self.sm.snapshot().prefix, "zh")  # 缓冲保留，由输入法出候选

    def test_done_continue_next_syllable(self):
        sm = self.sm
        sm.handle(Event.SCROLL_DOWN)               # 高亮 z（跳过 ↕ 选字）
        act = sm.handle(Event.LEFT)                # 第二声母 z（整句流）
        self.assertEqual(act, Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "z")
        self.assertEqual(sm.snapshot().prefix, "zhz")      # 微软拼音自动分节
        self.assertEqual(sm.snapshot().stage, Stage.FINAL_HEAD)

    def test_x2_in_done_cancels_syllable(self):
        self.sm.handle(Event.X2)
        self.assertEqual(self.sm.snapshot().prefix, "")
        self.assertEqual(self.sm.snapshot().stage, Stage.INITIAL)


class TestDoneImeSync(unittest.TestCase):
    """D-057：上屏只经 ↕选字 → SELECT；IME 反馈在 SELECT 态三分支。"""

    def setUp(self):
        self.sm = make()
        self.sm.handle(Event.LEFT)                 # z → FINAL_HEAD
        self.sm.handle(Event.LEFT)                 # h 组单项直发 → DONE (zh)
        self.sm.handle(Event.LEFT)                 # ↕选字 → SELECT

    def test_space_then_ended_resets(self):
        self.assertIs(self.sm.handle(Event.LEFT), Action.SEND_SPACE)
        self.sm.update_composition(None, "ENDED")
        snap = self.sm.snapshot()
        self.assertEqual(snap.stage, Stage.INITIAL)
        self.assertEqual(snap.prefix, "")            # 整句确认完毕，全新开始

    def test_space_then_composing_keeps_select(self):
        self.assertIs(self.sm.handle(Event.LEFT), Action.SEND_SPACE)
        # 微软拼音分段消费：zh 部分上屏、剩余 "z" → 留选字同步显示
        self.sm.update_composition("z", "COMPOSING")
        snap = self.sm.snapshot()
        self.assertEqual(snap.mode, Mode.SELECT)
        self.assertEqual(snap.items[0], "选字 ▸ z")

    def test_space_then_unknown_x2_auto_exit(self):
        self.assertIs(self.sm.handle(Event.LEFT), Action.SEND_SPACE)
        self.sm.update_composition(None, "UNKNOWN")
        self.assertEqual(self.sm.mode, Mode.SELECT)  # 第 1 次：保守留
        self.sm.update_composition(None, "UNKNOWN")
        self.assertEqual(self.sm.mode, Mode.PINYIN)  # 第 2 次：自动回声母层
        self.assertEqual(self.sm.snapshot().stage, Stage.INITIAL)

    def test_right_backspace_unified(self):
        """D-056：右键统一逐字退格（两种模式一致）。"""
        act = self.sm.handle(Event.RIGHT)            # SELECT 态右键
        self.assertEqual(act, Action.BACKSPACE)

    def test_x1_back_to_pinyin(self):
        """SELECT 态 X1 = 回拼字（缓冲保留）。"""
        self.assertIs(self.sm.handle(Event.X1), Action.NONE)
        self.assertEqual(self.sm.mode, Mode.PINYIN)
        self.assertEqual(self.sm.prefix, "zh")

    def test_x2_empty_buffer_no_backspace(self):
        """D-053：选字态逐字退格删空 → 自动回声母层；已空再按不发。"""
        self.sm.handle(Event.X2)                    # zh → z
        self.sm.handle(Event.X2)                    # z → ""（删空回声母层）
        self.assertEqual(self.sm.snapshot().prefix, "")
        self.assertEqual(self.sm.snapshot().stage, Stage.INITIAL)
        act = self.sm.handle(Event.X2)              # 已空：不发
        self.assertEqual(act, Action.NONE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
