"""工具索引（agent 忘记有哪些工具时查询）"""

from typing import Any

from sump.tools.base import Tool
from sump.tools.registry import ToolRegistry


class ToolIndexTool(Tool):
    """返回当前可用工具列表，供 agent 忘记工具时查询。"""

    name = "list_tools"
    description = (
        "列出当前可用的所有工具及其用途。"
        "当不确定有哪些工具可用、或需要确认某个操作是否有对应工具时调用此工具。"
    )
    parameters = {"type": "object", "properties": {}}

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, **kwargs: Any) -> str:
        lines = [f"- {t.name}: {t.description}" for t in self._registry.list_all()]
        return "\n".join(lines) if lines else "当前无可用工具"
