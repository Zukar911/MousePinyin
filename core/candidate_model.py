"""core/candidate_model.py —— SQLite 只读候选模型（与状态机 duck-typing 接口一致）

接口（StateMachine 依赖的四个方法）：
    initials()           -> list[str]          声母表（频率降序，"" = 零声母）
    finals(initial)      -> list[str]          该声母有效韵母（频率降序）
    candidates(syllable) -> list[str]          该音节候选字（字频降序）
    assoc(prev_char)     -> list[str]          联想候选（词频降序）

显示辅助：
    display_initial(s)   零声母显示为「∅」
    display_final(s)     v→ü（ve→üe / vn→ün / van→üan）
"""

import sqlite3
from pathlib import Path

from core.app_paths import resource_dir

DB_PATH = resource_dir() / "data" / "index.db"


def display_final(f: str) -> str:
    """内部编码 → 显示串（v=ü 系还原）。"""
    return f.replace("van", "üan").replace("ve", "üe").replace("vn", "ün").replace("v", "ü")


def display_initial(s: str) -> str:
    return "∅" if s == "" else s


class CandidateModel:
    def __init__(self, db_path: Path = DB_PATH):
        if not db_path.exists():
            raise FileNotFoundError(
                f"缺少索引库 {db_path} —— 请先运行 tools/validate_index.py 构建数据"
            )
        self.conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        self.conn.execute("PRAGMA query_only=1")

    # ---------- 声母层 ----------

    def initials(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT initial FROM initials ORDER BY weight DESC, initial"
        ).fetchall()
        return [r[0] for r in rows]

    # ---------- 韵母层 ----------

    def finals(self, initial: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT final FROM syllables WHERE initial=? ORDER BY rank", (initial,)
        ).fetchall()
        return [r[0] for r in rows]

    # ---------- 汉字层 ----------

    def candidates(self, syllable: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT hanzi FROM candidates WHERE syllable=? ORDER BY rank", (syllable,)
        ).fetchall()
        return [r[0] for r in rows]

    def candidate_page(self, syllable: str, page: int, size: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT hanzi FROM candidates WHERE syllable=? ORDER BY rank LIMIT ? OFFSET ?",
            (syllable, size, page * size),
        ).fetchall()
        return [r[0] for r in rows]

    # ---------- 联想层 ----------

    def assoc(self, prev: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT next FROM assoc WHERE prev=? ORDER BY rank LIMIT 30", (prev,)
        ).fetchall()
        return [r[0] for r in rows]

    def close(self):
        self.conn.close()
