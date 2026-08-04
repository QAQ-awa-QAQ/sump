"""鍐呯疆鏃ュ織鎻掍欢"""


class LoggerPlugin:
    """榛樿鏃ュ織璁板綍鎻掍欢"""

    def __init__(self):
        self._events: list[dict] = []

    async def on_event(self, event: dict) -> None:
        self._events.append(event)