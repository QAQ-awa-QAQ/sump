"""Zep 记忆 Provider"""

from typing import Any

from sump.memory.base import MemoryProvider


class ZepProvider(MemoryProvider):
    """基于 Zep 的记忆后端"""

    def __init__(self):
        pass

    async def store(self, key: str, value: Any, **kwargs) -> None:
        pass

    async def retrieve(self, key: str, **kwargs) -> Any | None:
        return None

    async def forget(self, key: str) -> None:
        pass

    async def clear(self) -> None:
        pass
