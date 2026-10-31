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
        # DONE 列表 = 选字入口 + 下一声母（整句流）
        self.assertEqual(snap.items[0], "␣ 选字")
        self.assertEqual(snap.items[1:], ["z", "f"])

    def test_x2_from_head_cancels_initial(self):
        act = self.sm.handle(Event.X2)             # 撤销声母
        self.assertEqual(act, Action.BACKSPACE)
        self.assertEqual(self.sm.pending_text, "1")
        self.assertEqual(self.sm.snapshot().stage, Stage.INITIAL)

    def test_x1_half_pinyin_to_select(self):
        act = self.sm.handle(Event.X1)             # 只拼了 z（不完整）也可选字
        self.assertIs(act, Action.NONE)
        self.assertEqual(self.sm.snapshot().mode, Mode.SELECT)


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

    def test_done_first_item_selects(self):
        self.sm.handle(Event.LEFT)                 # ␣ 选字
        self.assertEqual(self.sm.snapshot().mode, Mode.SELECT)
        self.assertEqual(self.sm.snapshot().prefix, "zh")  # 缓冲保留，由输入法出候选

    def test_done_continue_next_syllable(self):
        sm = self.sm
        sm.handle(Event.SCROLL_DOWN)               # 跳过选字，高亮 z
        act = sm.handle(Event.LEFT)                # 第二声母 z（整句流）
        self.assertEqual(act, Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "z")
        self.assertEqual(sm.snapshot().prefix, "zhz")      # 微软拼音自动分节
        self.assertEqual(sm.snapshot().stage, Stage.FINAL_HEAD)

    def test_x2_in_done_cancels_syllable(self):
        self.sm.handle(Event.X2)
        self.assertEqual(self.sm.snapshot().prefix, "")
        self.assertEqual(self.sm.snapshot().stage, Stage.INITIAL)


class TestSelectMode(unittest.TestCase):
    def setUp(self):
        self.sm = make()
        self.sm.handle(Event.LEFT)                 # z
        self.sm.handle(Event.LEFT)                 # h 组合并直发 -> DONE
        self.sm.handle(Event.LEFT)                 # ␣ 选字 -> SELECT

    def test_scroll_sends_up_down(self):
        self.assertEqual(self.sm.handle(Event.SCROLL_UP), Action.SEND_UP)
        self.assertEqual(self.sm.handle(Event.SCROLL_DOWN), Action.SEND_DOWN)

    def test_left_space_keeps_session(self):
        """D-031：确认键发出后会话保留（组合结束由 IME 反馈判定，见 end_select_session）。"""
        act = self.sm.handle(Event.LEFT)
        self.assertEqual(act, Action.SEND_SPACE)
        snap = self.sm.snapshot()
        self.assertEqual(snap.mode, Mode.SELECT)     # 仍选字（可能只消费部分音节）
        self.assertEqual(snap.prefix, "zh")          # 缓冲未清

    def test_end_select_session_resets_all(self):
        """组合结束（IME 反馈 ENDED）→ end_select_session 清空全部状态。"""
        self.sm.handle(Event.LEFT)
        self.sm.end_select_session()
        snap = self.sm.snapshot()
        self.assertEqual(snap.mode, Mode.PINYIN)
        self.assertEqual(snap.stage, Stage.INITIAL)
        self.assertEqual(snap.prefix, "")            # 整句确认完毕，全新开始
        self.assertEqual(snap.syllable, "")

    def test_right_pagedown(self):
        self.assertEqual(self.sm.handle(Event.RIGHT), Action.SEND_PAGEDOWN)

    def test_x1_back_to_pinyin_keeps_buffer(self):
        self.sm.handle(Event.X1)
        snap = self.sm.snapshot()
        self.assertEqual(snap.mode, Mode.PINYIN)
        self.assertEqual(snap.prefix, "zh")        # 缓冲保留（继续拼整句）

    def test_x2_backspace_single(self):
        act = self.sm.handle(Event.X2)
        self.assertEqual(act, Action.BACKSPACE)
        self.assertEqual(self.sm.pending_text, "")  # 单次退格（payload 空即 1 次）
        self.assertEqual(self.sm.snapshot().prefix, "z")

    def test_x2_empty_buffer_no_backspace(self):
        """D-053：缓冲删空后再 X2 不再盲发退格——防止删除目标输入框中
        用户已上屏的字符（导航键/退格落错目标的同类泄漏）。"""
        self.sm.handle(Event.X2)                    # zh → z
        act = self.sm.handle(Event.X2)              # z → ""（删掉最后一个）
        self.assertEqual(act, Action.BACKSPACE)
        self.assertEqual(self.sm.snapshot().prefix, "")
        act = self.sm.handle(Event.X2)              # 已空：不发
        self.assertEqual(act, Action.NONE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
