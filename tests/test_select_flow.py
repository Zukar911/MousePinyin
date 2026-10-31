"""整句流上屏回归 —— D-055（选字菜单层移除：「␣ 上屏」直接发空格 + IME 反馈同步）

场景：nihao（DONE 层）→ ␣上屏 → COMPOSING（剩余组合）prefix 同步重derive
继续拼 / ENDED 清空回声母层 / UNKNOWN 保守保持。
覆盖 update_composition 新语义、分段流、_pick_tail 接受当前态。
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.candidate_model import CandidateModel  # noqa: E402
from core.events import Action, Event, Mode, Stage  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402
from io_sink.ime_feedback import (COMPOSING, ENDED, UNKNOWN,  # noqa: E402
                                  match_composition)


class FakeIME:
    """注入式组合状态查询（替代真实跨进程读取）。"""

    def __init__(self):
        self.state = UNKNOWN
        self.remaining = None

    def set(self, state, remaining=None):
        self.state, self.remaining = state, remaining

    def __call__(self, prefix):
        return self.state, self.remaining


def apply_confirm_result(sm, ime: FakeIME):
    """复刻 demo_main 上屏反馈分支（可注入查询）。"""
    state, remaining = ime(sm.prefix)
    sm.update_composition(remaining, state)


def make_done(prefix: str = "nihao", syllable: str = "hao") -> StateMachine:
    sm = StateMachine(CandidateModel())
    sm.mode = Mode.PINYIN
    sm.prefix = prefix
    sm.syllable = syllable
    sm.syllable_start = len(prefix) - len(syllable)
    sm.stage = Stage.DONE
    sm._refresh_items()
    return sm


class TestDoneScreen(unittest.TestCase):
    """DONE 层「↕ 选字」= 唯一上屏途径（D-057：直达上屏已移除）。"""

    def test_first_item_is_select(self):
        sm = make_done()
        self.assertEqual(sm.items[0], "↕ 选字")

    def test_left_on_select_enters_select(self):
        sm = make_done()
        sm.idx = 0
        act = sm.handle(Event.LEFT)
        self.assertIs(act, Action.NONE)
        self.assertEqual(sm.mode, Mode.SELECT)
        self.assertEqual(sm.items[0], "选字 ▸ nihao")

    def test_left_on_initial_continues_flow(self):
        sm = make_done()
        sm.idx = sm.items.index("d")                    # 下一声母（整句流）
        act = sm.handle(Event.LEFT)
        self.assertEqual(act, Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "d")

    def test_right_backspace_in_done(self):
        sm = make_done()
        act = sm.handle(Event.RIGHT)                    # 统一逐字退格
        self.assertEqual(act, Action.BACKSPACE)

    def test_x1_idle(self):
        sm = make_done()
        self.assertIs(sm.handle(Event.X1), Action.NONE)


class TestCompositionSync(unittest.TestCase):
    """IME 反馈 → update_composition（v7：上屏只发生在 SELECT，按模式分流）。"""

    def setUp(self):
        self.sm = make_done("nihao", "hao")

    def test_composing_keeps_select_and_syncs(self):
        """上屏'你'消费 ni → 剩余 hao → 留选字并同步显示（不重derive 拼字层）。"""
        self.sm.idx = 0
        self.sm.handle(Event.LEFT)                      # ↕选字 → SELECT
        self.sm.handle(Event.LEFT)                      # SEND_SPACE
        ime = FakeIME(); ime.set(COMPOSING, "hao")
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.SELECT)
        self.assertEqual(self.sm.items[0], "选字 ▸ hao")

    def test_ended_resets_to_initial(self):
        """整句一次上屏 → ENDED → 清会话回声母层。"""
        self.sm.idx = 0
        self.sm.handle(Event.LEFT)                      # ↕选字
        self.sm.handle(Event.LEFT)                      # SEND_SPACE
        ime = FakeIME(); ime.set(ENDED, None)
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.PINYIN)
        self.assertEqual(self.sm.stage, Stage.INITIAL)
        self.assertEqual(self.sm.prefix, "")
        self.assertEqual(self.sm.items, list(self.sm.model.initials()))

    def test_unknown_x2_auto_exit(self):
        """连续 2 次 UNKNOWN → 自动回声母层（防滞留）。"""
        self.sm.idx = 0
        self.sm.handle(Event.LEFT)                      # ↕选字
        self.sm.handle(Event.LEFT)                      # SEND_SPACE
        ime = FakeIME(); ime.set(UNKNOWN, None)
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.SELECT)     # 第 1 次：保守留
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.PINYIN)     # 第 2 次：自动回

    def test_segmented_flow_via_select(self):
        """nihao → ↕选字 → 上屏'你'（剩 hao，留选字）→ 上屏'好'（ENDED
        → 回声母层）。全链经唯一上屏途径，无卡点。"""
        sm = self.sm
        sm.idx = 0
        sm.handle(Event.LEFT)                           # ↕选字 → SELECT
        sm.handle(Event.LEFT)                           # SPACE：上屏'你'
        ime = FakeIME(); ime.set(COMPOSING, "hao")
        apply_confirm_result(sm, ime)
        self.assertEqual(sm.mode, Mode.SELECT)
        self.assertEqual(sm.items[0], "选字 ▸ hao")
        sm.handle(Event.LEFT)                           # SPACE：上屏'好'
        ime.set(ENDED, None)
        apply_confirm_result(sm, ime)
        self.assertEqual(sm.mode, Mode.PINYIN)
        self.assertEqual(sm.stage, Stage.INITIAL)
        self.assertEqual(sm.prefix, "")

    def test_x1_back_to_pinyin_after_partial(self):
        """分段上屏后 X1 回拼字：按剩余重derive（hao → 韵尾层当前态 ao）
        继续拼（整句流）。"""
        sm = self.sm
        sm.idx = 0
        sm.handle(Event.LEFT)                           # ↕选字
        sm.handle(Event.LEFT)                           # SPACE
        ime = FakeIME(); ime.set(COMPOSING, "hao")
        apply_confirm_result(sm, ime)
        self.assertIs(sm.handle(Event.X1), Action.NONE)  # 回拼字
        self.assertEqual(sm.mode, Mode.PINYIN)
        self.assertEqual(sm.prefix, "hao")               # 剩余同步
        self.assertEqual(sm.stage, Stage.FINAL_TAIL)
        self.assertEqual(sm.items, ["ao"])               # 当前态在韵尾菜单
        sm.idx = 0
        self.assertIs(sm.handle(Event.LEFT), Action.NONE)  # 接受当前态 → DONE
        self.assertEqual(sm.stage, Stage.DONE)


class TestSelectRestored(unittest.TestCase):
    """D-056 选字模式恢复：↕选字入口 / 候选导航 / UNKNOWN×2 防滞留。"""

    def setUp(self):
        self.sm = make_done("jian", "jian")

    def _enter_select(self):
        self.sm.idx = self.sm.items.index("↕ 选字")
        self.assertIs(self.sm.handle(Event.LEFT), Action.NONE)
        self.assertEqual(self.sm.mode, Mode.SELECT)

    def test_entry_and_navigation(self):
        self._enter_select()
        self.assertEqual(self.sm.items[0], "选字 ▸ jian")
        self.assertIs(self.sm.handle(Event.SCROLL_UP), Action.SEND_UP)
        self.assertIs(self.sm.handle(Event.SCROLL_DOWN), Action.SEND_DOWN)
        self.assertIs(self.sm.handle(Event.LEFT), Action.SEND_SPACE)

    def test_composing_keeps_select_and_syncs_display(self):
        """上屏'键'消费 jian 部分 → 剩余 an → 留选字并同步显示（不重derive）。"""
        self._enter_select()
        self.sm.handle(Event.LEFT)                       # SEND_SPACE
        ime = FakeIME(); ime.set(COMPOSING, "an")
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.SELECT)      # 留在选字
        self.assertEqual(self.sm.stage, Stage.DONE)      # stage 不被重derive
        self.assertEqual(self.sm.items[0], "选字 ▸ an")

    def test_ended_back_to_initial(self):
        self._enter_select()
        self.sm.handle(Event.LEFT)
        ime = FakeIME(); ime.set(ENDED, None)
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.PINYIN)
        self.assertEqual(self.sm.stage, Stage.INITIAL)

    def test_unknown_x2_auto_exit(self):
        """连续 2 次 UNKNOWN → 自动回声母层（D-056 卡死根治）。"""
        self._enter_select()
        self.sm.handle(Event.LEFT)
        ime = FakeIME(); ime.set(UNKNOWN, None)
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.SELECT)      # 第 1 次：保守留
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.PINYIN)      # 第 2 次：自动回
        self.assertEqual(self.sm.stage, Stage.INITIAL)

    def test_right_backspace_until_empty_exits(self):
        """选字态右键逐字退格：jian→ian→an→n→空 → 自动回声母层。"""
        self._enter_select()
        for _ in range(4):
            self.assertEqual(self.sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(self.sm.prefix, "")
        act = self.sm.handle(Event.RIGHT)                # 已空 → 回声母层
        self.assertEqual(self.sm.mode, Mode.PINYIN)
        self.assertEqual(self.sm.stage, Stage.INITIAL)

    def test_x1_back_to_pinyin_keeps_buffer(self):
        self._enter_select()
        self.assertIs(self.sm.handle(Event.X1), Action.NONE)
        self.assertEqual(self.sm.mode, Mode.PINYIN)
        self.assertEqual(self.sm.prefix, "jian")         # 缓冲保留


class TestMatchComposition(unittest.TestCase):
    def test_composing_tail(self):
        state, rem = match_composition("nihaozhongguo", "你好 zhongguo")
        self.assertEqual(state, COMPOSING)
        self.assertEqual(rem, "zhongguo")

    def test_composing_partial_with_apostrophe(self):
        state, rem = match_composition("nihaozhongguo", "…文本…zhong'guo")
        self.assertEqual(state, COMPOSING)
        self.assertEqual(rem, "zhongguo")

    def test_ended(self):
        state, rem = match_composition("nihaozhongguo", "你好中国")
        self.assertEqual((state, rem), (ENDED, None))

    def test_unknown_no_text(self):
        self.assertEqual(match_composition("nihao", None), (UNKNOWN, None))

    def test_unknown_empty_prefix(self):
        self.assertEqual(match_composition("", "随便什么"), (UNKNOWN, None))


if __name__ == "__main__":
    unittest.main()
