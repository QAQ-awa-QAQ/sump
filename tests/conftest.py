"""pytest 配置与 fixture"""

import os
import tempfile
from collections.abc import AsyncGenerator
from typing import Any

import pytest

# 测试环境：不需要真实 API key
os.environ.setdefault("DEEPSEEK_API_KEY", "test-dummy-key")
# 测试环境：隔离全局运行时设置（避免本地 data/settings.json 影响用例）
os.environ.setdefault(
    "SUMP_SETTINGS_FILE", os.path.join(tempfile.gettempdir(), "sump_test_settings.json")
)
# 测试环境：HF 离线（fastembed 初始化会访问 huggingface.co，无网时长时间等待）
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from sump.config import Config
from sump.core.context import Context
from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry


@pytest.fixture
def config(tmp_path, monkeypatch) -> Config:
    # 隔离全局运行时设置到临时目录（写读均不影响项目）
    monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
    cfg = Config()
    # 隔离数据库路径，避免测试污染项目 data/ 目录
    memory = cfg._data.setdefault("memory", {})
    for key, filename in (
        ("session", "session.db"),
        ("shallow", "shallow.db"),
        ("deep", "deep.db"),
        ("scene", "scene.db"),
        ("archive", "archive.db"),
        ("state", "state.db"),
        ("working", "working.db"),
    ):
        node = memory.setdefault(key, {})
        node["db_path"] = str(tmp_path / filename)
    # 默认不启用主人标记过滤（专门测试用 owner_marker）
    memory["owner_marker"] = ""
    # 隔离资产库（目录 + 索引库）
    assets = cfg._data.setdefault("assets", {})
    assets["dir"] = str(tmp_path / "assets")
    assets["db_path"] = str(tmp_path / "assets.db")
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


@pytest.fixture(autouse=True)
def _isolated_event_bus(tmp_path):
    """每个测试用独立的 event.db，避免污染项目 data/ 目录。"""
    import sump.event.bus as bus_module

    previous = bus_module._singleton
    bus_module._singleton = bus_module.EventBus(str(tmp_path / "event.db"))
    yield
    bus_module._singleton = previous


@pytest.fixture(autouse=True)
def _no_mcp(monkeypatch):
    """测试默认禁用 MCP 子进程（npx 冷启动慢且会泄漏，拖挂整个测试会话）。"""
    from sump.tools.mcp.client import MCPClient

    async def _disabled_connect(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("MCP disabled in tests")

    monkeypatch.setattr(MCPClient, "connect", _disabled_connect)
