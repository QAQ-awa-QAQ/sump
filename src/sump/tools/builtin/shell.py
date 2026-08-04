"""Shell 命令工具"""

from typing import Any

from sump.tools.base import Tool


class ShellTool(Tool):
    name = "shell"
    description = "执行 Shell 命令"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
        },
        "required": ["command"],
    }

    async def execute(self, **kwargs) -> Any:
        pass
