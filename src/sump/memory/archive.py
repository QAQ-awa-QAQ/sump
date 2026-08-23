"""记忆归档（历史会话副本，智能体本体不可见）

睡眠巩固时，已提取的会话消息复制到此归档库，
随后从会话记忆中清除——智能体本体（SessionMemory）完全不接触归档库。
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class ArchiveMemory:
    """历史会话归档存储（独立 SQLite 库）。"""

    def __init__(self, db_path: str = "data/archive.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS archived_messages (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT    NOT NULL,
                    name         TEXT    NOT NULL DEFAULT '',
                    role         TEXT    NOT NULL,
                    content      TEXT    NOT NULL,
                    tool_call_id TEXT    NOT NULL DEFAULT '',
                    tool_calls   TEXT,
                    reasoning_content TEXT NOT NULL DEFAULT '',
                    archived_at  REAL    NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_archive_session
                ON archived_messages(session_id, id)
            """)
            try:
                db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS archived_messages_fts
                    USING fts5(session_id UNINDEXED, content, tokenize='trigram')
                """)
            except Exception:
                pass
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def archive_session(
        self, session_id: str, name: str, messages: list[dict[str, Any]]
    ) -> int:
        """归档一个会话的全部消息，返回写入条数。"""
        if not messages:
            return 0
        db = self._conn()
        try:
            db.executemany(
                "INSERT INTO archived_messages "
                "(session_id, name, role, content, tool_call_id, tool_calls, reasoning_content, archived_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        name,
                        m.get("role", ""),
                        m.get("content", ""),
                        m.get("tool_call_id", ""),
                        json.dumps(m["tool_calls"], ensure_ascii=False)
                        if m.get("tool_calls")
                        else None,
                        m.get("reasoning_content", ""),
                        time.time(),
                    )
                    for m in messages
                ],
            )
            try:
                db.executemany(
                    "INSERT INTO archived_messages_fts (session_id, content) VALUES (?, ?)",
                    [(session_id, m.get("content", "")) for m in messages],
                )
            except Exception:
                pass
            db.commit()
            return len(messages)
        finally:
            db.close()

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        """读回某会话的归档副本（按时间正序）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT role, content, tool_call_id, tool_calls, reasoning_content "
                "FROM archived_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        finally:
            db.close()

        result: list[dict[str, Any]] = []
        for role, content, tci, tcs, reasoning in rows:
            entry: dict[str, Any] = {"role": role, "content": content}
            if tci:
                entry["tool_call_id"] = tci
            if tcs:
                entry["tool_calls"] = json.loads(tcs)
            if reasoning:
                entry["reasoning_content"] = reasoning
            result.append(entry)
        return result

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出归档会话（session_id + 标题 + 条数）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT session_id, name, COUNT(*) FROM archived_messages "
                "GROUP BY session_id ORDER BY MAX(archived_at) DESC"
            ).fetchall()
        finally:
            db.close()
        return [
            {"id": r[0], "name": r[1], "msg_count": r[2]} for r in rows
        ]

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """FTS5 全文检索归档会话消息，返回命中消息（session_id + content）。"""
        safe = query.replace('"', " ").strip()
        if len(safe) < 2:
            return []
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT session_id, content FROM archived_messages_fts "
                "WHERE archived_messages_fts MATCH ? "
                "ORDER BY bm25(archived_messages_fts) LIMIT ?",
                (f'"{safe}"', top_k),
            ).fetchall()
        except Exception:
            return []
        finally:
            db.close()
        return [{"session_id": r[0], "content": r[1]} for r in rows]
