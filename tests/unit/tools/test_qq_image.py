"""QQ 发图工具测试：send_qq_image"""

import pytest

from sump.tools.builtin.qq_image import SendQQImageTool


class _FakeSender:
    """模拟 NapCatPlugin.send_image_to。"""

    def __init__(self, error: str | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._error = error

    async def send_image_to(self, session_id: str, image_path: str, text: str = "") -> str | None:
        self.calls.append((session_id, image_path, text))
        return self._error


class TestSendQQImageTool:
    @pytest.mark.asyncio
    async def test_send_success(self, tmp_path):
        pic = tmp_path / "cat.png"
        pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
        sender = _FakeSender()
        tool = SendQQImageTool(sender, "group_123")

        out = await tool.execute(image=str(pic), text="看这个")
        assert "已发送" in out
        assert sender.calls == [("group_123", str(pic), "看这个")]

    @pytest.mark.asyncio
    async def test_missing_image_param(self, tmp_path):
        sender = _FakeSender()
        out = await SendQQImageTool(sender, "group_123").execute()
        assert "错误" in out
        assert sender.calls == []

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        sender = _FakeSender()
        out = await SendQQImageTool(sender, "group_123").execute(image=str(tmp_path / "none.png"))
        assert "找不到图片" in out
        assert sender.calls == []

    @pytest.mark.asyncio
    async def test_sender_error(self, tmp_path):
        pic = tmp_path / "cat.png"
        pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
        sender = _FakeSender(error="QQ 未连接")
        out = await SendQQImageTool(sender, "group_123").execute(image=str(pic))
        assert "发送失败" in out
        assert "QQ 未连接" in out
