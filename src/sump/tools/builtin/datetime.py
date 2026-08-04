"""鏃堕棿宸ュ叿"""

from datetime import datetime, timezone

from sump.tools.base import Tool
from typing import Any


class DateTimeTool(Tool):
    name = "datetime"
    description = "Get current date and time"
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs) -> Any:
        return datetime.now(timezone.utc).isoformat()