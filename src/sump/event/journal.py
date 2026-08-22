"""事件记账（SQLite append-only）"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class EventJournal:
    """事件记账：事件按时间戳存档，谁消费追加标签，暂不删除。"""

    def __init__(self, db_path: str = "data/event.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS event_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    event      TEXT NOT NULL,
                    payload    TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS event_consumption (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id    INTEGER NOT NULL,
                    consumer    TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'ok',
                    consumed_at REAL NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS idx_consumption_event
                ON event_consumption(event_id)
            """)
            db.commit()
        finally:
            db.close()

    def record_event(self, event: str, payload: dict[str, Any]) -> int:
        """存档一条事件，返回事件 ID。"""
        db = self._conn()
        try:
            cur = db.execute(
                "INSERT INTO event_log (event, payload, created_at) VALUES (?, ?, ?)",
                (event, json.dumps(payload, ensure_ascii=False, default=str), time.time()),
            )
            db.commit()
            return int(cur.lastrowid)
        finally:
            db.close()

    def mark_consumed(self, event_id: int, consumer: str, status: str = "ok") -> None:
        """为事件追加一条消费标签。"""
        db = self._conn()
        try:
            db.execute(
                "INSERT INTO event_consumption (event_id, consumer, status, consumed_at) "
                "VALUES (?, ?, ?, ?)",
                (event_id, consumer, status, time.time()),
            )
            db.commit()
        finally:
            db.close()
