"""Mem0 记忆 Provider"""

from typing import Any

from sump.memory.base import MemoryProvider


class Mem0Provider(MemoryProvider):
    """基于 Mem0 的记忆后端"""

    def __init__(self) -> None:
        pass

    async def store(self, key: str, value: Any, **kwargs: Any) -> None:
        pass

    async def retrieve(self, key: str, **kwargs: Any) -> Any | None:
        return None

    async def forget(self, key: str) -> None:
        pass

    async def clear(self) -> None:
        pass
