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

import numpy as np

from sump.memory.base import MemoryProvider


class DeepMemory(MemoryProvider):
    """深层长期记忆，SQLite 持久化 + 向量语义检索。

    使用方式::

        deep = DeepMemory("data/deep.db")
        await deep.store("event_1", "用户要求删除生产数据库",
                          embedding=[0.1, 0.2, ...], category="关键事件")
        results = await deep.search("数据库删除操作", top_k=5)
    """

    def __init__(
        self,
        db_path: str = "data/deep.db",
        embedding_model: str = "BAAI/bge-small-zh-v1.5",
        embedder: Any = None,
        embedder_cache_dir: str | None = None,
    ) -> None:
        self.db_path = db_path
        self.embedding_model = embedding_model
        self._embedder = embedder
        self._embedder_cache_dir = embedder_cache_dir
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
                    priority INTEGER NOT NULL DEFAULT 0,
                    embedding TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_access REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            self._ensure_column(db, "deep_memory", "priority", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "deep_memory", "access_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "deep_memory", "last_access", "REAL NOT NULL DEFAULT 0")
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_deep_category
                ON deep_memory(category)
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_deep_created
                ON deep_memory(created_at)
            """)
            try:
                db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS deep_memory_fts
                    USING fts5(key UNINDEXED, content, tokenize='trigram')
                """)
            except Exception:
                pass
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, decl: str) -> None:
        """旧库迁移：缺列则 ALTER TABLE 补上。"""
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

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
        priority = int(kwargs.get("priority", 0))
        meta = kwargs.get("metadata", {})

        # 未显式提供向量且 value 是文本时，自动本地生成
        if not embedding and isinstance(value, str):
            vecs = self._embed_texts(self._get_embedder(), [value])
            if vecs:
                embedding = vecs[0]

        db = self._conn()
        try:
            db.execute(
                """INSERT OR REPLACE INTO deep_memory
                   (key, value, category, priority, embedding, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    json.dumps(value, ensure_ascii=False),
                    category,
                    priority,
                    json.dumps(embedding),
                    json.dumps(meta, ensure_ascii=False),
                    time.time(),
                ),
            )
            self._fts_upsert(db, key, value if isinstance(value, str) else str(value))
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
            self._fts_delete(db, key)
            db.commit()
        finally:
            db.close()

    async def clear(self) -> None:
        """清空所有深层记忆。"""
        db = self._conn()
        try:
            db.execute("DELETE FROM deep_memory")
            try:
                db.execute("DELETE FROM deep_memory_fts")
            except Exception:
                pass
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 语义检索
    # ------------------------------------------------------------------

    async def search(
        self, query: str, top_k: int = 10, *, query_embedding: list[float] | None = None
    ) -> list[dict[str, Any]]:
        """混合检索：向量余弦 + FTS5 BM25 经 RRF 融合排序。"""
        if query_embedding is None and query:
            vecs = self._embed_texts(self._get_embedder(), [query])
            if vecs:
                query_embedding = vecs[0]

        db = self._conn()
        try:
            rows = db.execute(
                "SELECT key, value, category, priority, embedding, metadata, access_count, last_access, created_at "
                "FROM deep_memory ORDER BY created_at DESC"
            ).fetchall()
            bm25_ranks = self._bm25_ranks(db, query) if query else {}
        finally:
            db.close()

        if not rows:
            return []

        results: list[dict[str, Any]] = []
        for key, value, category, priority, emb_json, meta_json, access_count, last_access, created_at in rows:
            results.append({
                "key": key,
                "value": json.loads(value),
                "category": category,
                "priority": priority,
                "embedding": json.loads(emb_json) if emb_json else [],
                "metadata": json.loads(meta_json),
                "access_count": access_count,
                "last_access": last_access,
                "created_at": created_at,
                "score": 0.0,
            })

        vector_ranks: dict[str, int] = {}
        if query_embedding:
            vector_ranks = self._vector_ranks(results, query_embedding)
        self._rrf_fuse(results, vector_ranks, bm25_ranks)
        self._apply_access_weight(results)

        result = results[:top_k]
        self._touch(result)
        return result

    async def search_by_category(
        self, category: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """按分类检索记忆（不排序）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT key, value, category, priority, embedding, metadata, created_at "
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
                "priority": r[3],
                "embedding": json.loads(r[4]) if r[4] else [],
                "metadata": json.loads(r[5]),
                "created_at": r[6],
            }
            for r in rows
        ]

    def list_all(self) -> list[dict[str, Any]]:
        """列出全部深层记忆（按创建时间倒序）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT key, value, category, priority, embedding, metadata, access_count, last_access, created_at "
                "FROM deep_memory ORDER BY created_at DESC"
            ).fetchall()
        finally:
            db.close()
        return [
            {
                "key": r[0],
                "value": json.loads(r[1]),
                "category": r[2],
                "priority": r[3],
                "embedding": json.loads(r[4]) if r[4] else [],
                "metadata": json.loads(r[5]),
                "access_count": r[6],
                "last_access": r[7],
                "created_at": r[8],
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

    # ------------------------------------------------------------------
    # 本地 embedding
    # ------------------------------------------------------------------

    def _get_embedder(self) -> Any:
        """懒加载本地 embedding 模型（可注入自定义实现）。"""
        if self._embedder is None:
            from sump.memory.embedder import Embedder

            self._embedder = Embedder(cache_dir=self._embedder_cache_dir)
        return self._embedder

    @staticmethod
    def _embed_texts(embedder: Any, texts: list[str]) -> list[list[float]]:
        """调用 embedder 生成向量，失败时返回空列表。"""
        try:
            vectors = embedder.embed(texts)
        except Exception:
            return []
        result: list[list[float]] = []
        for v in vectors:
            result.append([float(x) for x in np.asarray(v, dtype=np.float32)])
        return result

    @staticmethod
    def _rank_by_cosine(
        results: list[dict[str, Any]], query_embedding: list[float]
    ) -> None:
        """numpy 批量余弦相似度，原地写回 score 并按降序排序。"""
        q = np.asarray(query_embedding, dtype=np.float32)
        dim = q.shape[0]
        idx = [i for i, r in enumerate(results) if len(r["embedding"]) == dim]
        if not idx:
            return
        matrix = np.array(
            [results[i]["embedding"] for i in idx], dtype=np.float32
        )
        q_norm = float(np.linalg.norm(q))
        denom = np.linalg.norm(matrix, axis=1) * q_norm
        denom[denom == 0] = 1e-12
        scores = (matrix @ q) / denom
        for i, s in zip(idx, scores):
            results[i]["score"] = float(s)
        results.sort(key=lambda x: x["score"], reverse=True)

    # ------------------------------------------------------------------
    # 过期回收
    # ------------------------------------------------------------------

    async def delete_expired(self, retention_days: int) -> int:
        """删除过期深层记忆；从未访问的按一半保留期删除；80% 安全阈值防误删。"""
        if retention_days < 3:
            return 0
        cutoff = time.time() - retention_days * 86400
        half_cutoff = time.time() - (retention_days / 2) * 86400
        db = self._conn()
        try:
            total = db.execute("SELECT COUNT(*) FROM deep_memory").fetchone()[0]
            expired = db.execute(
                "SELECT COUNT(*) FROM deep_memory WHERE created_at < ? "
                "OR (access_count = 0 AND created_at < ?)",
                (cutoff, half_cutoff),
            ).fetchone()[0]
            if total == 0 or expired / total > 0.8:
                return 0
            cur = db.execute(
                "DELETE FROM deep_memory WHERE created_at < ? "
                "OR (access_count = 0 AND created_at < ?)",
                (cutoff, half_cutoff),
            )
            try:
                db.execute(
                    "DELETE FROM deep_memory_fts WHERE key NOT IN (SELECT key FROM deep_memory)"
                )
            except Exception:
                pass
            db.commit()
            return cur.rowcount
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 混合检索（FTS5 + 向量 RRF）
    # ------------------------------------------------------------------

    def _bm25_ranks(self, db: sqlite3.Connection, query: str) -> dict[str, int]:
        """FTS5 BM25 召回，返回 key → 排名（1 起）。不可用或过短时返回空。"""
        safe = query.replace('"', " ").strip()
        if len(safe) < 3:
            return {}
        try:
            rows = db.execute(
                "SELECT key FROM deep_memory_fts WHERE deep_memory_fts MATCH ? "
                "ORDER BY bm25(deep_memory_fts) LIMIT 200",
                (f'"{safe}"',),
            ).fetchall()
        except Exception:
            return {}
        return {key: i + 1 for i, (key,) in enumerate(rows)}

    @staticmethod
    def _vector_ranks(
        results: list[dict[str, Any]], query_embedding: list[float]
    ) -> dict[str, int]:
        """向量余弦召回，返回 key → 排名（1 起）。"""
        q = np.asarray(query_embedding, dtype=np.float32)
        dim = q.shape[0]
        scored = [
            (i, r["key"]) for i, r in enumerate(results)
            if len(r["embedding"]) == dim
        ]
        if not scored:
            return {}
        matrix = np.array(
            [results[i]["embedding"] for i, _ in scored], dtype=np.float32
        )
        q_norm = float(np.linalg.norm(q))
        denom = np.linalg.norm(matrix, axis=1) * q_norm
        denom[denom == 0] = 1e-12
        scores = (matrix @ q) / denom
        ranked = sorted(zip([k for _, k in scored], scores), key=lambda x: -x[1])
        return {key: i + 1 for i, (key, _) in enumerate(ranked)}

    @staticmethod
    def _rrf_fuse(
        results: list[dict[str, Any]],
        vector_ranks: dict[str, int],
        bm25_ranks: dict[str, int],
        k: int = 60,
    ) -> None:
        """RRF 融合：score = Σ 1/(k+rank)，原地写回并按降序排序。"""
        for r in results:
            score = 0.0
            if r["key"] in vector_ranks:
                score += 1.0 / (k + vector_ranks[r["key"]])
            if r["key"] in bm25_ranks:
                score += 1.0 / (k + bm25_ranks[r["key"]])
            r["score"] = score
        results.sort(key=lambda x: x["score"], reverse=True)

    @staticmethod
    def _apply_access_weight(results: list[dict[str, Any]], k: float = 0.1) -> None:
        """访问频次加权：越常召回越靠前（遗忘曲线的巩固效应）。"""
        for r in results:
            r["score"] = r["score"] * (1 + k * math.log1p(r.get("access_count", 0)))

    def _touch(self, results: list[dict[str, Any]]) -> None:
        """召回即访问：被召回的记忆 access_count+1、刷新 last_access。"""
        if not results:
            return
        db = self._conn()
        try:
            db.executemany(
                "UPDATE deep_memory SET access_count = access_count + 1, last_access = ? WHERE key = ?",
                [(time.time(), r["key"]) for r in results],
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _fts_upsert(db: sqlite3.Connection, key: str, content: str) -> None:
        try:
            db.execute("DELETE FROM deep_memory_fts WHERE key = ?", (key,))
            db.execute(
                "INSERT INTO deep_memory_fts (key, content) VALUES (?, ?)",
                (key, content),
            )
        except Exception:
            pass

    @staticmethod
    def _fts_delete(db: sqlite3.Connection, key: str) -> None:
        try:
            db.execute("DELETE FROM deep_memory_fts WHERE key = ?", (key,))
        except Exception:
            pass
