"""core/state_machine.py —— 双模式状态机 v4（D-024：韵母两级渐进 + 整句流）

PINYIN 拼字模式（声母整发 + 韵母两级 + 整句流）：
  INITIAL     选声母（24 项整发，如 zh = 一次发 z,h 两键）
  FINAL_HEAD  选韵头组（a/o/e/i/u/ü，仅该声母下有效的组，≤6 项）——不发键
  FINAL_TAIL  选该组下韵母（≤10 项，频率降序）→ 1 次确认整发完整韵母
              组内仅 1 项时自动合并（选组即发，保持快捷）
  DONE        音节完成：items = ["␣ 选字"] + 声母列表 —— 首项选字（单字流），其余继续拼
              （微软拼音自动分节 zhong|guo，整句候选由输入法引擎给出 = 联想性恢复）
  X1/RIGHT = 切选字（任何时候，含拼一半）
  X2 = 撤销：FINAL_TAIL→回 FINAL_HEAD（韵母未发不退格）；其余=撤销当前音节（退格回边界）

SELECT 选字模式：滚轮 = ↑↓ 候选高亮、左键 = 空格上屏（整句/词/字由输入法定）、
  右键 = PgDn 翻页、X1 = 回拼字、X2 = 退格删拼音字母。

行为矩阵以 01 §4（v4）为规范；纯逻辑，键盘模拟由 KeyboardSink 主线程执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.events import Action, Event, Mode, Stage


@dataclass
class Snapshot:
    """UI 渲染快照。"""
    mode: Mode
    stage: Stage
    prefix: str            # 整句拼音缓冲（发出去的全部字母）
    syllable: str          # 当前音节（拼字中的）
    items: list            # 当前建议列表
    idx: int               # 高亮索引
    context: str           # 状态栏文本
    composition: str | None = None     # D-031：读回的组合剩余（None=未知/未读）
    composition_state: str = "UNKNOWN"  # COMPOSING / ENDED / UNKNOWN


def _head_of(final: str) -> str:
    """韵母 → 韵头组键：首字符（a/o/e/i/u/v；er→e，ai→a，ia→i）。"""
    return final[:1]


class StateMachine:
    def __init__(self, model):
        """model 接口：initials() -> list[str]；finals(initial) -> list[str]（频率降序）。"""
        self.model = model
        self._tails: list[str] = []   # FINAL_TAIL 层的候选（韵母，频率序）
        self.three_key = False        # D-049 三键模式（无侧键：右键=逐字退格）
        self.reset()

    def reset(self) -> None:
        self.mode = Mode.PINYIN
        self.stage = Stage.INITIAL
        self.prefix = ""          # 整句缓冲
        self.syllable = ""        # 当前音节
        self.syllable_start = 0   # 当前音节在 prefix 中的起始（X2 撤销用）
        self.pending_text = ""    # 最近待发内容（字母串/退格次数）
        self.composition: str | None = None   # D-031：读回的组合剩余（None=未知/未读）
        self.composition_state = "UNKNOWN"    # COMPOSING/ENDED/UNKNOWN
        self._refresh_items()
        self.idx = 0

    # ---------- 内部 ----------

    def _grouped_finals(self, ini: str) -> list[tuple[str, list[str]]]:
        """韵母按韵头分组 → [(组键, [韵母…频率序])]，按组内最高频位次排序。"""
        finals = self.model.finals(ini)
        groups: dict[str, list[str]] = {}
        for f in finals:
            groups.setdefault(_head_of(f), []).append(f)
        # 组序 = 组内最高频韵母在 finals 中的位次
        order = sorted(groups.items(), key=lambda kv: finals.index(kv[1][0]))
        return order

    def _refresh_items(self) -> None:
        if self.stage is Stage.INITIAL:
            self.items = list(self.model.initials())
        elif self.stage is Stage.FINAL_HEAD:
            self.items = [head for head, _ in self._grouped_finals(self.syllable)]
        elif self.stage is Stage.FINAL_TAIL:
            self.items = list(self._tails)
        else:  # DONE：选字入口 + 下一声母（整句流）
            self.items = ["␣ 选字"] + list(self.model.initials())
        self.idx = 0

    def _switch_select(self) -> None:
        self.mode = Mode.SELECT
        self.items = [self._select_display()]
        self.idx = 0

    def _select_display(self) -> str:
        """选字模式 Dock 显示：读回的组合剩余（可信）或原缓冲+未知标注（D-031）。"""
        if self.composition is not None:
            return self.composition
        if self.composition_state == "UNKNOWN" and self.prefix:
            return f"{self.prefix}（组合未知）"
        return self.prefix or "选字"

    # ---------- 选字会话（D-031：发确认键 ≠ 组合结束） ----------

    def update_composition(self, remaining: str | None, state: str) -> None:
        """IME 状态读回后同步：remaining 可信则更新显示；UNKNOWN 保留原缓冲+标注。"""
        self.composition = remaining
        self.composition_state = state
        if self.mode is Mode.SELECT:
            self.items = [self._select_display()]
            self.idx = 0

    def end_select_session(self) -> None:
        """组合确认结束：清空会话回声母层（仅由 ENDED/显式结束调用，不在发键前）。"""
        self.mode = Mode.PINYIN
        self.stage = Stage.INITIAL
        self.prefix = ""
        self.syllable = ""
        self.syllable_start = 0
        self.composition = None
        self.composition_state = "UNKNOWN"
        self._refresh_items()
        self.idx = 0

    def _cancel_syllable(self) -> Action:
        """撤销当前音节：发 len(syllable) 次退格，回 INITIAL。"""
        if not self.syllable:
            return Action.NONE
        self.pending_text = str(len(self.syllable))
        self.prefix = self.prefix[: self.syllable_start]
        self.syllable = ""
        self.syllable_start = len(self.prefix)
        self.stage = Stage.INITIAL
        self._refresh_items()
        self.idx = 0
        return Action.BACKSPACE

    # ---------- 三键模式（D-049：右键=逐字退格 + 前缀重建 + delta 发送） ----------

    def _longest_initial(self, p: str) -> str:
        """p 的最长合法声母前缀（零声母空串除外）。"""
        best = ""
        for ini in self.model.initials():
            if ini and p.startswith(ini) and len(ini) > len(best):
                best = ini
        return best

    def _initial_index(self, syl: str) -> int:
        """声母菜单中高亮与 syl 前缀匹配的项（无则 0）。"""
        for i, it in enumerate(self.items):
            if it and syl.startswith(it):
                return i
        return 0

    def _rederive_from_prefix(self, prev_stage: Stage) -> None:
        """三键模式：按当前 prefix 重建 stage/syllable/items/idx。
        规则（用户二十三轮 zheng 撤退流程定案）：
          音节段为空且 prefix 非空 → 前序音节完整 → DONE（␣选字+声母）；
          音节段只剩声母（zh）→ 韵头组菜单；但若是**从韵头组/声母菜单退进
          声母字母内部**（删 h 得 z）→ 声母菜单（高亮可续声母）；
          音节段 = 声母+韵头或更长（zhe/zhen）→ FINAL_TAIL（组内以已打韵尾
          开头者，rest 自身=当前态，左键=接受完成）。
        组合状态字段复位（采样/读回语义随退格失效）。"""
        self.composition = None
        self.composition_state = "UNKNOWN"
        p = self.prefix
        syl = p[self.syllable_start:] if self.syllable_start <= len(p) else p
        if not syl:
            # 音节段删空：前面还有完整音节 → DONE；全空 → 声母菜单
            if p:
                self.stage = Stage.DONE
                self.syllable = ""
                self._refresh_items()
                self.idx = 0
            else:
                self.stage = Stage.INITIAL
                self.syllable = ""
                self.syllable_start = 0
                self._refresh_items()
                self.idx = 0
            return
        ini = self._longest_initial(syl)
        if not ini:
            self.stage = Stage.INITIAL
            self.syllable = ""
            self.syllable_start = len(p)
            self._refresh_items()
            self.idx = 0
            return
        rest = syl[len(ini):]
        self.syllable = ini
        if not rest:
            if prev_stage in (Stage.FINAL_HEAD, Stage.INITIAL):
                # 退进了声母字母内部 → 声母菜单（高亮可续声母）
                # 注意：syllable_start **保持不动**——已打的声母字母属于
                # 正在重选的音节，delta 发送要以它为基准（D-049）
                self.stage = Stage.INITIAL
                self.syllable = ""
                self._refresh_items()
                self.idx = self._initial_index(syl)
            else:
                # 删掉了整个韵母 → 韵头组菜单
                self.stage = Stage.FINAL_HEAD
                self._refresh_items()
                self.idx = 0
            return
        head = rest[0]
        tails = [f for f in self.model.finals(ini)
                 if f.startswith(rest) and f[:1] == head]
        if not tails:
            self.stage = Stage.INITIAL
            self.syllable = ""
            self.syllable_start = len(p)
            self._refresh_items()
            self.idx = self._initial_index(syl)
            return
        self.stage = Stage.FINAL_TAIL
        self._tails = tails
        self.items = list(tails)
        self.idx = tails.index(rest) if rest in tails else 0

    def _three_key_backspace(self) -> Action:
        """三键模式右键（拼字各态）：退**一个字母** + 前缀重建（D-049 全局确认）。"""
        if not self.prefix:
            return Action.NONE
        prev = self.stage
        self.pending_text = "1"
        self.prefix = self.prefix[:-1]
        if self.syllable_start > len(self.prefix):
            self.syllable_start = len(self.prefix)
        self._rederive_from_prefix(prev)
        return Action.BACKSPACE

    def _three_key_select_backspace(self) -> Action:
        """三键模式选字态退格：同 X2 语义（删一个拼音字母）；删空回拼字声母层。"""
        if self.prefix:
            self.prefix = self.prefix[:-1]
            self.pending_text = "1"
            self._rederive_from_prefix(Stage.DONE)
            if not self.prefix:
                self.end_select_session()
            return Action.BACKSPACE
        self.end_select_session()
        return Action.BACKSPACE

    def _three_key_pick_initial(self, target: str) -> Action:
        """三键 INITIAL 确认声母：与句内已打字母做 delta 校正——
        syl 是 target 前缀（z→zh）只补发差量；分叉（z→s）先退后发（FIXUP）。"""
        syl = self.prefix[self.syllable_start:]
        common = 0
        for a, b in zip(syl, target):
            if a != b:
                break
            common += 1
        n_back = len(syl) - common
        letters = target[common:]
        self.prefix = self.prefix[:self.syllable_start] + target
        self.syllable = target
        self.syllable_start = len(self.prefix) - len(target)
        self.stage = Stage.FINAL_HEAD
        self._refresh_items()
        self.idx = 0
        if n_back <= 0:
            self.pending_text = letters
            return Action.SEND_LETTER
        self.pending_text = f"{n_back}|{letters}"
        return Action.FIXUP

    def _three_key_pick_head(self, head: str) -> Action:
        """三键 FINAL_HEAD 确认韵头组：**选韵头即上屏**（用户定案——zhe 立即
        出现在屏幕，e/en/eng 菜单随后可精化），进入韵尾菜单（含当前态）。
        注意：韵母表按**声母**查（ini），必须在追加韵头前取值。"""
        ini = self.syllable
        self.pending_text = head
        self.prefix += head
        self.syllable += head
        tails = [f for f in self.model.finals(ini) if f.startswith(head)]
        if len(tails) <= 1:
            # 组内仅韵头自身 → 直接收尾
            self.stage = Stage.DONE
            self._refresh_items()
            return Action.SEND_LETTER
        self.stage = Stage.FINAL_TAIL
        self._tails = tails
        self.items = list(tails)
        self.idx = tails.index(head) if head in tails else 0
        return Action.SEND_LETTER

    def _three_key_pick_tail(self, final: str) -> Action:
        """三键 FINAL_TAIL 确认：选当前态 = 收尾进 DONE（无输出）；
        选更长续接 = 补发差量字母并停留在韵尾菜单（继续精化）。"""
        syl = self.syllable
        rest = syl[len(self._longest_initial(syl)):] if syl else ""
        if final == rest:
            self.stage = Stage.DONE
            self._refresh_items()
            return Action.NONE
        if final.startswith(rest) and rest:
            delta = final[len(rest):]
            self.pending_text = delta
            self.prefix += delta
            self.syllable += delta
            self.stage = Stage.FINAL_TAIL
            self._tails = [f for f in self.model.finals(
                self._longest_initial(self.syllable))
                if f.startswith(self.syllable[len(self._longest_initial(
                    self.syllable)):])]
            self.items = list(self._tails)
            self.idx = self.items.index(final) if final in self.items else 0
            return Action.SEND_LETTER
        # 兜底（不应发生）：整发该韵母
        return self._commit_final(final)

    def _start_initial(self, ini: str) -> Action:
        self.pending_text = ini
        self.syllable = ini
        self.syllable_start = len(self.prefix)
        self.prefix += ini
        self.stage = Stage.FINAL_HEAD
        self._refresh_items()
        self.idx = 0
        return Action.SEND_LETTER

    # ---------- 事件入口 ----------

    def handle(self, ev: Event) -> Action:
        if self.mode is Mode.SELECT:
            return self._select(ev)
        return self._pinyin(ev)

    # ----- 拼字模式（INITIAL/FINAL_HEAD/FINAL_TAIL/DONE） -----

    def _pinyin(self, ev: Event) -> Action:
        if ev is Event.SCROLL_UP and self.items:
            self.idx = (self.idx - 1) % len(self.items)
            return Action.NONE
        if ev is Event.SCROLL_DOWN and self.items:
            self.idx = (self.idx + 1) % len(self.items)
            return Action.NONE

        if ev is Event.RIGHT and self.three_key:
            # 三键模式：右键 = 逐字退格 + 菜单自动回退（D-049）
            return self._three_key_backspace()
        if ev in (Event.X1, Event.RIGHT):
            # 任何时候可切选字（微软拼音对不完整拼音也出候选）
            self._switch_select()
            return Action.NONE
        if ev is Event.X2:
            # 宪法 F-001：X2 = 退格撤销。统一撤销整个音节回声母层（全显 24 项）
            return self._cancel_syllable()

        if ev is not Event.LEFT or not self.items:
            return Action.NONE
        picked = self.items[self.idx]

        if self.stage is Stage.INITIAL:
            if self.three_key and self.prefix:
                return self._three_key_pick_initial(picked)
            self._start_initial(picked)                 # 发声母（可能两键）
            return Action.SEND_LETTER

        if self.stage is Stage.FINAL_HEAD:
            if self.three_key:
                # 三键：选韵头即上屏（D-049），组内多项时停留在韵尾菜单
                return self._three_key_pick_head(picked)
            tails = dict(self._grouped_finals(self.syllable))[picked]
            if len(tails) == 1:
                return self._commit_final(tails[0])     # 组内单项：合并直发
            self._tails = tails
            self.stage = Stage.FINAL_TAIL               # 不发键
            self._refresh_items()
            self.idx = 0
            return Action.NONE

        if self.stage is Stage.FINAL_TAIL:
            if self.three_key:
                return self._three_key_pick_tail(picked)
            return self._commit_final(picked)

        # DONE：首项=切选字；其余=下一声母（整句流）
        if picked.startswith("␣"):
            self._switch_select()
            return Action.NONE
        return self._start_initial(picked)

    def _commit_final(self, final: str) -> Action:
        """整发完整韵母 → 音节完成。"""
        self.pending_text = final
        self.prefix += final
        self.syllable += final
        self.stage = Stage.DONE
        self._refresh_items()
        self.idx = 0
        return Action.SEND_LETTER

    # ----- 选字模式 -----

    def _select(self, ev: Event) -> Action:
        if ev is Event.SCROLL_UP:
            return Action.SEND_UP
        if ev is Event.SCROLL_DOWN:
            return Action.SEND_DOWN
        if ev is Event.LEFT:
            # D-031：发送确认键 ≠ 组合结束。不清空会话——组合状态由
            # 输出层发键后的 IME 反馈（ime_feedback）判定，ENDED 时经
            # end_select_session() 清空；部分确认/未知都保持 SELECT 继续选字。
            self.pending_text = ""
            return Action.SEND_SPACE
        if ev is Event.RIGHT:
            if self.three_key:
                return self._three_key_select_backspace()
            return Action.SEND_PAGEDOWN
        if ev is Event.X1:
            self.mode = Mode.PINYIN                     # 回拼字：拼音缓冲保留
            self._refresh_items()
            self.idx = 0
            return Action.NONE
        if ev is Event.X2:
            if self.prefix:
                self.prefix = self.prefix[:-1]          # 输入法侧删一个字母
                self.pending_text = ""                  # 单次退格（payload 空 = 1 次）
                return Action.BACKSPACE
            # D-053：缓冲已空（组合多已结束/未知）——不再盲发退格，防止
            # 删除目标输入框中用户已上屏的字符（同类泄漏：导航键落错目标）
            return Action.NONE
        return Action.NONE

    # ---------- 渲染快照 ----------

    def snapshot(self) -> Snapshot:
        stage_name = {Stage.INITIAL: "声母", Stage.FINAL_HEAD: "韵头",
                      Stage.FINAL_TAIL: "韵母", Stage.DONE: "完成"}[self.stage]
        if self.mode is Mode.PINYIN:
            ctx = f"拼字[{stage_name}] ｜ {self.prefix or '（空）'}"
            if self.stage is Stage.DONE:
                ctx += " ｜ ␣选字 或继续下一声母（整句）"
        else:
            comp = (f"剩余 {self.composition}" if self.composition is not None
                    else f"{self.prefix}（{self.composition_state}）")
            ctx = f"选字 ｜ 组合[{self.composition_state}]：{comp}"
        return Snapshot(
            mode=self.mode,
            stage=self.stage,
            prefix=self.prefix,
            syllable=self.syllable,
            items=self.items,
            idx=self.idx,
            context=ctx,
            composition=self.composition,
            composition_state=self.composition_state,
        )
