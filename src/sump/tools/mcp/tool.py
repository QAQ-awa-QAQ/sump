"""MCP 工具包装：把 MCP 服务器工具注册进 ToolRegistry。"""

import json
from typing import Any

from sump.tools.base import Tool


def _schema_to_parameters(input_schema: dict[str, Any] | None) -> dict[str, Any]:
    """MCP inputSchema（JSON Schema）→ OpenAI function parameters。"""
    if not isinstance(input_schema, dict):
        return {"type": "object", "properties": {}}
    return {
        "type": "object",
        "properties": input_schema.get("properties", {}) or {},
        "required": input_schema.get("required", []) or [],
    }


class MCPTool(Tool):
    """包装一个 MCP 服务器工具，execute 时远程调用。"""

    def __init__(
        self,
        client: Any,
        server_name: str,
        name: str,
        description: str = "",
        parameters: dict[str, Any] | None = None,
        sandbox: Any = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self._client = client
        self._server_name = server_name
        self._sandbox = sandbox

    async def execute(self, **kwargs: Any) -> str:
        if self._sandbox is not None:
            result = await self._sandbox.run(self._call, **kwargs)
            if not result.get("ok"):
                return f"工具执行失败：{result.get('error')}"
            return str(result.get("result"))
        return await self._call(**kwargs)

    async def _call(self, **kwargs: Any) -> str:
        result = await self._client.call_tool(self._server_name, self.name, dict(kwargs))
        content = result.get("content", result) if isinstance(result, dict) else result
        return json.dumps(content, ensure_ascii=False)


async def register_mcp_tools(
    registry: Any, client: Any, server_name: str, sandbox: Any = None
) -> list[str]:
    """发现并注册某 MCP 服务器的全部工具，返回注册的工具名列表。"""
    tools = await client.list_tools(server_name)
    registered: list[str] = []
    for spec in tools:
        name = str(spec.get("name", ""))
        if not name:
            continue
        registry.register(MCPTool(
            client=client,
            server_name=server_name,
            name=name,
            description=str(spec.get("description", "")),
            parameters=_schema_to_parameters(spec.get("inputSchema")),
            sandbox=sandbox,
        ))
        registered.append(name)
    return registered
