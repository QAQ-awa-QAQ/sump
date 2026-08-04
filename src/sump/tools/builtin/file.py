"""鏂囦欢璇诲啓宸ュ叿"""

from sump.tools.base import Tool
from typing import Any


class FileTool(Tool):
    name = "file"
    description = "Read and write files"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write"]},
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["action", "path"],
    }

    async def execute(self, **kwargs) -> Any:
        pass