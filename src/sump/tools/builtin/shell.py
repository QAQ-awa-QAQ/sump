"""Shell 鍛戒护宸ュ叿"""

from sump.tools.base import Tool
from typing import Any


class ShellTool(Tool):
    name = "shell"
    description = "Execute shell commands"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
        },
        "required": ["command"],
    }

    async def execute(self, **kwargs) -> Any:
        pass