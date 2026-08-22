"""浅层记忆测试"""

from sump.memory.shallow import ShallowMemory


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
