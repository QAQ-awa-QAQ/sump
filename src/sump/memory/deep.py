"""长期-深层记忆（SQLite + 向量语义检索）

持久化关键事件、重大错误、黑名单等深层记忆，
支持基于 embedding 的语义相似度检索。
"""

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from sump.memory.base import MemoryProvider


class DeepMemory(MemoryProvider):
    """深层长期记忆，SQLite 持久化 + 向量语义检索。

    使用方式::

        deep = DeepMemory("data/memory.db")
        await deep.store("event_1", "用户要求删除生产数据库",
                          embedding=[0.1, 0.2, ...], category="关键事件")
        results = await deep.search("数据库删除操作", top_k=5)
    """

    def __init__(
        self,
        db_path: str = "data/memory.db",
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self.db_path = db_path
        self.embedding_model = embedding_model
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # 数据库初始化
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS deep_memory (
                    key      TEXT PRIMARY KEY,
                    value    TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    embedding TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_deep_category
                ON deep_memory(category)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_deep_created
                ON deep_memory(created_at)
            """)
            db.commit()
        finally:
            db.close()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    # ------------------------------------------------------------------
    # MemoryProvider 接口
    # ------------------------------------------------------------------

    async def store(self, key: str, value: Any, **kwargs: Any) -> None:
        """存储深层记忆。

        kwargs:
            embedding: list[float] 向量表示
            category: str 分类标签（关键事件/重大error/黑名单）
            metadata: dict 附加元数据
        """
        embedding = kwargs.get("embedding", [])
        category = kwargs.get("category", "")
        meta = kwargs.get("metadata", {})

        db = self._conn()
        try:
            db.execute(
                """INSERT OR REPLACE INTO deep_memory
                   (key, value, category, embedding, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    json.dumps(value, ensure_ascii=False),
                    category,
                    json.dumps(embedding),
                    json.dumps(meta, ensure_ascii=False),
                    time.time(),
                ),
            )
            db.commit()
        finally:
            db.close()

    async def retrieve(self, key: str, **kwargs: Any) -> Any | None:
        """按键检索深层记忆。"""
        db = self._conn()
        try:
            row = db.execute(
                "SELECT value FROM deep_memory WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        finally:
            db.close()

    async def forget(self, key: str) -> None:
        """删除指定记忆。"""
        db = self._conn()
        try:
            db.execute("DELETE FROM deep_memory WHERE key = ?", (key,))
            db.commit()
        finally:
            db.close()

    async def clear(self) -> None:
        """清空所有深层记忆。"""
        db = self._conn()
        try:
            db.execute("DELETE FROM deep_memory")
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 语义检索
    # ------------------------------------------------------------------

    async def search(
        self, query: str, top_k: int = 10, *, query_embedding: list[float] | None = None
    ) -> list[dict[str, Any]]:
        """语义搜索：按向量余弦相似度排序。

        如果未提供 query_embedding，则回退到全表返回
        （调用方应先通过 embedding API 获取向量）。
        """
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT key, value, category, embedding, metadata, created_at "
                "FROM deep_memory ORDER BY created_at DESC"
            ).fetchall()
        finally:
            db.close()

        if not rows:
            return []

        results: list[dict[str, Any]] = []
        for key, value, category, emb_json, meta_json, created_at in rows:
            results.append({
                "key": key,
                "value": json.loads(value),
                "category": category,
                "embedding": json.loads(emb_json) if emb_json else [],
                "metadata": json.loads(meta_json),
                "created_at": created_at,
                "score": 0.0,
            })

        # 向量相似度排序
        if query_embedding:
            for r in results:
                r["score"] = self._cosine_similarity(query_embedding, r["embedding"])
            results.sort(key=lambda x: x["score"], reverse=True)

        return results[:top_k]

    async def search_by_category(
        self, category: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """按分类检索记忆（不排序）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT key, value, category, embedding, metadata, created_at "
                "FROM deep_memory WHERE category = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        finally:
            db.close()

        return [
            {
                "key": r[0],
                "value": json.loads(r[1]),
                "category": r[2],
                "embedding": json.loads(r[3]) if r[3] else [],
                "metadata": json.loads(r[4]),
                "created_at": r[5],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """纯 Python 余弦相似度。"""
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
