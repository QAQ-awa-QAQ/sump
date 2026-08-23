"""DeepSeek V4 API 客户端"""

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncGenerator, Callable
from typing import Any, TypeVar

from openai import AsyncOpenAI

from sump.config import Config

logger = logging.getLogger("sump.deepseek")

_T = TypeVar("_T")

_RETRYABLE = (
    "rate_limit", "server_error", "timeout", "connection",
)


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
        self._vision_model = config.get("deepseek.vision_model", "deepseek-v4-flash-vision-exp")
        self._reasoning_effort = config.get("deepseek.reasoning_effort", "high")
        self._thinking_enabled = config.get("deepseek.thinking_enabled", False)
        self._max_tokens = config.get("deepseek.max_tokens", 4096)
        self._temperature = config.get("deepseek.temperature", 1.0)
        self._max_retries = config.get("deepseek.max_retries", 3)
        self._retry_delay = config.get("deepseek.retry_delay", 1.0)

    # ------------------------------------------------------------------
    # 重试 + 公共构建
    # ------------------------------------------------------------------

    async def _retry_call(self, coro_factory: Callable[[], Any], description: str = "API call") -> Any:  # noqa: ANN401
        """指数退避重试。"""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await coro_factory()
            except Exception as e:
                last_exc = e
                msg = str(e).lower()
                is_retryable = any(kw in msg for kw in _RETRYABLE)
                if not is_retryable or attempt == self._max_retries - 1:
                    raise
                delay = self._retry_delay * (2 ** attempt)
                logger.warning(
                    "%s 失败 (attempt %d/%d): %s，%0.1fs 后重试",
                    description, attempt + 1, self._max_retries, e, delay,
                )
                await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    def _build_kwargs(self, messages: list[dict[str, Any]], stream: bool,
                      tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "max_tokens": self._max_tokens,
        }
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if self._thinking_enabled else "disabled"}
        }
        if self._thinking_enabled:
            kwargs["reasoning_effort"] = self._reasoning_effort
        else:
            kwargs["temperature"] = self._temperature
        if tools:
            kwargs["tools"] = tools
        return kwargs

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
        """发送对话请求（带重试），返回完整响应字典。"""
        kwargs = self._build_kwargs(messages, stream, tools)

        async def _call() -> dict[str, Any]:
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            msg = choice.message
            content = msg.content or ""
            tool_calls = self._serialize_tool_calls(msg.tool_calls)
            if not tool_calls:
                # DeepSeek V4 有时把工具调用以 XML 文本放在 content 里
                tool_calls = self._parse_xml_tool_calls(content)
                if tool_calls:
                    content = ""
            return {
                "content": content,
                "reasoning_content": getattr(msg, "reasoning_content", None),
                "tool_calls": tool_calls,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            }

        return await self._retry_call(_call, "DeepSeek chat")  # type: ignore[no-any-return]

    async def chat_text(self, messages: list[dict[str, Any]]) -> str:
        """简化接口：只返回文本回复内容。"""
        result = await self.chat(messages)
        return str(result["content"])

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        """轻量快速调用：独立会话 + flash 模型 + 不思考，文字进文字出。"""
        kwargs: dict[str, Any] = {
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": text}],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        async def _call() -> str:
            response = await self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        return await self._retry_call(_call, "DeepSeek flash")  # type: ignore[no-any-return]

    async def chat_vision(
        self, text: str, image_url: str, *, max_tokens: int = 1024
    ) -> str:
        """视觉模型：图片 + 文本 → 文本描述（仅图像工具用，主模型不受影响）。"""
        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }]

        kwargs: dict[str, Any] = {
            "model": self._vision_model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "extra_body": {"thinking": {"type": "disabled"}},
        }

        async def _call() -> str:
            response = await self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        return await self._retry_call(_call, "DeepSeek vision")  # type: ignore[no-any-return]

    async def chat_stream(
        self, messages: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式对话（带重试建立连接），逐 token 产出。"""
        kwargs = self._build_kwargs(messages, True, None)

        async def _call() -> Any:
            return await self._client.chat.completions.create(**kwargs)

        stream = await self._retry_call(_call, "DeepSeek stream")
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

    @staticmethod
    def _parse_xml_tool_calls(content: str) -> list[dict[str, Any]] | None:
        """解析 DeepSeek V4 放在 content 里的 XML 格式工具调用。

        形如::

            <tool_calls><invoke name="image_vision">
            <parameter name="image">...</parameter>
            </invoke></tool_calls>
        """
        if "<tool_calls>" not in content:
            return None
        calls: list[dict[str, Any]] = []
        for idx, m in enumerate(
            re.finditer(r'<invoke\s+name="([^"]+)">(.*?)</invoke>', content, re.DOTALL)
        ):
            name = m.group(1)
            body = m.group(2)
            params: dict[str, Any] = {}
            for pm in re.finditer(
                r'<parameter\s+name="([^"]+)">(.*?)</parameter>', body, re.DOTALL
            ):
                params[pm.group(1)] = pm.group(2)
            calls.append({
                "id": f"xml_{idx}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(params, ensure_ascii=False),
                },
            })
        return calls or None


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
