"""长期-深层记忆（SQLite + 向量）"""

from typing import Any

from sump.memory.base import MemoryProvider


class DeepMemory(MemoryProvider):
    """深层长期记忆，支持语义检索"""

    def __init__(self, db_path: str = "data/memory.db", embedding_model: str = "text-embedding-3-small"):
        self.db_path = db_path
        self.embedding_model = embedding_model

    async def store(self, key: str, value: Any, **kwargs) -> None:
        pass

    async def retrieve(self, key: str, **kwargs) -> Any | None:
        return None

    async def forget(self, key: str) -> None:
        pass

    async def clear(self) -> None:
        pass

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """语义搜索"""
        return []
