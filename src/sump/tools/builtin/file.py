"""文件读写工具"""

from sump.tools.base import Tool
from typing import Any


class FileTool(Tool):
    name = "file"
    description = "读取和写入文件"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write"]},
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["action", "path"],
    }

    async def execute(self, **kwargs: Any) -> Any:
        pass
