"""pytest 配置与 fixture"""

import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest

# 测试环境：不需要真实 API key
os.environ.setdefault("DEEPSEEK_API_KEY", "test-dummy-key")

from sump.config import Config
from sump.core.context import Context
from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config()
    # 隔离数据库路径，避免测试污染项目 data/ 目录
    memory = cfg._data.setdefault("memory", {})
    for key, filename in (
        ("session", "session.db"),
        ("shallow", "shallow.db"),
        ("deep", "deep.db"),
        ("scene", "scene.db"),
        ("working", "working.db"),
    ):
        node = memory.setdefault(key, {})
        node["db_path"] = str(tmp_path / filename)
    return cfg


@pytest.fixture
def ctx(config: Config) -> Context:
    return Context(config)


@pytest.fixture
def tools() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    return reg


class _EchoTool(Tool):
    """测试用回显工具。"""
    name = "echo"
    description = "Echo back the input"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo"},
        },
        "required": ["text"],
    }

    async def execute(self, text: str = "", **kwargs: Any) -> str:
        return f"echo: {text}"


class MockLLMClient:
    """模拟 LLM，返回预设回复。"""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = responses or [{"content": "mock response", "tool_calls": None}]
        self._idx = 0
        self.calls: list[dict[str, Any]] = []

    async def chat_full(
        self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "tools": tools})
        resp = self.responses[min(self._idx, len(self.responses) - 1)]
        self._idx += 1
        return resp

    async def chat_stream(
        self, messages: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        yield {"type": "content", "text": "mock stream response"}


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return MockLLMClient()
