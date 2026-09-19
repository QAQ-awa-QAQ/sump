"""Agent 资产库（表情包等"有意思的东西"）

资产文件存放在 assets/ 目录（可手工维护），SQLite 索引 + FTS5 全文检索。
启动时自动对账扫描（新文件入库 / 失效条目清理），保存时自动索引。
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

# 单个资产大小上限（与图片直通链路保持一致）
MAX_ASSET_BYTES = 32 * 1024 * 1024

# 常见图片格式的 MIME → 扩展名
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def guess_asset_ext(data: bytes, fallback: str = ".bin") -> str:
    """按文件实际内容判断扩展名（图片常见格式，其余用 fallback）。"""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF8"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return fallback


def _kind_of(filename: str) -> str:
    """按扩展名判断资产类型。"""
    suffix = Path(filename).suffix.lower()
    return "image" if suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp") else "other"


class AssetStore:
    """资产库：文件目录 + SQLite 索引（FTS5 全文检索）。"""

    def __init__(self, asset_dir: str = "assets", db_path: str = "data/assets.db") -> None:
        self._dir = Path(asset_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.scan()

    # ------------------------------------------------------------------
    # 数据库
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    def _init_db(self) -> None:
        db = self._conn()
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename    TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    tags        TEXT NOT NULL DEFAULT '[]',
                    kind        TEXT NOT NULL DEFAULT 'other',
                    size        INTEGER NOT NULL DEFAULT 0,
                    hash        TEXT NOT NULL DEFAULT '',
                    created_at  REAL NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_assets_hash ON assets(hash)")
            try:
                db.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts
                    USING fts5(filename, description, tags, tokenize='trigram')
                """)
            except Exception:
                pass
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _fts_upsert(
        db: sqlite3.Connection, asset_id: int, filename: str, description: str, tags_text: str
    ) -> None:
        """同步 FTS 索引行（FTS5 不可用时静默跳过，检索会降级 LIKE）。"""
        try:
            db.execute("DELETE FROM assets_fts WHERE rowid = ?", (asset_id,))
            db.execute(
                "INSERT INTO assets_fts (rowid, filename, description, tags) VALUES (?, ?, ?, ?)",
                (asset_id, filename, description, tags_text),
            )
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _fts_delete(db: sqlite3.Connection, asset_id: int) -> None:
        try:
            db.execute("DELETE FROM assets_fts WHERE rowid = ?", (asset_id,))
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------------------------------
    # 索引维护
    # ------------------------------------------------------------------

    def scan(self) -> dict[str, int]:
        """对账扫描：新文件入库（描述留空待补）、已删文件清条目。"""
        files = {p.name for p in self._dir.iterdir() if p.is_file()}
        added = 0
        removed = 0
        db = self._conn()
        try:
            rows = db.execute("SELECT id, filename FROM assets").fetchall()
            for asset_id, name in rows:
                if name not in files:
                    db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                    self._fts_delete(db, asset_id)
                    removed += 1
            known = {name for _, name in rows if name in files}
            for name in sorted(files - known):
                path = self._dir / name
                cur = db.execute(
                    "INSERT INTO assets "
                    "(filename, description, tags, kind, size, hash, created_at) "
                    "VALUES (?, '', '[]', ?, ?, '', ?)",
                    (name, _kind_of(name), path.stat().st_size, time.time()),
                )
                asset_id = int(cur.lastrowid or 0)
                self._fts_upsert(db, asset_id, name, "", "")
                added += 1
            db.commit()
        finally:
            db.close()
        return {"added": added, "removed": removed}

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    def save_bytes(
        self,
        data: bytes,
        description: str,
        tags: list[str] | None = None,
        ext: str | None = None,
    ) -> dict[str, Any]:
        """保存资产并索引；相同内容已存在时返回已有条目（不重复保存）。"""
        digest = hashlib.md5(data).hexdigest()
        existing = self.find_by_hash(digest)
        if existing is not None:
            existing["duplicated"] = True
            return existing

        suffix = ext or guess_asset_ext(data)
        filename = f"{int(time.time())}_{digest[:8]}{suffix}"
        (self._dir / filename).write_bytes(data)
        tag_list = tags or []
        db = self._conn()
        try:
            try:
                cur = db.execute(
                    "INSERT INTO assets "
                    "(filename, description, tags, kind, size, hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (filename, description, json.dumps(tag_list, ensure_ascii=False),
                     _kind_of(filename), len(data), digest, time.time()),
                )
            except sqlite3.IntegrityError:
                # 并发竞态：另一进程刚写入了同内容（同文件名）→ 返回已有条目
                db.rollback()
                existing = self.find_by_hash(digest)
                if existing is None:
                    raise
                existing["duplicated"] = True
                return existing
            asset_id = int(cur.lastrowid or 0)
            self._fts_upsert(db, asset_id, filename, description, " ".join(tag_list))
            db.commit()
        finally:
            db.close()
        entry = self.get(asset_id)
        assert entry is not None
        entry["duplicated"] = False
        return entry

    def get(self, asset_id: int) -> dict[str, Any] | None:
        """按 id 读取资产条目。"""
        db = self._conn()
        try:
            row = db.execute(
                "SELECT id, filename, description, tags, kind, size, created_at "
                "FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        finally:
            db.close()
        return self._row_to_dict(row) if row else None

    def delete(self, asset_id: int) -> dict[str, Any] | None:
        """删除资产：文件移入 assets/.trash/（可人工恢复），清除索引。"""
        entry = self.get(asset_id)
        if entry is None:
            return None
        src = self._dir / entry["filename"]
        if src.is_file():
            trash = self._dir / ".trash"
            trash.mkdir(exist_ok=True)
            src.replace(trash / f"{int(time.time())}_{entry['filename']}")
        db = self._conn()
        try:
            db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
            self._fts_delete(db, asset_id)
            db.commit()
        finally:
            db.close()
        return entry

    def update(
        self,
        asset_id: int,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """更新资产的描述/标签（语义重命名）；None 表示保持原值。"""
        entry = self.get(asset_id)
        if entry is None:
            return None
        new_desc = entry["description"] if description is None else description
        new_tags = entry["tags"] if tags is None else tags
        db = self._conn()
        try:
            db.execute(
                "UPDATE assets SET description = ?, tags = ? WHERE id = ?",
                (new_desc, json.dumps(new_tags, ensure_ascii=False), asset_id),
            )
            self._fts_upsert(db, asset_id, entry["filename"], new_desc, " ".join(new_tags))
            db.commit()
        finally:
            db.close()
        return self.get(asset_id)

    def find_by_hash(self, digest: str) -> dict[str, Any] | None:
        """按内容哈希查找已有资产（去重用）。"""
        if not digest:
            return None
        db = self._conn()
        try:
            row = db.execute(
                "SELECT id, filename, description, tags, kind, size, created_at "
                "FROM assets WHERE hash = ? AND hash != '' LIMIT 1",
                (digest,),
            ).fetchone()
        finally:
            db.close()
        return self._row_to_dict(row) if row else None

    def search(self, query: str = "", top_k: int = 10) -> list[dict[str, Any]]:
        """检索资产：query 为空列出最近资产；否则 FTS5 全文检索（降级 LIKE）。"""
        safe = query.replace('"', " ").strip()
        db = self._conn()
        try:
            if not safe:
                rows = db.execute(
                    "SELECT id, filename, description, tags, kind, size, created_at "
                    "FROM assets ORDER BY id DESC LIMIT ?",
                    (top_k,),
                ).fetchall()
            else:
                rows = []
                try:
                    rows = db.execute(
                        "SELECT a.id, a.filename, a.description, a.tags, a.kind, "
                        "a.size, a.created_at "
                        "FROM assets_fts f JOIN assets a ON a.id = f.rowid "
                        "WHERE assets_fts MATCH ? ORDER BY bm25(assets_fts) LIMIT ?",
                        (f'"{safe}"', top_k),
                    ).fetchall()
                except Exception:
                    rows = []
                if not rows:
                    like = f"%{safe}%"
                    rows = db.execute(
                        "SELECT id, filename, description, tags, kind, size, created_at "
                        "FROM assets WHERE description LIKE ? OR filename LIKE ? OR tags LIKE ? "
                        "ORDER BY id DESC LIMIT ?",
                        (like, like, like, top_k),
                    ).fetchall()
        finally:
            db.close()
        return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row: tuple[Any, ...]) -> dict[str, Any]:
        asset_id, filename, description, tags, kind, size, created_at = row
        try:
            tag_list = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tag_list = []
        return {
            "id": asset_id,
            "filename": filename,
            "description": description,
            "tags": tag_list if isinstance(tag_list, list) else [],
            "kind": kind,
            "size": size,
            "path": str(self._dir / filename),
            "created_at": created_at,
        }
