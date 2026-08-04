"""閽╁瓙绯荤粺锛堜簨浠剁洃鍚級"""

from collections import defaultdict
from typing import Any, Callable


class HookSystem:
    """浜嬩欢閽╁瓙绯荤粺"""

    def __init__(self):
        self._hooks: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, callback: Callable) -> None:
        self._hooks[event].append(callback)

    async def emit(self, event: str, **kwargs) -> list[Any]:
        results = []
        for callback in self._hooks.get(event, []):
            if hasattr(callback, "__await__"):
                results.append(await callback(**kwargs))
            else:
                results.append(callback(**kwargs))
        return results