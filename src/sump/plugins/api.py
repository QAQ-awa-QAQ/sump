"""SUMP_API锛堜簨浠舵祦鏆撮湶锛?""


class SUMPAPI:
    """瀵瑰鏆撮湶鐨?API 鎺ュ彛"""

    def __init__(self):
        self._listeners: list = []

    def subscribe(self, listener) -> None:
        self._listeners.append(listener)

    async def publish(self, event: dict) -> None:
        for listener in self._listeners:
            await listener(event)