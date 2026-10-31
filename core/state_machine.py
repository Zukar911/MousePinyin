"""core/state_machine.py —— 双模式状态机 v5（D-024 整句流 + D-055 去选字菜单层）

PINYIN 拼字模式（声母整发 + 韵母两级 + 整句流）：
  INITIAL     选声母（24 项整发，如 zh = 一次发 z,h 两键）
  FINAL_HEAD  选韵头组（a/o/e/i/u/ü，仅该声母下有效的组，≤6 项）——不发键
  FINAL_TAIL  选该组下韵母（≤10 项，频率降序）→ 1 次确认整发完整韵母
              组内仅 1 项时自动合并（选组即发，保持快捷）
  DONE        音节完成：items = ["␣ 上屏"] + 声母列表 —— 首项**直接发空格
              上屏整句候选**（D-055：不再进入选字二级菜单——微软拼音的候选
              窗本就在输入框旁，Dock 不重复承载），其余继续拼（整句连续流）
  X1          拼字各态 = 无操作（D-055：选字模式移除后侧键闲置）
  X2 = 撤销：FINAL_TAIL→回 FINAL_HEAD（韵母未发不退格）；其余=撤销当前音节（退格回边界）
  RIGHT       统一逐字退格（D-055：两种模式右键语义一致；原"切选字/翻页"随
              选字模式移除）

【D-055 移除 SELECT 选字菜单层】原 Mode.SELECT（单键帽"拼音（组合未知）"
菜单）整体移除：①微软拼音整句流下候选窗已由输入法承载，Dock 重复展示无价值；
②三键模式（无侧键）下该层无任何回退通路（右键被逐字退格占用）→ 卡死；
③组合状态 UNKNOWN 时滞留并持续泄漏导航键（D-053 根因场景）。
上屏语义改由 DONE 层直接承担：SEND_SPACE → IME 反馈（D-031/D-053 门闸）
判定 COMPOSING（prefix 同步输入法剩余）/ ENDED（清会话回声母层）。

行为矩阵以 01 §4（v5）为规范；纯逻辑，键盘模拟由 KeyboardSink 主线程执行。
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


def normalize_prefix(s: str) -> str:
    """拼音缓冲比较归一：去隔音符/空格（IME 剩余回读可能带分隔符）。"""
    return s.replace("'", "").replace(" ", "")


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
        else:  # DONE：首项上屏 + 下一声母（整句流，D-055）
            self.items = ["␣ 上屏"] + list(self.model.initials())
        self.idx = 0

    # ---------- 选字会话语义（D-055：迁移到 DONE 层，无二级菜单） ----------

    def update_composition(self, remaining: str | None, state: str) -> None:
        """IME 状态读回后同步（原 D-031 SELECT 语义 → D-055 DONE 层语义）：
        COMPOSING（remaining 可信）→ **prefix 同步为输入法侧剩余组合**（音节
        段从 0 重标）并重建拼字状态（音节未完则回到对应韵母层继续；已完则
        留 DONE 继续拼）；ENDED → 清会话回声母层；UNKNOWN → 保守不动（保持
        当前状态 + 原缓冲，不冒充不乱清）。"""
        if state == "COMPOSING" and remaining is not None:
            if normalize_prefix(remaining) != normalize_prefix(self.prefix):
                self.prefix = remaining
                self.syllable_start = 0            # 剩余组合 = 完整待拼内容
                self._rederive_from_prefix(Stage.DONE)
            self.composition = remaining           # _rederive 会复位 → 后置
            self.composition_state = state
            return
        if state == "ENDED":
            self.end_select_session()
            return
        # UNKNOWN：保守保持（原缓冲 + 当前层，字段不覆盖已有可信值）
        if state != "UNKNOWN" or self.composition_state == "UNKNOWN":
            self.composition_state = state

    def end_select_session(self) -> None:
        """组合确认结束：清空会话回声母层（IME 反馈 ENDED / 显式重置调用）。"""
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
        self.syllable = syl                     # D-055：完整音节段（含韵尾）——
        # _pick_tail 的 rest、_cancel_syllable 的退格数都依赖完整 syllable
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
                self.syllable = syl                 # 残段 = 声母（D-055 同步）
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

    def _pick_tail(self, final: str) -> Action:
        """韵尾确认（D-055 起两模式统一，原 _three_key_pick_tail）：
        选当前态 = 收尾进 DONE（无输出；IME 剩余同步重derive 后的"接受"场景）；
        选更长续接 = 补发差量字母并停留在韵尾菜单（继续精化）。"""
        syl = self.syllable
        rest = syl[len(self._longest_initial(syl)):] if syl else ""
        if final == rest and self.prefix.endswith(syl):
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
        # 兜底（全新音节的整发）：整发该韵母
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
        # D-055：SELECT 选字菜单层移除，mode 恒 PINYIN（枚举保留仅为兼容旧引用）
        return self._pinyin(ev)

    # ----- 拼字模式（INITIAL/FINAL_HEAD/FINAL_TAIL/DONE） -----

    def _pinyin(self, ev: Event) -> Action:
        if ev is Event.SCROLL_UP and self.items:
            self.idx = (self.idx - 1) % len(self.items)
            return Action.NONE
        if ev is Event.SCROLL_DOWN and self.items:
            self.idx = (self.idx + 1) % len(self.items)
            return Action.NONE

        if ev is Event.RIGHT:
            # D-055：右键统一逐字退格（两种模式一致；原"非三键切选字/三键退格"
            # 分叉随选字模式移除而统一）
            return self._three_key_backspace()
        if ev is Event.X1:
            return Action.NONE                  # D-055：选字模式移除，侧键闲置
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
            # D-055 统一两种模式的韵尾确认（含"接受当前态"语义——IME 剩余
            # 同步重derive 后当前态已在组合中，此时确认 = 收尾不发键）
            return self._pick_tail(picked)

        # DONE：首项 = **直接发空格上屏整句候选**（D-055，不再进选字菜单）；
        # 其余 = 下一声母（整句流）
        if picked.startswith("␣"):
            self.pending_text = ""
            return Action.SEND_SPACE
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
        return Action.NONE

    # ---------- 渲染快照 ----------

    def snapshot(self) -> Snapshot:
        stage_name = {Stage.INITIAL: "声母", Stage.FINAL_HEAD: "韵头",
                      Stage.FINAL_TAIL: "韵母", Stage.DONE: "完成"}[self.stage]
        ctx = f"拼字[{stage_name}] ｜ {self.prefix or '（空）'}"
        if self.stage is Stage.DONE:
            ctx += " ｜ ␣上屏 或继续下一声母（整句）"
        if self.composition_state != "UNKNOWN" and self.composition is not None:
            ctx += f" ｜ 同步[{self.composition}]"
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
