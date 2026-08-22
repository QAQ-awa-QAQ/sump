"""工作记忆（智能体的任务便签）

记录当前任务的目标与过程。后端可配置：
- memory：纯内存
- disk：SQLite 持久化
容量按字节限制，每次写入后检查大小，超出则丢弃最旧的过程记录。
"""

import sqlite3
import time
from pathlib import Path


class WorkingMemory:
    """工作记忆：智能体的任务便签，记录当前任务的过程与目标。

    使用方式::

        wm = WorkingMemory(backend="disk", max_bytes=102400)
        wm.set_goal("修复登录 bug")
        wm.add_note("定位到 token 过期")
    """

    def __init__(
        self,
        backend: str = "disk",
        max_bytes: int = 102400,
        db_path: str = "data/working.db",
    ) -> None:
        self._backend = backend
        self._max_bytes = max_bytes
        self._path = Path(db_path)
        self._goal = ""
        self._notes: list[str] = []
        if backend == "disk":
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    # ------------------------------------------------------------------
    # 目标
    # ------------------------------------------------------------------

    def set_goal(self, goal: str) -> None:
        """设置当前任务目标。"""
        self._goal = goal
        if self._backend == "disk":
            self._upsert_kind("goal", goal)
        self._trim()

    def get_goal(self) -> str:
        """获取当前任务目标。"""
        if self._backend == "disk":
            return self._read_kind("goal")
        return self._goal

    # ------------------------------------------------------------------
    # 过程记录
    # ------------------------------------------------------------------

    def add_note(self, note: str) -> None:
        """追加一条过程记录。"""
        if self._backend == "disk":
            self._insert("note", note)
        else:
            self._notes.append(note)
        self._trim()

    def get_notes(self) -> list[str]:
        """获取全部过程记录（按时间正序）。"""
        if self._backend == "disk":
            return self._list_kind("note")
        return list(self._notes)

    def clear(self) -> None:
        """清空便签。"""
        self._goal = ""
        self._notes.clear()
        if self._backend == "disk":
            db = self._conn()
            try:
                db.execute("DELETE FROM working_memory")
                db.commit()
            finally:
                db.close()

    # ------------------------------------------------------------------
    # 内部：SQLite 存储
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS working_memory (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            db.commit()
        finally:
            db.close()

    def _upsert_kind(self, kind: str, content: str) -> None:
        db = self._conn()
        try:
            db.execute("DELETE FROM working_memory WHERE kind = ?", (kind,))
            db.execute(
                "INSERT INTO working_memory (kind, content, created_at) VALUES (?, ?, ?)",
                (kind, content, time.time()),
            )
            db.commit()
        finally:
            db.close()

    def _insert(self, kind: str, content: str) -> None:
        db = self._conn()
        try:
            db.execute(
                "INSERT INTO working_memory (kind, content, created_at) VALUES (?, ?, ?)",
                (kind, content, time.time()),
            )
            db.commit()
        finally:
            db.close()

    def _read_kind(self, kind: str) -> str:
        db = self._conn()
        try:
            row = db.execute(
                "SELECT content FROM working_memory WHERE kind = ? "
                "ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
            return row[0] if row else ""
        finally:
            db.close()

    def _list_kind(self, kind: str) -> list[str]:
        db = self._conn()
        try:
            rows = db.execute(
                "SELECT content FROM working_memory WHERE kind = ? ORDER BY id ASC",
                (kind,),
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 内部：容量（字节）
    # ------------------------------------------------------------------

    def _current_bytes(self) -> int:
        """当前占用字节数。disk 后端查询文件大小，memory 后端按 UTF-8 字节估算。"""
        if self._backend == "disk":
            try:
                return self._path.stat().st_size
            except FileNotFoundError:
                return 0
        total = len(self._goal.encode("utf-8"))
        total += sum(len(n.encode("utf-8")) for n in self._notes)
        return total

    def _trim(self) -> None:
        """超出字节上限后丢弃最旧的过程记录。"""
        while self._current_bytes() > self._max_bytes:
            if not self._drop_oldest():
                break

    def _drop_oldest(self) -> bool:
        """丢弃最旧一条过程记录；无记录可丢时清空目标。"""
        if self._backend == "disk":
            db = self._conn()
            try:
                cur = db.execute(
                    "DELETE FROM working_memory WHERE id = ("
                    "SELECT id FROM working_memory WHERE kind = 'note' "
                    "ORDER BY id ASC LIMIT 1)"
                )
                if cur.rowcount > 0:
                    db.commit()
                    return True
                cur = db.execute("DELETE FROM working_memory WHERE kind = 'goal'")
                db.commit()
                return cur.rowcount > 0
            finally:
                db.close()
        if self._notes:
            self._notes.pop(0)
            return True
        if self._goal:
            self._goal = ""
            return True
        return False
