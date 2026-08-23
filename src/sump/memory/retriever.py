"""记忆召回（核心强制注入 + 深层/浅层/场景相关召回，预算各自独立）"""

import asyncio
from typing import Any


class MemoryRetriever:
    """核心信息强制注入（身份一致性），深层/浅层/场景按需语义召回。

    - core：按 priority 取 top N 强制注入，独立预算 core_max_chars
    - relevant：深层相关（search）+ 场景 + 浅层，独立预算 max_chars
    三重上限：max_results（条数）、max_chars（字符）、timeout（超时）。
    """

    def __init__(
        self,
        deep_memory: Any,
        shallow_memory: Any,
        scene_memory: Any = None,
        max_results: int = 5,
        max_chars: int = 800,
        timeout: float = 3.0,
        deep_inject_count: int = 5,
        core_max_chars: int | None = None,
    ) -> None:
        self._deep_memory = deep_memory
        self._shallow_memory = shallow_memory
        self._scene_memory = scene_memory
        self._max_results = max_results
        self._max_chars = max_chars
        self._timeout = timeout
        self._deep_inject_count = deep_inject_count
        self._core_max_chars = core_max_chars if core_max_chars is not None else max_chars

    async def recall(self, query: str) -> str:
        """召回：核心强制注入 + 深层/浅层/场景相关召回，返回注入文本。"""
        if not query:
            return ""

        # 1. 核心：按 priority 强制注入 top N（不看相关性，保证身份一致性）
        deep_all = self._deep_memory.list_all()
        deep_all.sort(key=lambda x: x.get("priority", 0), reverse=True)
        core_entries = deep_all[: self._deep_inject_count]

        # 2. 相关召回：深层（search）+ 场景 + 浅层
        deep_search = await self._search_layer(
            self._deep_memory, query, top_k=self._max_results
        )
        scene_results = (
            await self._search_layer(self._scene_memory, query, top_k=3)
            if self._scene_memory
            else []
        )
        shallow_results = await self._search_layer(
            self._shallow_memory, query, top_k=self._max_results
        )

        # core 独立预算
        core_out: list[str] = []
        core_total = 0
        injected_keys: set[str] = set()
        for r in core_entries:
            line = f"- [核心/{r.get('category', '')}] {r.get('value', '')}"
            if core_total + len(line) > self._core_max_chars:
                continue
            core_out.append(line)
            core_total += len(line)
            injected_keys.add(r.get("key"))

        # relevant 独立预算；深层相关召回排除已在核心注入的 key
        relevant_out: list[str] = []
        relevant_total = 0
        for d in deep_search:
            if d.get("key") in injected_keys:
                continue
            line = f"- [深层/{d.get('category', '')}] {d.get('value', '')}"
            if relevant_total + len(line) > self._max_chars:
                continue
            relevant_out.append(line)
            relevant_total += len(line)
        for s in scene_results:
            line = f"- [场景/{s.get('name', '')}] {s.get('summary', '')}"
            if relevant_total + len(line) > self._max_chars:
                continue
            relevant_out.append(line)
            relevant_total += len(line)
        for e in shallow_results:
            line = f"- [浅层/{e.get('category', '')}] {e.get('content', '')}"
            if relevant_total + len(line) > self._max_chars:
                continue
            relevant_out.append(line)
            relevant_total += len(line)

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

