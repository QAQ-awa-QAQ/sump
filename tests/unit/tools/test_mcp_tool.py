"""MCP 工具包装与自动注册测试"""

import pytest

from sump.tools.mcp.tool import MCPTool, register_mcp_tools
from sump.tools.registry import ToolRegistry


class _FakeClient:
    def __init__(self, tools: list[dict]) -> None:
        self._tools = tools
        self.calls: list[tuple] = []

    async def list_tools(self, server_name: str) -> list[dict]:
        return self._tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict):
        self.calls.append((server_name, tool_name, arguments))
        return {"content": [{"type": "text", "text": f"result of {tool_name}"}], "isError": False}


class TestMCPTool:
    @pytest.mark.asyncio
    async def test_execute_calls_remote(self):
        client = _FakeClient([])
        tool = MCPTool(
            client,
            "srv",
            "read",
            "读文件",
            {"type": "object", "properties": {"path": {"type": "string"}}},
        )
        result = await tool.execute(path="/tmp/x")
        assert "result of read" in result
        assert client.calls == [("srv", "read", {"path": "/tmp/x"})]

    @pytest.mark.asyncio
    async def test_register_mcp_tools(self):
        client = _FakeClient([
            {
                "name": "t1",
                "description": "d1",
                "inputSchema": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "required": ["a"],
                },
            },
            {"name": "t2", "description": "d2", "inputSchema": None},
        ])
        registry = ToolRegistry()
        names = await register_mcp_tools(registry, client, "srv")

        assert names == ["t1", "t2"]
        assert registry.get("t1").name == "t1"
        assert registry.get("t1").parameters["required"] == ["a"]
        assert registry.get("t2").parameters == {"type": "object", "properties": {}}
