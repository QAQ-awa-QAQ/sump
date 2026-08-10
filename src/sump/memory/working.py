"""短期记忆（LRU）"""

from collections import OrderedDict
from typing import Any

from sump.memory.base import MemoryProvider


class WorkingMemory(MemoryProvider):
    """基于 LRU 的短期记忆实现"""

    def __init__(self, max_items: int = 100, ttl_seconds: int = 600) -> None:
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, Any] = OrderedDict()

    async def store(self, key: str, value: Any, **kwargs: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) > self.max_items:
            self._store.popitem(last=False)

    async def retrieve(self, key: str, **kwargs: Any) -> Any | None:
        return self._store.get(key)

    async def forget(self, key: str) -> None:
        self._store.pop(key, None)

    async def clear(self) -> None:
        self._store.clear()
