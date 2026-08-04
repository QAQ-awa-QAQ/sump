"""SUMP_API（事件流暴露）"""


class SUMPAPI:
    """对外暴露的 API 接口"""

    def __init__(self):
        self._listeners: list = []

    def subscribe(self, listener) -> None:
        """订阅事件流"""
        self._listeners.append(listener)

    async def publish(self, event: dict) -> None:
        """发布事件"""
        for listener in self._listeners:
            await listener(event)
