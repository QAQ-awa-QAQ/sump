"""LLM 客户端封装 —— 统一入口，按配置选择后端"""

from typing import Any

from sump.config import Config
from sump.core.models.deepseek import DeepSeekClient


class LLMClient:
    """统一的 LLM 调用接口，当前后端为 DeepSeek V4。"""

    def __init__(self, config: Config) -> None:
        self._backend = DeepSeekClient(config)

    async def chat(self, messages: list[dict[str, str]]) -> str:
        """发送对话请求，返回文本回复。"""
        return await self._backend.chat_text(messages)

    async def chat_full(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """发送对话请求，返回完整响应（含 reasoning_content、tool_calls、usage）。"""
        return await self._backend.chat(messages, tools=tools)
