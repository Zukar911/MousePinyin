"""T-006: build_syllables.py —— 音节全集 + 声母→有效韵母映射

输入：data/raw/pinyin.txt（mozillazg/pinyin-data，MIT）
输出：data/syllables.json  {initial: {final: weight_placeholder}}
     及统计摘要（U6 销号：y/w 处理结论）

内部表示约定：
- 韵母用 v 表示 ü；ui/iu/un 为简写形式；ve=üe, vn=ün, van=üan
- 声母 = 21 传统声母 + y + w + ''(零声母)，共 24 项
- 切分规则：j/q/x/y 后的 u 归一化为 v（普通话无 ju[ju]，u 实为 ü）
- UI 显示层负责 v→ü 转换，本表只存内部编码
"""

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "pinyin.txt"
OUT = ROOT / "data" / "syllables.json"

# 声调剥离映射（拼音声调符号 → 无调字母）
TONE_MAP = str.maketrans({
    "ā": "a", "á": "a", "ǎ": "a", "à": "a",
    "ē": "e", "é": "e", "ě": "e", "è": "e",
    "ī": "i", "í": "i", "ǐ": "i", "ì": "i",
    "ō": "o", "ó": "o", "ǒ": "o", "ò": "o",
    "ū": "u", "ú": "u", "ǔ": "u", "ù": "u",
    "ǖ": "v", "ǘ": "v", "ǚ": "v", "ǜ": "v",
    "ü": "v",
    "ń": "n", "ň": "n", "ǹ": "n",
    "ḿ": "m",
    "\u0300": "",  # 组合变音符（如 m̀ 的尾标调），剥离
})

INITIALS_2 = ("zh", "ch", "sh")
INITIALS_1 = set("bpmfdtnlgkhjqxrzcsyw")
# 完整音系韵母集合（教学 24 韵母 + 组合韵母），v=ü
FINAL_SET = {
    # 单韵母
    "a", "o", "e", "i", "u", "v",
    # 复韵母
    "ai", "ei", "ui", "ao", "ou", "iu", "ie", "ve", "er",
    # 前鼻韵母
    "an", "en", "in", "un", "vn",
    # 后鼻韵母
    "ang", "eng", "ing", "ong",
    # i 系组合
    "ia", "iao", "ian", "iang", "iong",
    # u 系组合
    "ua", "uo", "uai", "uan", "uang",
    # ü 系组合
    "van",
}


def strip_tone(p: str) -> str:
    return p.translate(TONE_MAP)


def split_initial_final(syl: str):
    """把无调音节切分为 (initial, final)；不合法返回 None。"""
    if syl[:2] in INITIALS_2:
        ini, rest = syl[:2], syl[2:]
    elif syl[:1] in INITIALS_1:
        ini, rest = syl[:1], syl[1:]
    else:
        ini, rest = "", syl
    # j/q/x/y 后的 u 一律归一化为 ü(v)
    if ini in ("j", "q", "x", "y") and rest.startswith("u"):
        rest = "v" + rest[1:]
    if not ini and rest and rest[0] in "iu" and rest not in ("i", "u"):
        # 零声母 i/u 开头的音节不存在（yi/wu 已由 y/w 承接），防御
        return None
    if rest not in FINAL_SET:
        return None
    return ini, rest


def main():
    syllable_chars = defaultdict(set)   # 无调音节 -> {汉字}
    raw_map = defaultdict(set)          # 汉字 -> {无调音节}
    line_re = re.compile(r"^U\+([0-9A-Fa-f]+): ([a-züāáǎàéěèīíǐìōóǒòūúǔùǖǘǚǜńňǹḿm̀,]+)\s+#\s+(.+)$")

    for line in RAW.read_text(encoding="utf-8").splitlines():
        m = line_re.match(line)
        if not m:
            continue
        cp = int(m.group(1), 16)
        # 仅取 CJK 统一表意文字主块 + 扩展A + 兼容表意区
        if not (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF):
            continue
        hanzi = m.group(3).split()[0]
        for p in m.group(2).split(","):
            syl = strip_tone(p)
            if not syl:
                continue
            syllable_chars[syl].add(hanzi)
            raw_map[hanzi].add(syl)

    # 音节 → (声母, 韵母)
    valid = {}
    invalid = set()
    for syl in syllable_chars:
        sf = split_initial_final(syl)
        if sf:
            valid[syl] = sf
        else:
            invalid.add(syl)

    initial_finals = defaultdict(set)
    for syl, (ini, fin) in valid.items():
        initial_finals[ini].add(fin)

    result = {
        "meta": {
            "source": "mozillazg/pinyin-data pinyin.txt (MIT)",
            "raw_syllables": len(syllable_chars),
            "valid_syllables": len(valid),
            "invalid_examples": sorted(invalid)[:30],
            "initials": sorted(initial_finals.keys(), key=lambda x: (len(x), x)),
            "finals": sorted(FINAL_SET),
            "note": "v=ü; ve=üe; vn=ün; van=üan; j/q/x/y 后 u→v 归一化",
        },
        "initial_finals": {k: sorted(v) for k, v in sorted(initial_finals.items())},
        "syllable_chars_top": {
            s: sorted(chars)[:5] for s, chars in sorted(valid.items())
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"原始无调音节数   : {len(syllable_chars)}")
    print(f"合法音节数       : {len(valid)}")
    print(f"无法切分样例     : {sorted(invalid)[:15]}")
    print(f"声母数（含零声母）: {len(initial_finals)} -> {sorted(initial_finals.keys(), key=lambda x: (len(x), x))}")
    zero = sorted(initial_finals.get("", []))
    print(f"零声母韵母       : {zero}")
    yw = {k: sorted(v) for k, v in initial_finals.items() if k in ("y", "w")}
    print(f"y 声母韵母       : {yw.get('y')}")
    print(f"w 声母韵母       : {yw.get('w')}")
    per = {k: len(v) for k, v in sorted(initial_finals.items(), key=lambda x: -len(x[1]))}
    print(f"各声母有效韵母数  : {per}")
    print(f"输出: {OUT}")


if __name__ == "__main__":
    main()
