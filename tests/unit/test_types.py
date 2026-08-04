"""绫诲瀷瀹氫箟娴嬭瘯"""

from sump.types import MemoryType, Message, MemoryEntry


class TestMemoryType:
    def test_enum_values(self):
        assert MemoryType.WORKING == "working"
        assert MemoryType.SHALLOW == "shallow"


class TestMessage:
    def test_create_message(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"


class TestMemoryEntry:
    def test_create_entry(self):
        entry = MemoryEntry(id="1", type=MemoryType.WORKING, content="test")
        assert entry.id == "1"
        assert entry.type == MemoryType.WORKING