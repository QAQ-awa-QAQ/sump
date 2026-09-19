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
from sump.settings import load_settings

logger = logging.getLogger("sump.deepseek")

_T = TypeVar("_T")

_RETRYABLE = (
    "rate_limit", "server_error", "timeout", "connection",
)

# 支持多模态输入的模型：图片作为 content 块直发主模型，无需额外识图工具
_VISION_CAPABLE_MODELS = ("deepseek-flash",)

# 模型输出偶尔泄漏"标记文本"形态的伪工具调用：词元被全角竖线（U+FF5C，
# 偶见半角竖线）包裹，外观像 XML 标签。此类内容按硬性限制处理：
#   1) 一律不解析为工具调用（禁止使用，见 _parse_xml_tool_calls）；
#   2) 输出前清洗剥离，绝不外发给用户（QQ/CLI），也不写入对话上下文。
_MARK_TOKEN = re.compile(r"[\uff5c|]\s{0,2}DSML\s{0,2}[\uff5c|]")


def sanitize_marked_output(text: str) -> str:
    """清洗模型输出中泄漏的标记文本（含标记的整行剔除）。

    - 不含标记特征：原样返回；
    - 含标记特征：剔除相关行并去除首尾空白（可能整段清空）。
    """
    if not _MARK_TOKEN.search(text):
        return text
    kept = [ln for ln in text.splitlines() if not _MARK_TOKEN.search(ln)]
    return "\n".join(kept).strip()


def supports_vision(model: str) -> bool:
    """主模型是否支持多模态输入（图片直通，无需 image_vision 工具）。"""
    name = str(model or "").lower()
    return any(name.startswith(prefix) for prefix in _VISION_CAPABLE_MODELS)


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
        # settings.json 是最高优先级层，但传入的 config 可能只是启动时的快照
        # （长生命周期组件持有旧 config，用户设置中心保存后不会自动更新）。
        # 对设置中心管理的字段再叠加一次最新值，保证"保存之后才创建"的客户端
        # （新会话 / 新 QQ 群 Agent 等）不会拿到过期的 Key 或模型名。
        fresh = load_settings().get("deepseek", {})
        self._api_key = str(
            fresh.get("api_key")
            or config.get("deepseek.api_key")
            or os.getenv("DEEPSEEK_API_KEY", "")
        )
        self._base_url = str(
            fresh.get("base_url")
            or config.get("deepseek.base_url", "https://api.deepseek.com")
        )
        # 空 Key 时用占位符保证客户端可构造（服务可启动，用户可在设置中心填 Key）
        self._client = AsyncOpenAI(
            api_key=self._api_key or "sk-not-configured", base_url=self._base_url
        )
        self._model = fresh.get("model") or config.get("deepseek.model", "deepseek-flash")
        self._vision_model = (
            fresh.get("vision_model")
            or config.get("deepseek.vision_model", "deepseek-flash")
        )
        self._flash_model = str(
            fresh.get("flash_model") or config.get("deepseek.flash_model", "deepseek-flash")
        )
        self._reasoning_effort = config.get("deepseek.reasoning_effort", "high")
        self._thinking_enabled = config.get("deepseek.thinking_enabled", False)
        self._max_tokens = config.get("deepseek.max_tokens", 4096)
        self._temperature = config.get("deepseek.temperature", 1.0)
        self._max_retries = config.get("deepseek.max_retries", 3)
        self._retry_delay = config.get("deepseek.retry_delay", 1.0)

    def apply_settings(self, settings: dict[str, Any]) -> None:
        """应用设置中心变更（热更新：重建 API 客户端 + 更新各环节模型名）。"""
        api_key = str(settings.get("api_key") or self._api_key)
        base_url = str(settings.get("base_url") or self._base_url)
        if api_key != self._api_key or base_url != self._base_url:
            self._api_key = api_key
            self._base_url = base_url
            self._client = AsyncOpenAI(
                api_key=api_key or "sk-not-configured", base_url=base_url
            )
        if settings.get("model"):
            self._model = str(settings["model"])
        if settings.get("vision_model"):
            self._vision_model = str(settings["vision_model"])
        if settings.get("flash_model"):
            self._flash_model = str(settings["flash_model"])

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
            # 标记文本形态的伪调用：不解析、不执行，直接清洗剥离（禁止使用）
            cleaned = sanitize_marked_output(content)
            if cleaned != content:
                logger.warning(
                    "检测到模型输出泄漏标记文本，已清洗（%d→%d 字符）",
                    len(content), len(cleaned),
                )
                content = cleaned
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
            "model": self._flash_model,
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
                # 逐块清洗（跨块残片由执行器/Agent 的全文级清洗兜底）
                text = sanitize_marked_output(delta.content)
                if text:
                    yield {"type": "content", "text": text}

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

        注意：被特殊标记词元（全角竖线包裹）的伪调用文本一律不解析，
        属于禁止使用形态，只做清洗剥离（见 sanitize_marked_output）。
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
