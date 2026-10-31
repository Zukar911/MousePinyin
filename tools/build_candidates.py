"""T-007: build_candidates.py —— 每音节候选字列表（按字频降序）+ 韵母权重

输入：data/raw/pinyin.txt（字→音，MIT）+ wordfreq 中文词频（MIT + CC BY-SA 4.0）
输出：data/candidates.json    {syllable: [[char, freq], ...]}  每音节截前 30
     data/final_weights.json {initial: {final: weight}}       韵母排序权重（高频匹配核心）

字频口径：用字频率 —— 遍历 wordfreq 中文词表（频次降序），词的频次按字符均摊。
Zipf 近似：rank r 的词贡献 1/(r+1)；单字词全额，多字词按字长均摊。
该口径 = 「字在真实语料中被使用的频率」，比纯单字表更贴合候选排序需求。
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_syllables import split_initial_final, strip_tone  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "kMandarin_8105.txt"   # 规范 8105 字·普通话最常用读音（降噪首选）
RAW_FALLBACK = ROOT / "data" / "raw" / "pinyin.txt"  # 全量数据（含古异读，仅作 fallback）
OUT_CAND = ROOT / "data" / "candidates.json"
OUT_WEIGHT = ROOT / "data" / "final_weights.json"

TOP_N = 60000          # 词表截断规模（覆盖常用语料足够）
MAX_CAND = 30          # 每音节候选字截断数
CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))


def is_hanzi(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def load_char_syllables():
    """解析字音数据 -> {char: {无调音节}}。优先 8105 规范字表（单读音降噪），fallback 全量。"""
    import re
    src = RAW if RAW.exists() else RAW_FALLBACK
    line_re = re.compile(r"^U\+([0-9A-Fa-f]+): ([^#]+?)\s+#\s+(.+)$")
    char_syls = defaultdict(set)
    for line in src.read_text(encoding="utf-8").splitlines():
        m = line_re.match(line)
        if not m:
            continue
        cp = int(m.group(1), 16)
        if not is_hanzi(chr(cp)):
            continue
        hanzi = m.group(3).split()[0]
        if not is_hanzi(hanzi):
            continue
        for p in m.group(2).split(","):
            syl = strip_tone(p)
            if split_initial_final(syl):
                char_syls[hanzi].add(syl)
    return char_syls


def build_char_freq():
    """wordfreq 词表 -> {char: freq}（Zipf 近似，词频均摊到字符）"""
    from wordfreq import top_n_list
    freq = defaultdict(float)
    for rank, word in enumerate(top_n_list("zh", TOP_N)):
        w = 1.0 / (rank + 1)
        chars = [c for c in word if is_hanzi(c)]
        if not chars:
            continue
        share = w if len(chars) == 1 else w / len(chars)
        for c in chars:
            freq[c] += share
    return freq


def main():
    print("解析 pinyin.txt ...")
    char_syls = load_char_syllables()
    print(f"  有音节的汉字数: {len(char_syls)}")

    print("构建字频（wordfreq top %d 词）..." % TOP_N)
    char_freq = build_char_freq()
    print(f"  覆盖汉字数: {len(char_freq)}")
    top10 = sorted(char_freq.items(), key=lambda x: -x[1])[:10]
    print(f"  字频 top10: {[c for c, _ in top10]}")

    # 音节 -> 候选字
    syl_cands = defaultdict(list)
    for ch, syls in char_syls.items():
        f = char_freq.get(ch, 0.0)
        for syl in syls:
            syl_cands[syl].append((ch, f))

    candidates = {}
    for syl, lst in syl_cands.items():
        lst.sort(key=lambda x: -x[1])
        candidates[syl] = [[c, round(f, 8)] for c, f in lst[:MAX_CAND]]

    # 韵母权重 = Σ候选字频率（高频匹配核心：声母内韵母按此降序）
    ini_fin_w = defaultdict(lambda: defaultdict(float))
    syl_sf = {}
    for syl in candidates:
        sf = split_initial_final(syl)
        if sf:
            syl_sf[syl] = sf
            ini, fin = sf
            ini_fin_w[ini][fin] += sum(f for _, f in candidates[syl])

    weights = {ini: {fin: round(w, 8) for fin, w in sorted(fins.items(), key=lambda x: -x[1])}
               for ini, fins in ini_fin_w.items()}

    OUT_CAND.write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
    OUT_WEIGHT.write_text(json.dumps(weights, ensure_ascii=False, indent=1), encoding="utf-8")

    # 摘要：展示高频匹配效果
    print("\n高频匹配效果抽查（每声母 top5 韵母）：")
    for ini in ("zh", "z", "l", "j", "b", ""):
        fins = weights.get(ini, {})
        print(f"  {ini or '(零声母)':6s}: {list(fins.keys())[:5]}")
    print("\n候选抽查（top 音节首 6 字）：")
    for syl in ("zhong", "shi", "yi", "de"):
        print(f"  {syl:6s}: {''.join(c for c, _ in candidates.get(syl, [])[:6])}")
    empty = [s for s, lst in candidates.items() if not lst]
    print(f"\n空候选音节: {len(empty)}")
    print(f"输出: {OUT_CAND}")
    print(f"输出: {OUT_WEIGHT}")


if __name__ == "__main__":
    main()
