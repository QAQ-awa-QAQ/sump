"""搜索工具"""

from typing import Any

from sump.tools.base import Tool


class SearchTool(Tool):
    name = "search"
    description = "搜索信息"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs: Any) -> Any:
        pass
