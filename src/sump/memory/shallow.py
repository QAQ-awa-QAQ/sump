"""浅层记忆（SQLite 分类条目）

存储跨会话的浅层长期记忆，按类别归档：
情景 / 语义 / 工作流 / error。
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class ShallowMemory:
    """浅层长期记忆，SQLite 分类条目存储。

    使用方式::

        mem = ShallowMemory("data/shallow.db")
        entry_id = mem.add_entry("语义", "用户喜欢 Python", {"source": "chat"})
        entries = mem.list_entries("语义", limit=20)
    """

    def __init__(self, db_path: str = "data/shallow.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS shallow_memory (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    category   TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    metadata   TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_shallow_category
                ON shallow_memory(category)
            """)
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def add_entry(
        self, category: str, content: str, metadata: dict[str, Any] | None = None
    ) -> int:
        """添加一条浅层记忆，返回条目 ID。"""
        db = self._conn()
        try:
            cur = db.execute(
                "INSERT INTO shallow_memory (category, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?)",
                (category, content, json.dumps(metadata or {}, ensure_ascii=False), time.time()),
            )
            db.commit()
            return int(cur.lastrowid)
        finally:
            db.close()

    def list_entries(
        self, category: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """列出浅层记忆条目，可按类别过滤，返回最新 limit 条。"""
        db = self._conn()
        try:
            if category is None:
                rows = db.execute(
                    "SELECT id, category, content, metadata, created_at "
                    "FROM shallow_memory ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, category, content, metadata, created_at "
                    "FROM shallow_memory WHERE category = ? ORDER BY id DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
        finally:
            db.close()
        return [
            {
                "id": r[0],
                "category": r[1],
                "content": r[2],
                "metadata": json.loads(r[3]),
                "created_at": r[4],
            }
            for r in rows
        ]

    def remove_entry(self, entry_id: int) -> bool:
        """删除指定条目。"""
        db = self._conn()
        try:
            cur = db.execute("DELETE FROM shallow_memory WHERE id = ?", (entry_id,))
            db.commit()
            return cur.rowcount > 0
        finally:
            db.close()

    def clear(self) -> None:
        """清空所有浅层记忆。"""
        db = self._conn()
        try:
            db.execute("DELETE FROM shallow_memory")
            db.commit()
        finally:
            db.close()
