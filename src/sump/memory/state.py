"""巩固状态（增量游标持久化）"""

import sqlite3
from pathlib import Path


class ConsolidationState:
    """睡眠巩固的增量游标，SQLite 单表 key-value 存储。"""

    def __init__(self, db_path: str = "data/state.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.commit()
        finally:
            db.close()

    def get(self, key: str, default: int = 0) -> int:
        """读取游标，无记录返回 default。"""
        db = self._conn()
        try:
            row = db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            return int(row[0]) if row else default
        finally:
            db.close()

    def set(self, key: str, value: int) -> None:
        """写入游标。"""
        db = self._conn()
        try:
            db.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            db.commit()
        finally:
            db.close()
