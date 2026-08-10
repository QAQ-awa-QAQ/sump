"""工具注册表（自注册）"""

from typing import Any

from sump.tools.base import Tool


class ToolRegistry:
    """工具自注册表"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """获取工具"""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """列出所有工具"""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """获取所有工具的 OpenAI schema"""
        return [t.to_openai_schema() for t in self._tools.values()]
