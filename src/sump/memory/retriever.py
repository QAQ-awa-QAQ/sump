"""记忆召回（深层混合检索 + 浅层补充，带三重上限）"""

import asyncio
from typing import Any


class MemoryRetriever:
    """从深层/浅层召回相关记忆，格式化为注入上下文文本。

    三重上限：max_results（条数）、max_chars（字符预算）、timeout（超时）。
    """

    def __init__(
        self,
        deep_memory: Any,
        shallow_memory: Any,
        max_results: int = 5,
        max_chars: int = 800,
        timeout: float = 3.0,
    ) -> None:
        self._deep_memory = deep_memory
        self._shallow_memory = shallow_memory
        self._max_results = max_results
        self._max_chars = max_chars
        self._timeout = timeout

    async def recall(self, query: str) -> str:
        """召回相关记忆，返回 <relevant-memories> 文本（无结果返回空串）。"""
        if not query:
            return ""

        try:
            deep_results = await asyncio.wait_for(
                self._deep_memory.search(query, top_k=self._max_results),
                timeout=self._timeout,
            )
        except Exception:
            deep_results = []

        # 浅层补充：按 priority 降序取 top（浅层无向量，按优先级召回）
        shallow_entries = [
            e for e in self._shallow_memory.list_entries(limit=20)
            if e.get("priority", 0) > 0
        ]
        shallow_entries.sort(key=lambda x: x.get("priority", 0), reverse=True)
        shallow_entries = shallow_entries[: self._max_results]

        lines: list[str] = []
        total = 0
        for r in deep_results:
            line = f"- [深层/{r.get('category', '')}] {r['value']}"
            if total + len(line) > self._max_chars:
                break
            lines.append(line)
            total += len(line)
        for e in shallow_entries:
            line = f"- [浅层/{e.get('category', '')}] {e['content']}"
            if total + len(line) > self._max_chars:
                break
            lines.append(line)
            total += len(line)

        if not lines:
            return ""
        return "<relevant-memories>\n" + "\n".join(lines) + "\n</relevant-memories>"
