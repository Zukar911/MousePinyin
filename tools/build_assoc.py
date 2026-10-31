"""T-008: build_assoc.py —— bigram 联想表（前字→后字）

输入：data/raw/dict.txt（jieba 词典，MIT；随 jieba 包分发，安装后复制）
格式：词条 词频 词性（空格分隔）
输出：data/assoc.json  {prev_char: [[next_char, freq], ...]}  每前字截前 30

口径：取长度 ≥2 的纯汉字词，词内全部相邻字对 bigram[前字][后字] += 词频。
只保留汉字对（标点/字母词跳过），保证联想候选都是可继续输入的汉字。
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "dict.txt"
OUT = ROOT / "data" / "assoc.json"

MAX_NEXT = 30
CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))


def is_hanzi(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def main():
    if not RAW.exists():
        raise SystemExit(f"缺少 {RAW} —— 请先从 jieba 包复制 dict.txt（安装后 jieba/dict.txt）")

    bigram = defaultdict(float)
    n_words = 0
    for line in RAW.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        word, freq_s = parts[0], parts[1]
        if len(word) < 2:
            continue
        try:
            freq = float(freq_s)
        except ValueError:
            continue
        if not all(is_hanzi(c) for c in word):
            continue
        n_words += 1
        for i in range(len(word) - 1):
            bigram[(word[i], word[i + 1])] += freq

    per_prev = defaultdict(list)
    for (prev, nxt), f in bigram.items():
        per_prev[prev].append((nxt, f))

    assoc = {}
    for prev, lst in per_prev.items():
        lst.sort(key=lambda x: -x[1])
        assoc[prev] = [[nxt, int(f)] for nxt, f in lst[:MAX_NEXT]]

    OUT.write_text(json.dumps(assoc, ensure_ascii=False), encoding="utf-8")

    print(f"纯汉字多字词数: {n_words}")
    print(f"bigram 对数    : {len(bigram)}")
    print(f"有联想的前字数 : {len(assoc)}")
    print("\n联想抽查：")
    for ch in ("你", "我", "不", "中", "好"):
        nxt = "".join(c for c, _ in assoc.get(ch, [])[:8])
        print(f"  {ch} → {nxt}")
    print(f"\n输出: {OUT}")


if __name__ == "__main__":
    main()
