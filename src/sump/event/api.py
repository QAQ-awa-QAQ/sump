"""对外事件流（SUMPAPI，兼容保留）"""

from collections.abc import Callable
from typing import Any


class SUMPAPI:
    """对外暴露的事件流接口"""

    def __init__(self) -> None:
        self._listeners: list[Callable[..., Any]] = []

    def subscribe(self, listener: Callable[..., Any]) -> None:
        """订阅事件流"""
        self._listeners.append(listener)

    async def publish(self, event: dict[str, Any]) -> None:
        """发布事件"""
        for listener in self._listeners:
            await listener(event)
