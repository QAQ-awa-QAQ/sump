"""记忆召回（深层强制注入 + 浅层/场景按需召回，带三重上限）"""

import asyncio
from typing import Any


class MemoryRetriever:
    """深层核心信息强制注入（保证一致性），浅层/场景按需语义召回。

    三重上限：max_results（条数）、max_chars（字符预算）、timeout（超时）。
    """

    def __init__(
        self,
        deep_memory: Any,
        shallow_memory: Any,
        scene_memory: Any = None,
        max_results: int = 5,
        max_chars: int = 800,
        timeout: float = 3.0,
        deep_inject_count: int = 20,
    ) -> None:
        self._deep_memory = deep_memory
        self._shallow_memory = shallow_memory
        self._scene_memory = scene_memory
        self._max_results = max_results
        self._max_chars = max_chars
        self._timeout = timeout
        self._deep_inject_count = deep_inject_count

    async def recall(self, query: str) -> str:
        """召回：深层核心强制注入 + 浅层/场景按需召回，返回注入文本。"""
        if not query:
            return ""

        # 深层：核心信息强制注入（按 priority 取 top，不看相关性）
        deep_results = self._deep_memory.list_all()
        deep_results.sort(key=lambda x: x.get("priority", 0), reverse=True)
        deep_results = deep_results[: self._deep_inject_count]

        # 浅层/场景：按需语义召回
        scene_results = (
            await self._search_layer(self._scene_memory, query, top_k=3)
            if self._scene_memory
            else []
        )
        shallow_results = await self._search_layer(
            self._shallow_memory, query, top_k=self._max_results
        )

        total = 0
        core_out: list[str] = []
        for r in deep_results:
            line = f"- [核心/{r.get('category', '')}] {r.get('value', '')}"
            total = self._append_line(core_out, line, total)

        relevant_out: list[str] = []
        for s in scene_results:
            line = f"- [场景/{s.get('name', '')}] {s.get('summary', '')}"
            total = self._append_line(relevant_out, line, total)
        for e in shallow_results:
            line = f"- [浅层/{e.get('category', '')}] {e.get('content', '')}"
            total = self._append_line(relevant_out, line, total)

        parts: list[str] = []
        if core_out:
            parts.append("<core-memories>\n" + "\n".join(core_out) + "\n</core-memories>")
        if relevant_out:
            parts.append("<relevant-memories>\n" + "\n".join(relevant_out) + "\n</relevant-memories>")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _search_layer(self, memory: Any, query: str, top_k: int) -> list[dict[str, Any]]:
        """调用某层记忆的 search，兼容同步/异步，带超时与异常降级。"""
        try:
            result = memory.search(query, top_k=top_k)
            if hasattr(result, "__await__"):
                result = await asyncio.wait_for(result, timeout=self._timeout)
            return result
        except Exception:
            return []

    def _append_line(self, lines: list[str], line: str, total: int) -> int:
        """字符预算内追加一行，返回新的累计字符数。"""
        if total + len(line) > self._max_chars:
            return total
        lines.append(line)
        return total + len(line)
