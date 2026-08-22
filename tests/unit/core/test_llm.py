"""LLM 客户端封装测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sump.core.models import LLMClient
from sump.core.models.deepseek import DeepSeekClient


class TestDeepSeekClientFlash:
    @pytest.mark.asyncio
    async def test_chat_flash_isolated_session(self, config):
        """chat_flash：独立会话 + flash 模型 + 不思考 + 文字进文字出。"""
        client = DeepSeekClient(config)
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "标题"

        with patch.object(
            client._client.chat.completions, "create",
            new=AsyncMock(return_value=response),
        ) as mock_create:
            result = await client.chat_flash("总结这个对话", max_tokens=32, temperature=0.3)

        assert result == "标题"
        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "deepseek-v4-flash"
        assert kwargs["messages"] == [{"role": "user", "content": "总结这个对话"}]
        assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert kwargs["max_tokens"] == 32
        assert kwargs["temperature"] == 0.3


class TestLLMClientFlash:
    @pytest.mark.asyncio
    async def test_chat_flash_forwards(self, config):
        """LLMClient.chat_flash 转发到后端，参数正确。"""
        llm = LLMClient(config)
        with patch.object(
            llm._backend, "chat_flash", new=AsyncMock(return_value="回复")
        ) as mock_flash:
            result = await llm.chat_flash("文字", max_tokens=64, temperature=0.5)

        assert result == "回复"
        mock_flash.assert_awaited_once_with("文字", max_tokens=64, temperature=0.5)
