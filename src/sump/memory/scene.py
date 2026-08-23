"""场景记忆（L2：围绕场景聚合的原子记忆总结）"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SceneMemory:
    """场景层长期记忆，SQLite 存储场景块（name + summary）。"""

    def __init__(self, db_path: str = "data/scene.db") -> None:
        self._path = Path(db_path)
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
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def upsert_scene(self, name: str, summary: str, priority: int = 0) -> None:
        """写入或覆盖一个场景块。"""
        now = time.time()
        db = self._conn()
        try:
            db.execute(
                """INSERT INTO scene_memory (name, summary, priority, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     summary = excluded.summary,
                     priority = excluded.priority,
                     updated_at = excluded.updated_at""",
                (name, summary, priority, now, now),
            )
            db.commit()
        finally:
            db.close()

    def list_scenes(self, limit: int = 50) -> list[dict[str, Any]]:
        """列出场景块，按 priority 降序。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT name, summary, priority, created_at, updated_at "
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
                "created_at": r[3],
                "updated_at": r[4],
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
