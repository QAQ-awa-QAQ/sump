"""任务记忆（会话级）"""

from typing import Any

from sump.memory.base import MemoryProvider


class TaskMemory(MemoryProvider):
    """任务级记忆，随会话生命周期管理"""

    def __init__(self) -> None:
        self._tasks: dict[str, Any] = {}
        self._scratchpad: dict[str, Any] = {}

    async def store(self, key: str, value: Any, **kwargs: Any) -> None:
        self._tasks[key] = value

    async def retrieve(self, key: str, **kwargs: Any) -> Any | None:
        return self._tasks.get(key)

    async def forget(self, key: str) -> None:
        self._tasks.pop(key, None)

    async def clear(self) -> None:
        self._tasks.clear()
        self._scratchpad.clear()

    def set_scratchpad(self, key: str, value: Any) -> None:
        """设置工作便签"""
        self._scratchpad[key] = value

    def get_scratchpad(self, key: str) -> Any | None:
        """获取工作便签"""
        return self._scratchpad.get(key)
