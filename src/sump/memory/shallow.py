"""浅层记忆（SQLite 分类条目）

存储跨会话的浅层长期记忆，按类别归档：
情景 / 语义 / 工作流 / error。
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np

from sump.memory.embedder import cosine_scores


class ShallowMemory:
    """浅层长期记忆，SQLite 分类条目存储。

    使用方式::

        mem = ShallowMemory("data/shallow.db")
        entry_id = mem.add_entry("语义", "用户喜欢 Python", {"source": "chat"})
        entries = mem.list_entries("语义", limit=20)
    """

    def __init__(
        self,
        db_path: str = "data/shallow.db",
        embedder: Any = None,
        embedder_cache_dir: str | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._embedder = embedder
        self._embedder_cache_dir = embedder_cache_dir
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
                    embedding  TEXT NOT NULL DEFAULT '',
                    metadata   TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                )
            """)
            self._ensure_column(db, "shallow_memory", "priority", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "shallow_memory", "embedding", "TEXT NOT NULL DEFAULT ''")
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
        embedding = self._embed_content(content)
        db = self._conn()
        try:
            cur = db.execute(
                "INSERT INTO shallow_memory (category, content, priority, embedding, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (category, content, priority, json.dumps(embedding), json.dumps(metadata or {}, ensure_ascii=False), time.time()),
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
                "SELECT id, category, content, priority, embedding, metadata, created_at "
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
                "embedding": json.loads(r[4]) if r[4] else [],
                "metadata": json.loads(r[5]),
                "created_at": r[6],
            }
            for r in rows
        ]

    def list_entries_since(self, min_id: int, limit: int = 1000) -> list[dict[str, Any]]:
        """列出 id > min_id 的浅层条目（按 id 正序）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT id, category, content, priority, embedding, metadata, created_at "
                "FROM shallow_memory WHERE id > ? ORDER BY id ASC LIMIT ?",
                (min_id, limit),
            ).fetchall()
        finally:
            db.close()
        return [
            {
                "id": r[0],
                "category": r[1],
                "content": r[2],
                "priority": r[3],
                "embedding": json.loads(r[4]) if r[4] else [],
                "metadata": json.loads(r[5]),
                "created_at": r[6],
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

    def search(
        self, query: str, top_k: int = 10, *, query_embedding: list[float] | None = None
    ) -> list[dict[str, Any]]:
        """向量余弦语义检索；无向量时回退 priority 降序。"""
        if query_embedding is None and query:
            vecs = self._embed_texts([query])
            if vecs:
                query_embedding = vecs[0]

        entries = self.list_all_entries()
        if not entries:
            return []

        if query_embedding:
            dim = len(query_embedding)
            idx = [
                i for i, e in enumerate(entries)
                if len(e.get("embedding", [])) == dim
            ]
            if idx:
                matrix = np.array(
                    [entries[i]["embedding"] for i in idx], dtype=np.float32
                )
                scores = cosine_scores(query_embedding, matrix)
                for i, s in zip(idx, scores):
                    entries[i]["score"] = float(s)
                entries.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                return entries[:top_k]

        entries.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return entries[:top_k]

    # ------------------------------------------------------------------
    # 本地 embedding
    # ------------------------------------------------------------------

    def _embed_content(self, content: str) -> list[float]:
        vecs = self._embed_texts([content])
        return vecs[0] if vecs else []

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        embedder = self._get_embedder()
        if embedder is None:
            return []
        try:
            result: list[list[float]] = []
            for v in embedder.embed(texts):
                result.append([float(x) for x in np.asarray(v, dtype=np.float32)])
            return result
        except Exception:
            return []

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            from sump.memory.embedder import Embedder

            self._embedder = Embedder(cache_dir=self._embedder_cache_dir)
        return self._embedder
