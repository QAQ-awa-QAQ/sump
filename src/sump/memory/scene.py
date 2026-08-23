"""场景记忆（L2：围绕场景聚合的原子记忆总结）"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np

from sump.memory.embedder import cosine_scores


class SceneMemory:
    """场景层长期记忆，SQLite 存储场景块（name + summary）。"""

    def __init__(
        self,
        db_path: str = "data/scene.db",
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
                CREATE TABLE IF NOT EXISTS scene_memory (
                    name       TEXT PRIMARY KEY,
                    summary    TEXT NOT NULL,
                    priority   INTEGER NOT NULL DEFAULT 0,
                    embedding  TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            self._ensure_column(db, "scene_memory", "embedding", "TEXT NOT NULL DEFAULT ''")
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, decl: str) -> None:
        """旧库迁移：缺列则 ALTER TABLE 补上。"""
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def upsert_scene(self, name: str, summary: str, priority: int = 0) -> None:
        """写入或覆盖一个场景块。"""
        now = time.time()
        embedding = self._embed_content(summary)
        db = self._conn()
        try:
            db.execute(
                """INSERT INTO scene_memory (name, summary, priority, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     summary = excluded.summary,
                     priority = excluded.priority,
                     embedding = excluded.embedding,
                     updated_at = excluded.updated_at""",
                (name, summary, priority, json.dumps(embedding), now, now),
            )
            db.commit()
        finally:
            db.close()

    def list_scenes(self, limit: int = 50) -> list[dict[str, Any]]:
        """列出场景块，按 priority 降序。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT name, summary, priority, embedding, created_at, updated_at "
                "FROM scene_memory ORDER BY priority DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            db.close()
        return [
            {
                "name": r[0],
                "summary": r[1],
                "priority": r[2],
                "embedding": json.loads(r[3]) if r[3] else [],
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]

    def delete_expired(self, retention_days: int) -> int:
        """删除超过保留期的场景块；80% 安全阈值防误删。"""
        if retention_days < 3:
            return 0
        cutoff = time.time() - retention_days * 86400
        db = self._conn()
        try:
            total = db.execute("SELECT COUNT(*) FROM scene_memory").fetchone()[0]
            expired = db.execute(
                "SELECT COUNT(*) FROM scene_memory WHERE updated_at < ?", (cutoff,)
            ).fetchone()[0]
            if total == 0 or expired / total > 0.8:
                return 0
            cur = db.execute("DELETE FROM scene_memory WHERE updated_at < ?", (cutoff,))
            db.commit()
            return cur.rowcount
        finally:
            db.close()

    def _dump_metadata(self) -> str:
        """供调试：返回场景列表的 JSON。"""
        return json.dumps(self.list_scenes(), ensure_ascii=False)

    # ------------------------------------------------------------------
    # 语义检索
    # ------------------------------------------------------------------

    def search(
        self, query: str, top_k: int = 10, *, query_embedding: list[float] | None = None
    ) -> list[dict[str, Any]]:
        """向量余弦语义检索；无向量时回退 priority 降序。"""
        if query_embedding is None and query:
            vecs = self._embed_texts([query])
            if vecs:
                query_embedding = vecs[0]

        scenes = self.list_scenes()
        if not scenes:
            return []

        if query_embedding:
            dim = len(query_embedding)
            idx = [
                i for i, s in enumerate(scenes)
                if len(s.get("embedding", [])) == dim
            ]
            if idx:
                matrix = np.array(
                    [scenes[i]["embedding"] for i in idx], dtype=np.float32
                )
                scores = cosine_scores(query_embedding, matrix)
                for i, s in zip(idx, scores):
                    scenes[i]["score"] = float(s)
                scenes.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                return scenes[:top_k]

        scenes.sort(key=lambda x: x.get("priority", 0), reverse=True)
        return scenes[:top_k]

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
