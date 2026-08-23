"""图像理解工具测试"""

import pytest

from sump.tools.builtin.image_vision import ImageVisionTool


class _FakeLLM:
    async def chat_vision(self, text, image_url, *, max_tokens=1024):
        return f"描述({image_url})"


class TestToImageUrl:
    def test_http_passthrough(self):
        assert ImageVisionTool._to_image_url("http://x.com/a.jpg") == "http://x.com/a.jpg"
        assert ImageVisionTool._to_image_url("https://x.com/a.png") == "https://x.com/a.png"

    def test_local_png(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"data")
        url = ImageVisionTool._to_image_url(str(p))
        assert url.startswith("data:image/png;base64,")

    def test_local_jpeg(self, tmp_path):
        p = tmp_path / "a.jpg"
        p.write_bytes(b"\xff\xd8\xff" + b"data")
        url = ImageVisionTool._to_image_url(str(p))
        assert url.startswith("data:image/jpeg;base64,")

    def test_missing_file(self):
        assert ImageVisionTool._to_image_url("nope.jpg") is None


class TestExecute:
    @pytest.mark.asyncio
    async def test_calls_vision(self):
        tool = ImageVisionTool(_FakeLLM())
        result = await tool.execute(image="http://x.com/a.jpg", question="图里有啥")
        assert "http://x.com/a.jpg" in result

    @pytest.mark.asyncio
    async def test_missing_image(self):
        tool = ImageVisionTool(_FakeLLM())
        assert "缺少图片" in await tool.execute(image="")

    @pytest.mark.asyncio
    async def test_unreadable_image(self):
        tool = ImageVisionTool(_FakeLLM())
        assert "无法读取" in await tool.execute(image="nope.jpg")
