"""会话记忆压缩器"""

from typing import Any

from sump.memory.session_memory import SessionMemory


class MemoryCompressor:
    """会话记忆压缩器。

    当会话消息数达到阈值，用 flash 模型（不思考）评估消息重要性，
    丢弃不重要的一半。
    """

    def __init__(
        self,
        session_memory: SessionMemory,
        llm: Any = None,
        max_messages: int = 10000,
    ) -> None:
        self.session_memory = session_memory
        self.llm = llm
        self.max_messages = max_messages

    async def compress(self, session_id: str = "default") -> int:
        """压缩指定会话：消息数超阈值后丢弃一半，返回删除条数。"""
        total = self.session_memory.count_messages(session_id)
        if total < self.max_messages:
            return 0
        to_delete = total // 2
        # TODO: 用 flash（不思考）评估消息重要性，删除不重要的那一半；
        # 当前兜底为删除最旧的一半。
        if self.llm is not None:
            to_delete = await self._evaluate_delete_count(session_id, total)
        return self.session_memory.delete_oldest_messages(session_id, to_delete)

    async def _evaluate_delete_count(self, session_id: str, total: int) -> int:
        """TODO: 用 flash 模型评估重要性，返回应删除的消息数。"""
        return total // 2
