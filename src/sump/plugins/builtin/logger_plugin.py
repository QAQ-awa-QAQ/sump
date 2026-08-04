"""内置日志插件"""


class LoggerPlugin:
    """默认日志记录插件"""

    def __init__(self):
        self._events: list[dict] = []

    async def on_event(self, event: dict) -> None:
        """记录事件"""
        self._events.append(event)
