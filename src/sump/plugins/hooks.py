"""钩子系统（事件监听）"""

from collections import defaultdict
from typing import Any, Callable


class HookSystem:
    """事件钩子系统"""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """注册事件监听"""
        self._hooks[event].append(callback)

    async def emit(self, event: str, **kwargs: Any) -> list[Any]:
        """触发事件"""
        results = []
        for callback in self._hooks.get(event, []):
            if hasattr(callback, "__await__"):
                results.append(await callback(**kwargs))
            else:
                results.append(callback(**kwargs))
        return results
