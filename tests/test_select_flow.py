"""多音节分段选字回归测试 —— D-031（发确认键 ≠ 组合结束）

场景：nihaozhongguo → 选"你好" → 选"中" → 选"国" → 回声母层。
覆盖：确认后保持 SELECT / IME 反馈分支（COMPOSING/ENDED/UNKNOWN）/ 判定纯函数。
"""

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
    """复刻 demo_main.ime_feedback_check 的分支（可注入查询）。"""
    state, remaining = ime(sm.prefix)
    sm.update_composition(remaining, state)
    if state == ENDED:
        sm.end_select_session()


class TestSelectKeepsSession(unittest.TestCase):
    def setUp(self):
        self.sm = StateMachine(CandidateModel())
        # 走到 SELECT（真数据：d→a组→a 等；直接构造简单路径）
        self.sm.mode = Mode.SELECT
        self.sm.prefix = "nihaozhongguo"
        self.sm.stage = Stage.DONE
        self.sm.items = [self.sm.prefix or "选字"]

    def test_left_does_not_reset(self):
        """确认键发出后会话保留（旧实现在此清空 → 分段选字断裂）。"""
        act = self.sm.handle(Event.LEFT)
        self.assertEqual(act, Action.SEND_SPACE)
        self.assertEqual(self.sm.mode, Mode.SELECT)      # 仍选字
        self.assertEqual(self.sm.prefix, "nihaozhongguo")  # 缓冲未清
        self.assertNotEqual(self.sm.stage, Stage.INITIAL or self.sm.stage)

    def test_partial_confirm_keeps_select(self):
        """选'你好'（只消费部分音节）→ 保持 SELECT 继续选字。"""
        self.sm.handle(Event.LEFT)                       # 确认键
        ime = FakeIME(); ime.set(COMPOSING, "zhongguo")
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.SELECT)
        self.assertIn("zhongguo", self.sm.items[0])      # Dock 显示读回的剩余

    def test_whole_sentence_confirm_ends(self):
        """整句候选一次确认 → ENDED → 回声母层。"""
        self.sm.handle(Event.LEFT)
        ime = FakeIME(); ime.set(ENDED, None)
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.PINYIN)
        self.assertEqual(self.sm.stage, Stage.INITIAL)
        self.assertEqual(self.sm.prefix, "")
        self.assertEqual(self.sm.items[0], "d")          # 声母层（频率首项）

    def test_unknown_keeps_session_no_fake_reset(self):
        """读取失败 → 标记未知、保留会话、不清空（不冒充、不补发）。"""
        self.sm.handle(Event.LEFT)
        ime = FakeIME(); ime.set(UNKNOWN, None)
        apply_confirm_result(self.sm, ime)
        self.assertEqual(self.sm.mode, Mode.SELECT)
        self.assertIn("（组合未知）", self.sm.items[0])   # 明确标注未知
        self.assertEqual(self.sm.prefix, "nihaozhongguo")

    def test_segmented_flow_full(self):
        """nihaozhongguo → 选'你好' → 选'中' → 选'国'（分段确认全流程）。"""
        sm = self.sm
        sm.handle(Event.LEFT)
        ime = FakeIME(); ime.set(COMPOSING, "zhongguo")
        apply_confirm_result(sm, ime)
        self.assertEqual(sm.mode, Mode.SELECT)
        # 继续选字：再确认一次（选"中"）
        sm.handle(Event.LEFT)
        ime.set(COMPOSING, "guo")
        apply_confirm_result(sm, ime)
        self.assertEqual(sm.mode, Mode.SELECT)
        self.assertIn("guo", sm.items[0])
        # 最后一次确认 → 组合结束
        sm.handle(Event.LEFT)
        ime.set(ENDED, None)
        apply_confirm_result(sm, ime)
        self.assertEqual(sm.mode, Mode.PINYIN)
        self.assertEqual(sm.prefix, "")
        self.assertEqual(sm.items, list(sm.model.initials())[: len(sm.items)])

    def test_end_select_session_direct(self):
        """显式结束接口：清空全部会话状态。"""
        sm = self.sm
        sm.handle(Event.LEFT)
        sm.end_select_session()
        self.assertEqual(sm.mode, Mode.PINYIN)
        self.assertEqual((sm.prefix, sm.syllable, sm.syllable_start), ("", "", 0))
        self.assertEqual(sm.composition, None)


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
    unittest.main(verbosity=2)
