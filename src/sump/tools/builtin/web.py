"""HTTP 璇锋眰宸ュ叿"""

from sump.tools.base import Tool
from typing import Any


class WebTool(Tool):
    name = "web"
    description = "Make HTTP requests"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "method": {"type": "string", "enum": ["GET", "POST"]},
        },
        "required": ["url"],
    }

    async def execute(self, **kwargs) -> Any:
        pass