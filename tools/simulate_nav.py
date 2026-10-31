"""需求③模拟测试：方案A（两级菜单）vs 方案B（渐进字母树）操作步数对比

数据：data/candidates.json（每音节候选字频 → 音节权重 = Σ候选字频，字频加权口径）
方案A：声母层（24项频率排序，环形滚动）+1确认 → 韵母层（该声母韵母频率排序）+1确认
方案B：前缀树逐字母（如 zhong = z→h→o→n→g 五节点），每节点在"下一字母建议"
      （按该延续覆盖音节字频总和降序）中环形滚动 + 1确认；声母 zh 等也是树路径
指标：字频加权期望滚轮次数 / 期望确认次数 / 期望总步数（选字阶段两方案相同不计入）
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cand = json.loads((ROOT / "data" / "candidates.json").read_text(encoding="utf-8"))

# 音节权重
syl_w = {s: sum(f for _, f in lst) for s, lst in cand.items()}

def split(s):
    if s[:2] in ("zh", "ch", "sh"):
        return s[:2], s[2:]
    return (s[:1], s[1:]) if s[:1] in "bpmfdtnlgkhjqxrzcsyw" else ("", s)

# ---------- 方案A 数据 ----------
initials = sorted({split(s)[0] for s in cand}, key=lambda i: -sum(w for s, w in syl_w.items() if split(s)[0] == i))
ini_rank = {i: p for p, i in enumerate(initials)}
finals_by_ini = defaultdict(list)
for s in cand:
    ini, fin = split(s)
    finals_by_ini[ini].append((fin, syl_w[s]))
for ini in finals_by_ini:
    finals_by_ini[ini].sort(key=lambda x: -x[1])

def ring_steps(rank, n, bidirectional=True):
    if n <= 1:
        return 0
    return min(rank, n - rank) if bidirectional else rank

def steps_A(syl):
    ini, fin = split(syl)
    n1 = len(initials)
    s1 = ring_steps(ini_rank[ini], n1, bidirectional=False)   # 单向（滚轮只下滚口径）
    n2 = len(finals_by_ini[ini])
    p2 = [f for f, _ in finals_by_ini[ini]].index(fin)
    s2 = ring_steps(p2, n2, bidirectional=False)
    return s1 + s2, 2

# ---------- 方案B 数据 ----------
# 前缀树：node(prefix) 的延续字母 = {c: Σ 该前缀+c 覆盖音节权重}
prefix_children = defaultdict(dict)   # prefix -> {letter: weight}
for s, w in syl_w.items():
    for k in range(1, len(s) + 1):
        prefix, c = s[:k - 1], s[k - 1]
        prefix_children[prefix][c] = prefix_children[prefix].get(c, 0.0) + w

def steps_B(syl):
    scroll = 0
    confirms = 0
    for k in range(1, len(syl) + 1):
        prefix, letter = syl[:k - 1], syl[k - 1]
        kids = prefix_children[prefix]
        ranked = sorted(kids.items(), key=lambda x: -x[1])
        letters = [c for c, _ in ranked]
        p = letters.index(letter)
        scroll += ring_steps(p, len(letters), bidirectional=False)
        confirms += 1
    return scroll, confirms

# ---------- 加权统计 ----------
tot_w = sum(syl_w.values())
stats = {
    "A": [0.0, 0.0, 0.0],   # scroll, confirm, total (加权累积)
    "B": [0.0, 0.0, 0.0],
}
rows = []
for s, w in syl_w.items():
    sa, ca = steps_A(s)
    sb, cb = steps_B(s)
    stats["A"][0] += w * sa; stats["A"][1] += w * ca; stats["A"][2] += w * (sa + ca)
    stats["B"][0] += w * sb; stats["B"][1] += w * cb; stats["B"][2] += w * (sb + cb)
    rows.append((s, w, sa + ca, sb + cb))

print(f"音节数: {len(syl_w)}  总权重: {tot_w:.1f}")
print(f"\n{'指标（字频加权期望/每字）':<24}{'方案A 两级':>10}{'方案B 渐进':>10}{'差':>8}")
for j, name in enumerate(["滚轮次数", "确认次数", "总步数"]):
    a, b = stats["A"][j] / tot_w, stats["B"][j] / tot_w
    print(f"{name:<24}{a:>10.2f}{b:>10.2f}{b - a:>+8.2f}")

# 高频 TOP15 音节明细
rows.sort(key=lambda r: -r[1])
print("\nTOP15 高频音节步数明细（A vs B）：")
for s, w, a, b in rows[:15]:
    print(f"  {s:6s} 权重{w:8.1f}   A={a:2d}  B={b:2d}  {'B优' if b < a else 'A优' if a < b else '平'}")

# B 的逐节点列表长度分布（认知负荷参考）
lens = defaultdict(int)
for s in syl_w:
    for k in range(1, len(s) + 1):
        lens[len(prefix_children[s[:k - 1]])] += 1
print("\n方案B 每节点『下一字母建议』数量分布（列表短→好扫）：")
for n in sorted(lens):
    print(f"  {n} 项: {lens[n]} 节点")
