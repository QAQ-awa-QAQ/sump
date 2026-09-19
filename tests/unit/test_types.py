"""类型定义测试"""

from sump.types import (
    MemoryEntry,
    MemoryType,
    Message,
    build_user_content,
    content_has_images,
    content_to_text,
)

IMG = "data:image/png;base64,AAAA"


class TestMemoryType:
    def test_enum_values(self):
        assert MemoryType.WORKING == "working"
        assert MemoryType.SESSION == "session"
        assert MemoryType.SHALLOW == "shallow"
        assert MemoryType.DEEP == "deep"
        assert MemoryType.TASK == "task"


class TestMessage:
    def test_create_message(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_multimodal_content(self):
        """content 支持块数组（text + image_url）。"""
        msg = Message(role="user", content=[{"type": "text", "text": "hi"}])
        assert isinstance(msg.content, list)
        assert msg.content[0]["text"] == "hi"


class TestMultimodalHelpers:
    def test_build_text_only(self):
        assert build_user_content("你好") == "你好"
        assert build_user_content("你好", []) == "你好"

    def test_build_with_images(self):
        assert build_user_content("看这图", [IMG]) == [
            {"type": "text", "text": "看这图"},
            {"type": "image_url", "image_url": {"url": IMG}},
        ]

    def test_build_image_only(self):
        assert build_user_content("", [IMG]) == [
            {"type": "image_url", "image_url": {"url": IMG}},
        ]

    def test_has_images(self):
        assert content_has_images(build_user_content("x", [IMG])) is True
        assert content_has_images("纯文本") is False
        assert content_has_images([{"type": "text", "text": "x"}]) is False

    def test_to_text(self):
        assert content_to_text("纯文本") == "纯文本"
        assert content_to_text(build_user_content("看这图", [IMG])) == "看这图\n[图片]"
        assert content_to_text(build_user_content("", [IMG])) == "[图片]"


class TestMemoryEntry:
    def test_create_entry(self):
        entry = MemoryEntry(id="1", type=MemoryType.SESSION, content="test")
        assert entry.id == "1"
        assert entry.type == MemoryType.SESSION
