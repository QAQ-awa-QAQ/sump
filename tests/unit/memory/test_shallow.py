"""浅层记忆测试"""

import time

from sump.memory.shallow import ShallowMemory


class _FakeEmbedder:
    """按关键词映射到固定向量，验证语义排序。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for t in texts:
            if "Python" in t:
                result.append([1.0, 0.0, 0.0])
            elif "电影" in t:
                result.append([0.0, 1.0, 0.0])
            else:
                result.append([0.0, 0.0, 1.0])
        return result


class TestShallowMemory:
    def test_add_and_list(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        entry_id = mem.add_entry("语义", "用户喜欢 Python")
        assert entry_id > 0
        entries = mem.list_entries("语义")
        assert entries[0]["content"] == "用户喜欢 Python"

    def test_list_by_category(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        mem.add_entry("语义", "内容A")
        mem.add_entry("error", "内容B")
        assert len(mem.list_entries("语义")) == 1
        assert len(mem.list_entries("error")) == 1
        assert len(mem.list_entries()) == 2

    def test_remove_entry(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        entry_id = mem.add_entry("语义", "内容")
        assert mem.remove_entry(entry_id) is True
        assert mem.list_entries() == []

    def test_clear(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        mem.add_entry("语义", "内容")
        mem.clear()
        assert mem.list_entries() == []

    def test_list_all_entries(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        mem.add_entry("语义", "A")
        mem.add_entry("error", "B")
        assert len(mem.list_all_entries()) == 2

    def test_add_with_priority(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        mem.add_entry("语义", "内容", priority=80)
        assert mem.list_all_entries()[0]["priority"] == 80

    def test_delete_expired(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"))
        mem.add_entry("语义", "旧1", priority=80)
        mem.add_entry("语义", "旧2", priority=80)
        mem.add_entry("语义", "新1", priority=80)
        db = mem._conn()
        db.execute(
            "UPDATE shallow_memory SET created_at = ? WHERE id IN (1, 2)",
            (time.time() - 400 * 86400,),
        )
        db.commit()
        db.close()
        assert mem.delete_expired(365) == 2

    def test_search_vector(self, tmp_path):
        mem = ShallowMemory(str(tmp_path / "shallow.db"), embedder=_FakeEmbedder())
        mem.add_entry("语义", "用户喜欢 Python", priority=50)
        mem.add_entry("语义", "用户喜欢电影", priority=90)
        results = mem.search("Python")
        assert results[0]["content"] == "用户喜欢 Python"
