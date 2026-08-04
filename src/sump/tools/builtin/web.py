"""HTTP 请求工具"""

from typing import Any

from sump.tools.base import Tool


class WebTool(Tool):
    name = "web"
    description = "发送 HTTP 请求"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "目标 URL"},
            "method": {"type": "string", "enum": ["GET", "POST"]},
        },
        "required": ["url"],
    }

    async def execute(self, **kwargs) -> Any:
        pass
