"""定时等待器（agent 自主阻断，用于等待耗时终端任务）"""

import asyncio
from typing import Any

from sump.tools.base import Tool


class WaitTool(Tool):
    """阻塞等待指定秒数，用于等待 docker 构建、服务启动等耗时任务。"""

    name = "wait"
    description = (
        "阻塞等待指定秒数，期间不执行其他操作。"
        "用于等待耗时任务完成（如 docker 构建、服务启动、安装依赖），等待后再检查结果。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "seconds": {
                "type": "integer",
                "description": "等待秒数（1~600，超上限自动截断）",
            },
        },
        "required": ["seconds"],
    }

    def __init__(self, max_seconds: int = 600) -> None:
        self._max_seconds = max(1, max_seconds)

    async def execute(self, **kwargs: Any) -> str:
        try:
            seconds = int(kwargs.get("seconds", 1))
        except (TypeError, ValueError):
            seconds = 1
        seconds = max(1, min(seconds, self._max_seconds))
        await asyncio.sleep(seconds)
        return f"已等待 {seconds} 秒"
