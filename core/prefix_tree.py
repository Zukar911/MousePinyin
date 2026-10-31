"""core/prefix_tree.py —— 拼音前缀树导航数据（D-018 方案B 核心数据结构）

从 data/candidates.json 的音节集合构建：
- 前缀 → 下一字母建议（按该延续覆盖音节的字频总和降序）
- 前缀 → 是否完整音节 / 是否叶子（无延续 → 叶子音节自动切选字模式）

例：拼到 ian，建议列表 = [g(iang), ...其他可延续]；拼到 zhong（叶子）自动选字。
"""

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAND_PATH = ROOT / "data" / "candidates.json"


class PrefixTree:
    def __init__(self, syllable_weights: dict[str, float] | None = None):
        if syllable_weights is None:
            cand = json.loads(CAND_PATH.read_text(encoding="utf-8"))
            syllable_weights = {s: sum(f for _, f in lst) for s, lst in cand.items()}
        self._weights = syllable_weights
        # prefix -> {letter: Σ覆盖音节权重}
        self._children: dict[str, dict[str, float]] = defaultdict(dict)
        self._syllables = set(syllable_weights)
        for s, w in syllable_weights.items():
            for k in range(1, len(s) + 1):
                prefix, letter = s[:k - 1], s[k - 1]
                self._children[prefix][letter] = self._children[prefix].get(letter, 0.0) + w

    @lru_cache(maxsize=1024)
    def suggests(self, prefix: str) -> list[str]:
        """下一字母建议（按覆盖字频总和降序）。空前缀 = 声母首字母建议。"""
        kids = self._children.get(prefix, {})
        return [c for c, _ in sorted(kids.items(), key=lambda x: -x[1])]

    def is_syllable(self, prefix: str) -> bool:
        """当前前缀是否为完整音节（可切选字）。"""
        return prefix in self._syllables

    def is_leaf(self, prefix: str) -> bool:
        """叶子音节：是完整音节且无延续字母（自动切选字的唯一时机）。"""
        return prefix in self._syllables and not self._children.get(prefix)
