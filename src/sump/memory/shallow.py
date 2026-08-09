"""长期-浅层记忆（SQLite 持久化）"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class ShallowMemory:
    """会话消息持久化，基于 SQLite。

    使用方式::

        mem = ShallowMemory("data/memory.db")
        mem.save_message("default", "user", "你好")
        messages = mem.load_messages("default", limit=50)
    """

    def __init__(self, db_path: str = "data/memory.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_call_id: str = "",
        tool_calls: list[dict] | None = None,
    ) -> None:
        """保存一条消息。"""
        with self._lock:
            db = self._conn()
            try:
                db.execute(
                    "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        role,
                        content,
                        tool_call_id,
                        json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    ),
                )
                db.commit()
            finally:
                db.close()

    def load_messages(
        self, session_id: str = "default", limit: int = 50
    ) -> list[dict[str, Any]]:
        """加载指定会话的最近 N 条消息。"""
        with self._lock, self._conn() as db:
            rows = db.execute(
                "SELECT role, content, tool_call_id, tool_calls "
                "FROM messages WHERE session_id = ? "
                "ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for role, content, tci, tcs in rows:
            entry: dict[str, Any] = {"role": role, "content": content}
            if tci:
                entry["tool_call_id"] = tci
            if tcs:
                entry["tool_calls"] = json.loads(tcs)
            result.append(entry)
        return result

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出所有会话。"""
        with self._lock, self._conn() as db:
            rows = db.execute(
                "SELECT session_id, MIN(created_at) AS first, COUNT(*) AS cnt "
                "FROM messages GROUP BY session_id ORDER BY first DESC"
            ).fetchall()
        return [
            {"id": sid, "msg_count": cnt, "created_at": first}
            for sid, first, cnt in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        """删除一个会话的全部消息。"""
        with self._lock, self._conn() as db:
            cur = db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self._path))
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        with self._lock, self._conn() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT    NOT NULL DEFAULT 'default',
                    role         TEXT    NOT NULL,
                    content      TEXT    NOT NULL,
                    tool_call_id TEXT    NOT NULL DEFAULT '',
                    tool_calls   TEXT,
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_session "
                "ON messages(session_id, id)"
            )
