"""鎼滅储宸ュ叿"""

from sump.tools.base import Tool
from typing import Any


class SearchTool(Tool):
    name = "search"
    description = "Search for information"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs) -> Any:
        pass