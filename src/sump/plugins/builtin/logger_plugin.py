"""内置日志插件"""

from typing import Any


class LoggerPlugin:
    """默认日志记录插件"""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    async def on_event(self, event: dict[str, Any]) -> None:
        """记录事件"""
        self._events.append(event)
