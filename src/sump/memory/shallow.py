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
                    priority   INTEGER NOT NULL DEFAULT 0,
                    metadata   TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                )
            """)
            self._ensure_column(db, "shallow_memory", "priority", "INTEGER NOT NULL DEFAULT 0")
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_shallow_category
                ON shallow_memory(category)
            """)
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, decl: str) -> None:
        """旧库迁移：缺列则 ALTER TABLE 补上。"""
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def add_entry(
        self, category: str, content: str,
        metadata: dict[str, Any] | None = None, priority: int = 0,
    ) -> int:
        """添加一条浅层记忆，返回条目 ID。"""
        db = self._conn()
        try:
            cur = db.execute(
                "INSERT INTO shallow_memory (category, content, priority, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (category, content, priority, json.dumps(metadata or {}, ensure_ascii=False), time.time()),
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
                    "SELECT id, category, content, priority, metadata, created_at "
                    "FROM shallow_memory ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, category, content, priority, metadata, created_at "
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
                "priority": r[3],
                "metadata": json.loads(r[4]),
                "created_at": r[5],
            }
            for r in rows
        ]

    def list_all_entries(self) -> list[dict[str, Any]]:
        """列出全部浅层记忆条目（按 id 倒序）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT id, category, content, priority, metadata, created_at "
                "FROM shallow_memory ORDER BY id DESC"
            ).fetchall()
        finally:
            db.close()
        return [
            {
                "id": r[0],
                "category": r[1],
                "content": r[2],
                "priority": r[3],
                "metadata": json.loads(r[4]),
                "created_at": r[5],
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

    def delete_expired(self, retention_days: int) -> int:
        """删除超过保留期的条目；80% 安全阈值防误删，返回删除条数。"""
        if retention_days < 3:
            return 0
        cutoff = time.time() - retention_days * 86400
        db = self._conn()
        try:
            total = db.execute("SELECT COUNT(*) FROM shallow_memory").fetchone()[0]
            expired = db.execute(
                "SELECT COUNT(*) FROM shallow_memory WHERE created_at < ?", (cutoff,)
            ).fetchone()[0]
            if total == 0 or expired / total > 0.8:
                return 0
            cur = db.execute("DELETE FROM shallow_memory WHERE created_at < ?", (cutoff,))
            db.commit()
            return cur.rowcount
        finally:
            db.close()
