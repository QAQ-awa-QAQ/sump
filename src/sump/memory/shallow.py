"""长期-浅层记忆（SQLite）"""

from typing import Any

from sump.memory.base import MemoryProvider


class ShallowMemory(MemoryProvider):
    """浅层长期记忆，基于 SQLite 持久化"""

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = db_path

    async def store(self, key: str, value: Any, **kwargs) -> None:
        pass

    async def retrieve(self, key: str, **kwargs) -> Any | None:
        return None

    async def forget(self, key: str) -> None:
        pass

    async def clear(self) -> None:
        pass
