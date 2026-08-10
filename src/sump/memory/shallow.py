"""长期-浅层记忆（SQLite 持久化）"""

import json
import sqlite3
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
        reasoning_content: str = "",
    ) -> None:
        """保存一条消息。"""
        db = self._conn()
        try:
            db.execute(
                "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, reasoning_content) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, tool_call_id,
                 json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                 reasoning_content),
            )
            db.commit()
        finally:
            db.close()

    def load_messages(
        self, session_id: str = "default", limit: int = 50
    ) -> list[dict[str, Any]]:
        """加载指定会话的最近 N 条消息。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT role, content, tool_call_id, tool_calls, reasoning_content "
                "FROM messages WHERE session_id = ? "
                "ORDER BY id ASC LIMIT ?",
                (session_id, limit),
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
        """列出所有会话（含会话名）。"""
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT m.session_id, s.name, MIN(m.created_at) AS first, COUNT(*) AS cnt "
                "FROM messages m "
                "LEFT JOIN sessions s ON m.session_id = s.session_id "
                "GROUP BY m.session_id ORDER BY first DESC"
            ).fetchall()
        finally:
            db.close()
        return [
            {"id": sid, "name": name or sid[:8], "msg_count": cnt, "created_at": first}
            for sid, name, first, cnt in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        """删除一个会话的全部消息与会话名。"""
        db = self._conn()
        try:
            db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            db.commit()
            return True
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 会话名管理
    # ------------------------------------------------------------------

    def upsert_session_name(self, session_id: str, name: str) -> None:
        """写入或覆盖会话名。"""
        db = self._conn()
        try:
            db.execute(
                "INSERT INTO sessions (session_id, name) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET name = excluded.name",
                (session_id, name),
            )
            db.commit()
        finally:
            db.close()

    def get_session_name(self, session_id: str) -> str | None:
        """读取会话名，无记录返回 None。"""
        db = self._conn()
        try:
            row = db.execute(
                "SELECT name FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row[0] if row else None
        finally:
            db.close()

    def update_tool_message(self, session_id: str, tool_call_id: str, content: str) -> None:
        """更新指定 tool_call 的消息内容（审批后替换待确认文本）。"""
        db = self._conn()
        try:
            cur = db.execute(
                "UPDATE messages SET content = ? WHERE session_id = ? AND tool_call_id = ? AND role = 'tool'",
                (content, session_id, tool_call_id),
            )
            db.commit()
            print(f"[INFO][db] update_tool_message | session={session_id} tci={tool_call_id} rows={cur.rowcount} content={content[:60]}", flush=True)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self._path))
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT    NOT NULL DEFAULT 'default',
                    role         TEXT    NOT NULL,
                    content      TEXT    NOT NULL,
                    tool_call_id TEXT    NOT NULL DEFAULT '',
                    tool_calls   TEXT,
                    reasoning_content TEXT NOT NULL DEFAULT '',
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_session "
                "ON messages(session_id, id)"
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                    session_id   TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                )"""
            )
            db.commit()
        finally:
            db.close()
