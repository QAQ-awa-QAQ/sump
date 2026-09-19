"""归档存储测试"""

from sump.memory.archive import ArchiveMemory


class TestArchiveMemory:
    def test_archive_and_load(self, tmp_path):
        archive = ArchiveMemory(str(tmp_path / "archive.db"))
        msgs = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
            {"role": "tool", "content": "ok", "tool_call_id": "t1"},
        ]
        assert archive.archive_session("s1", "测试会话", msgs) == 3
        loaded = archive.load_messages("s1")
        assert len(loaded) == 3
        assert loaded[0]["content"] == "你好"
        assert loaded[2]["tool_call_id"] == "t1"

    def test_archive_multimodal_roundtrip(self, tmp_path):
        """多模态消息：图片块可归档并读回；FTS 索引文本而非 base64。"""
        archive = ArchiveMemory(str(tmp_path / "archive.db"))
        blocks = [
            {"type": "text", "text": "看这张图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]
        assert archive.archive_session("s1", "图", [{"role": "user", "content": blocks}]) == 1

        loaded = archive.load_messages("s1")
        assert loaded[0]["content"] == blocks
        assert len(archive.search("看这张图")) >= 1

    def test_archive_empty(self, tmp_path):
        archive = ArchiveMemory(str(tmp_path / "archive.db"))
        assert archive.archive_session("s1", "空", []) == 0

    def test_list_sessions(self, tmp_path):
        archive = ArchiveMemory(str(tmp_path / "archive.db"))
        archive.archive_session("s1", "A", [{"role": "user", "content": "x"}])
        archive.archive_session("s2", "B", [{"role": "user", "content": "y"}])
        sessions = archive.list_sessions()
        assert len(sessions) == 2
        names = {s["name"] for s in sessions}
        assert names == {"A", "B"}

    def test_search(self, tmp_path):
        archive = ArchiveMemory(str(tmp_path / "archive.db"))
        archive.archive_session(
            "s1", "A", [{"role": "user", "content": "用户喜欢 Python 编程"}]
        )
        results = archive.search("Python")
        assert len(results) >= 1
        assert "Python" in results[0]["content"]
