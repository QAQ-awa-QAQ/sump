"""MemoryProvider 抽象基类"""

from abc import ABC, abstractmethod
from typing import Any


class MemoryProvider(ABC):
    """所有记忆后端的抽象基类"""

    @abstractmethod
    async def store(self, key: str, value: Any, **kwargs) -> None:
        """存储记忆"""

    @abstractmethod
    async def retrieve(self, key: str, **kwargs) -> Any | None:
        """检索记忆"""

    @abstractmethod
    async def forget(self, key: str) -> None:
        """遗忘记忆"""

    @abstractmethod
    async def clear(self) -> None:
        """清空记忆"""
