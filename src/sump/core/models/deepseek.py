"""DeepSeek V4 API 客户端"""

import os
from collections.abc import AsyncGenerator
from typing import Any

from openai import AsyncOpenAI

from sump.config import Config


class DeepSeekClient:
    """DeepSeek V4 API 客户端，基于 OpenAI SDK 调用。

    使用方式::

        config = Config()
        client = DeepSeekClient(config)
        result = await client.chat([{"role": "user", "content": "你好"}])
        print(result["content"])
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        api_key = config.get("deepseek.api_key") or os.getenv("DEEPSEEK_API_KEY", "")
        base_url = config.get("deepseek.base_url", "https://api.deepseek.com")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = config.get("deepseek.model", "deepseek-v4-flash")
        self._reasoning_effort = config.get("deepseek.reasoning_effort", "high")
        self._thinking_enabled = config.get("deepseek.thinking_enabled", False)
        self._max_tokens = config.get("deepseek.max_tokens", 4096)
        self._temperature = config.get("deepseek.temperature", 1.0)

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """发送对话请求，返回完整响应字典。

        Returns:
            {
                "content": str,              # 模型最终回复
                "reasoning_content": str|None,  # 思维链（thinking mode 开启时）
                "tool_calls": list|None,      # 工具调用列表
                "usage": {
                    "prompt_tokens": int,
                    "completion_tokens": int,
                    "total_tokens": int,
                },
            }
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "max_tokens": self._max_tokens,
        }

        # thinking mode：必须显式开关，API 默认是开启的
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"}
        }
        if self._thinking_enabled:
            kwargs["reasoning_effort"] = self._reasoning_effort
        else:
            kwargs["temperature"] = self._temperature

        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        return {
            "content": msg.content or "",
            "reasoning_content": getattr(msg, "reasoning_content", None),
            "tool_calls": self._serialize_tool_calls(msg.tool_calls),
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        }

    async def chat_text(self, messages: list[dict[str, Any]]) -> str:
        """简化接口：只返回文本回复内容。"""
        result = await self.chat(messages)
        return result["content"]

    async def chat_stream(
        self, messages: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式对话，逐 token 产出。

        Yields:
            {"type": "reasoning", "text": "..."}   # 思维链片段
            {"type": "content", "text": "..."}      # 最终回复片段
            {"type": "tool_call", "call": {...}}    # 工具调用
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "max_tokens": self._max_tokens,
        }
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"}
        }
        if self._thinking_enabled:
            kwargs["reasoning_effort"] = self._reasoning_effort
        else:
            kwargs["temperature"] = self._temperature

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "reasoning", "text": reasoning}
            elif delta.tool_calls:
                for tc in delta.tool_calls:
                    yield {"type": "tool_call", "call": {
                        "id": tc.id or "",
                        "name": tc.function.name if tc.function else "",
                        "arguments": tc.function.arguments if tc.function else "",
                    }}
            elif delta.content:
                yield {"type": "content", "text": delta.content}

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_tool_calls(tool_calls: Any) -> list[dict[str, Any]] | None:
        """将 OpenAI SDK 的 tool_calls 对象序列化为普通 dict 列表。"""
        if not tool_calls:
            return None
        return [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]


# ------------------------------------------------------------------
# 自测入口
# ------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def _test() -> None:
        api_key = input("API Key: ").strip()
        if not api_key:
            print("未输入 API Key，退出")
            return

        client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        print("正在测试连接 deepseek-v4-pro ...")

        try:
            response = await client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[{"role": "user", "content": "用一句话介绍你自己"}],
                max_tokens=256,
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}},
            )
            msg = response.choices[0].message
            print(f"\n✅ 连接成功")
            print(f"   model: {response.model}")
            print(f"   reasoning_content: {getattr(msg, 'reasoning_content', '')[:100]}...")
            print(f"   content: {msg.content}")
            if response.usage:
                print(f"   tokens: prompt={response.usage.prompt_tokens} completion={response.usage.completion_tokens}")
        except Exception as e:
            print(f"\n❌ 请求失败: {e}")

    asyncio.run(_test())
