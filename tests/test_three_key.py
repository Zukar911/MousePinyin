# -*- coding: utf-8 -*-
"""三键模式回归 —— D-049：右键=逐字退格 + 菜单自动回退 + 选韵头即上屏
（断言数据驱动：菜单顺序跟随 model.finals 的频率序，不硬编码）。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.candidate_model import CandidateModel
from core.events import Action, Event
from core.state_machine import StateMachine

MODEL = CandidateModel()
E_TAILS = [f for f in MODEL.finals("zh") if f.startswith("e")]   # ['e','eng','en']
EN_TAILS = [f for f in MODEL.finals("zh") if f.startswith("en")]  # ['eng','en']


def mk(three_key=True):
    sm = StateMachine(CandidateModel())
    sm.three_key = three_key
    return sm


def drive_zhe(sm):
    """走到 zhe 已上屏 + 韵尾菜单（当前态 e）。返回动作记录。"""
    sm.idx = sm.items.index("zh")
    sm.handle(Event.LEFT)                       # 发 zh → FINAL_HEAD
    sm.idx = sm.items.index("e")
    sm.handle(Event.LEFT)                       # 发 e → FINAL_TAIL
    return sm


class TestThreeKeyZhengFlow(unittest.TestCase):
    def setUp(self):
        self.sm = mk()
        self.model = MODEL

    def test_head_commit_sends_vowel(self):
        """选韵头 e 即上屏：SEND_LETTER('e')，进入 FINAL_TAIL 且当前态=e。"""
        sm = self.sm
        sm.idx = sm.items.index("zh")
        self.assertEqual(sm.handle(Event.LEFT), Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "zh")
        self.assertEqual(sm.items[sm.idx], "e")   # 韵头组菜单
        sm.idx = sm.items.index("e")
        act = sm.handle(Event.LEFT)
        self.assertEqual((act, sm.pending_text), (Action.SEND_LETTER, "e"))
        self.assertEqual(sm.stage.name, "FINAL_TAIL")
        self.assertEqual(sm.items, E_TAILS)       # 频率序（数据驱动）
        self.assertEqual(sm.items[sm.idx], "e")
        self.assertEqual(sm.prefix, "zhe")

    def test_retreat_walk(self):
        """右键逐字退格 + 菜单自动回退（用户 zheng 流程反向全走一遍）。"""
        sm = self.sm
        drive_zhe(sm)
        sm.idx = sm.items.index("eng")            # 选 eng → 屏上 zheng
        self.assertEqual(sm.handle(Event.LEFT), Action.SEND_LETTER)
        self.assertEqual(sm.prefix, "zheng")
        # 右键 1：退 g → zhen，菜单 = 频率序中以 en 开头者（当前 en）
        self.assertEqual(sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(sm.prefix, "zhen")
        self.assertEqual(sm.stage.name, "FINAL_TAIL")
        self.assertEqual(sm.items, EN_TAILS)
        self.assertEqual(sm.items[sm.idx], "en")
        # 右键 2：退 n → zhe，菜单 = 以 e 开头者（当前 e）
        self.assertEqual(sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(sm.prefix, "zhe")
        self.assertEqual(sm.items, E_TAILS)
        self.assertEqual(sm.items[sm.idx], "e")
        # 右键 3：退 e → zh，自动回韵头菜单
        self.assertEqual(sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(sm.prefix, "zh")
        self.assertEqual(sm.stage.name, "FINAL_HEAD")
        # 右键 4：退 h → z，自动回声母菜单（高亮 z）
        self.assertEqual(sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(sm.prefix, "z")
        self.assertEqual(sm.stage.name, "INITIAL")
        self.assertEqual(sm.items[sm.idx], "z")
        # 右键 5：退 z → 空，声母菜单
        self.assertEqual(sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(sm.prefix, "")
        self.assertEqual(sm.stage.name, "INITIAL")
        self.assertEqual(sm.idx, 0)
        # 右键 6：空档再退 = 无动作
        self.assertEqual(sm.handle(Event.RIGHT), Action.NONE)

    def test_delta_continue_and_accept(self):
        """zhe 态：选 en 补发 n 停留韵尾菜单；选当前态 = 收尾进 DONE。"""
        sm = self.sm
        drive_zhe(sm)
        sm.idx = sm.items.index("en")
        self.assertEqual(sm.handle(Event.LEFT), Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "n")
        self.assertEqual(sm.prefix, "zhen")
        self.assertEqual(sm.items, EN_TAILS)           # 过滤续接
        # 选当前态 en = 接受 zhen → DONE（无输出）
        self.assertEqual(sm.items[sm.idx], "en")
        self.assertEqual(sm.handle(Event.LEFT), Action.NONE)
        self.assertEqual(sm.stage.name, "DONE")

    def test_delta_pick_initial_after_retreat(self):
        """退进声母字母内部（z）后：选 zh 只补发 h；选 s = FIXUP 先退后发。"""
        sm = self.sm
        drive_zhe(sm)
        for _ in range(2):                        # zhe → zh → z（两步）
            sm.handle(Event.RIGHT)
        self.assertEqual(sm.stage.name, "INITIAL")
        self.assertEqual(sm.prefix, "z")
        sm.idx = sm.items.index("zh")
        self.assertEqual(sm.handle(Event.LEFT), Action.SEND_LETTER)
        self.assertEqual(sm.pending_text, "h")    # 只补发差量
        self.assertEqual(sm.prefix, "zh")
        # 再退到 z，选 s = FIXUP（退1格发 s）
        sm.handle(Event.RIGHT)
        self.assertEqual(sm.prefix, "z")
        sm.idx = sm.items.index("s")
        self.assertEqual(sm.handle(Event.LEFT), Action.FIXUP)
        self.assertEqual(sm.pending_text, "1|s")
        self.assertEqual(sm.prefix, "s")


class TestThreeKeySelectMode(unittest.TestCase):
    def test_select_right_backspace_unified(self):
        """D-055：SELECT 移除，三键模式右键在 DONE 层 = 统一逐字退格。
        进入路径：n → i（韵尾菜单）→ 左键接受当前态 i → DONE。"""
        sm = mk()
        sm.idx = sm.items.index("n")
        sm.handle(Event.LEFT)                      # 发 n → FINAL_HEAD
        sm.idx = sm.items.index("i")
        sm.handle(Event.LEFT)                      # 发 i → FINAL_TAIL（组内多项）
        self.assertEqual(sm.stage.name, "FINAL_TAIL")
        sm.idx = sm.items.index("i")               # 当前态 = 接受
        self.assertEqual(sm.handle(Event.LEFT), Action.NONE)   # 收尾 → DONE
        self.assertEqual(sm.stage.name, "DONE")
        sm.idx = 0
        act = sm.handle(Event.RIGHT)               # 统一逐字退格
        self.assertEqual(act, Action.BACKSPACE)
        self.assertEqual(sm.prefix, "n")           # 退掉韵尾 i
        self.assertEqual(sm.mode.name, "PINYIN")   # mode 恒拼字（D-055）


class TestDefaultModeUnchanged(unittest.TestCase):
    def test_default_right_backspace_unified(self):
        """D-055：三键关闭（默认）右键也 = 统一逐字退格（原切选字随
        SELECT 移除而统一，两模式右键语义一致）。"""
        sm = mk(three_key=False)
        sm.idx = sm.items.index("zh")
        sm.handle(Event.LEFT)
        self.assertEqual(sm.handle(Event.RIGHT), Action.BACKSPACE)
        self.assertEqual(sm.snapshot().stage.name, "INITIAL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
