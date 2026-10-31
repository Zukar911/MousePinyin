"""T-009: validate_index.py —— 合并三份 JSON 构建 data/index.db + 校验报告

输入：data/syllables.json / data/candidates.json / data/final_weights.json / data/assoc.json
输出：data/index.db（只读三表 + initials 权重表）

校验项：
 V1 合法音节数在 380~430 区间
 V2 每音节候选非空
 V3 高频音节抽样 40 个打印 top5（人工核对）
 V4 韵母权重排序抽查（高频匹配验证）
 V5 联想表抽查
 V6 DB 查询往返测试（CandidateModel 接口）
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "index.db"


def main():
    syl_meta = json.loads((DATA / "syllables.json").read_text(encoding="utf-8"))
    candidates = json.loads((DATA / "candidates.json").read_text(encoding="utf-8"))
    weights = json.loads((DATA / "final_weights.json").read_text(encoding="utf-8"))
    assoc_path = DATA / "assoc.json"
    assoc = json.loads(assoc_path.read_text(encoding="utf-8")) if assoc_path.exists() else {}
    if not assoc:
        print("!! assoc.json 缺失 —— 联想层将为空（先跑 tools/build_assoc.py）")

    # ---- 重组：音节 -> (initial, final) ----
    syl_sf = {}
    for syl in candidates:
        if syl[:2] in ("zh", "ch", "sh"):
            ini, fin = syl[:2], syl[2:]
        else:
            head = syl[:1]
            if head and head in "bpmfdtnlgkhjqxrzcsyw":
                ini, fin = head, syl[1:]
            else:
                ini, fin = "", syl
        syl_sf[syl] = (ini, fin)

    # V1 音节数
    n = len(candidates)
    print(f"V1 音节数 = {n} -> {'PASS' if 380 <= n <= 430 else 'FAIL'}")

    # V2 候选非空
    empty = [s for s, lst in candidates.items() if not lst]
    print(f"V2 空候选音节数 = {len(empty)} -> {'PASS' if not empty else 'FAIL'}")

    # ---- 构建初值表：声母权重（SM 层排序）----
    ini_weight = {}
    for syl, lst in candidates.items():
        ini, _ = syl_sf[syl]
        ini_weight[ini] = ini_weight.get(ini, 0.0) + sum(f for _, f in lst)

    # ---- 写入 SQLite ----
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(
        """
        CREATE TABLE initials (initial TEXT PRIMARY KEY, weight REAL);
        CREATE TABLE syllables (initial TEXT, final TEXT, rank INTEGER,
                                PRIMARY KEY(initial, final));
        CREATE TABLE candidates (syllable TEXT, hanzi TEXT, freq REAL, rank INTEGER,
                                 PRIMARY KEY(syllable, rank));
        CREATE TABLE assoc (prev TEXT, next TEXT, freq REAL, rank INTEGER,
                            PRIMARY KEY(prev, rank));
        CREATE INDEX idx_cand ON candidates(syllable, rank);
        CREATE INDEX idx_assoc ON assoc(prev, rank);
        """
    )
    conn.executemany(
        "INSERT INTO initials VALUES (?,?)",
        sorted(ini_weight.items(), key=lambda x: -x[1]),
    )
    syl_rows = []
    for ini, fins in weights.items():
        for rank, (fin, _w) in enumerate(fins.items()):
            syl_rows.append((ini, fin, rank))
    conn.executemany("INSERT INTO syllables VALUES (?,?,?)", syl_rows)

    cand_rows = []
    for syl, lst in candidates.items():
        for rank, (ch, f) in enumerate(lst):
            cand_rows.append((syl, ch, f, rank))
    conn.executemany("INSERT INTO candidates VALUES (?,?,?,?)", cand_rows)

    assoc_rows = []
    for prev, lst in assoc.items():
        for rank, (nxt, f) in enumerate(lst):
            assoc_rows.append((prev, nxt, float(f), rank))
    conn.executemany("INSERT INTO assoc VALUES (?,?,?,?)", assoc_rows)
    conn.commit()

    print(f"DB 写入: initials={len(ini_weight)} syllables={len(syl_rows)} "
          f"candidates={len(cand_rows)} assoc={len(assoc_rows)}")

    # V3 高频音节抽样
    high = sorted(candidates.items(), key=lambda kv: -sum(f for _, f in kv[1]))[:40]
    print("\nV3 高频音节 top40 首选字（人工核对用）：")
    line = []
    for syl, lst in high:
        line.append(f"{syl}:{''.join(c for c, _ in lst[:5])}")
        if len(line) == 5:
            print("  " + "  ".join(line))
            line = []
    if line:
        print("  " + "  ".join(line))

    # V4 韵母权重抽查
    print("\nV4 高频匹配抽查（声母 -> top5 韵母）：")
    for ini in ("zh", "z", "l", "j", "b"):
        fins = list(weights.get(ini, {}).keys())[:5]
        print(f"  {ini or '∅':3s}: {fins}")

    # V5 联想抽查
    print("\nV5 联想抽查：")
    for ch in ("你", "中", "不"):
        nxt = "".join(c for c, _ in assoc.get(ch, [])[:8])
        print(f"  {ch} -> {nxt}")

    # V6 DB 往返测试
    from core.candidate_model import CandidateModel, display_final
    m = CandidateModel()
    inis = m.initials()
    print(f"\nV6 initials 排序: {[i if i else '∅' for i in inis]}")
    f_zh = m.finals("zh")
    print(f"V6 finals(zh)   : {f_zh[:6]} ... 共{len(f_zh)}")
    c = m.candidates("zhong")
    print(f"V6 cand(zhong)  : {''.join(c[:6])}")
    a = m.assoc("中")
    print(f"V6 assoc(中)    : {''.join(a[:8])}")
    print(f"V6 display(van/ve/vn) = {display_final('van')} {display_final('ve')} {display_final('vn')}")
    ok = c and f_zh and a and inis
    print(f"\nV6 往返查询 -> {'PASS' if ok else 'FAIL'}")
    print(f"\n索引库: {DB}")


if __name__ == "__main__":
    main()
