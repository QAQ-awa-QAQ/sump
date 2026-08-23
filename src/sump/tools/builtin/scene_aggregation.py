"""场景聚合工具（浅层原子记忆 → L2 场景块）"""

import json
from typing import Any

from sump.tools.base import Tool


class SceneAggregationTool(Tool):
    """把浅层原子记忆按主题聚类成场景块（L2）。"""

    name = "scene_aggregation"
    description = "把浅层记忆聚类为场景块（L2 场景记忆）"
    parameters = {"type": "object", "properties": {}}

    def __init__(
        self,
        llm: Any,
        shallow_memory: Any,
        scene_memory: Any,
        max_chars_per_batch: int = 8000,
    ) -> None:
        self._llm = llm
        self._shallow_memory = shallow_memory
        self._scene_memory = scene_memory
        self._max_chars_per_batch = max_chars_per_batch

    async def execute(self, **kwargs: Any) -> str:
        """聚合浅层记忆为场景块，返回结果描述。"""
        entries = self._shallow_memory.list_all_entries()
        if not entries:
            return "无浅层记忆可聚合"

        batches = self._split_batches(entries, self._max_chars_per_batch)
        total = 0
        failed = 0
        for batch in batches:
            n, ok = await self._aggregate_batch(batch)
            if ok:
                total += n
            else:
                failed += 1

        if failed and total == 0:
            return "聚合失败：模型返回无法解析"
        if total == 0:
            return "无需聚合"
        return f"聚合 {total} 个场景"

    async def _aggregate_batch(
        self, entries: list[dict[str, Any]]
    ) -> tuple[int, bool]:
        """对一批条目做一次聚类，返回 (场景数, 是否解析成功)。"""
        raw = await self._llm.chat_flash(
            self._build_prompt(entries), max_tokens=1024, temperature=0.3
        )
        data = self._parse_json(raw)
        if data is None:
            return 0, False

        scenes = data.get("scenes", []) or []
        count = 0
        for s in scenes:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip()
            summary = str(s.get("summary", "")).strip()
            if not name or not summary:
                continue
            priority = self._parse_priority(s.get("priority"))
            self._scene_memory.upsert_scene(name, summary, priority)
            count += 1
        return count, True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _split_batches(
        self, entries: list[dict[str, Any]], max_chars: int
    ) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for e in entries:
            line_len = len(self._format_entry(e))
            if current and current_chars + line_len > max_chars:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(e)
            current_chars += line_len
        if current:
            batches.append(current)
        return batches

    def _format_entry(self, e: dict[str, Any]) -> str:
        return f"id={e['id']} 类别={e['category']} 内容={e['content']}"

    def _build_prompt(self, entries: list[dict[str, Any]]) -> str:
        lines = [self._format_entry(e) for e in entries]
        return (
            "以下是一些浅层记忆条目。请把它们按主题聚类成若干场景，"
            "每个场景给出名字和一句话总结（浓缩关键信息）。\n"
            "只依据条目内容，不要胡编乱造、不要臆测。\n"
            "每个场景打 priority（0-100 整数）。\n\n"
            "只输出 JSON，不要 markdown 代码块、不要解释：\n"
            '{"scenes": [{"name": "场景名", "summary": "一句话总结", "priority": 80}]}\n'
            "条目：\n" + "\n".join(lines)
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        try:
            text = raw.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, AttributeError):
            return None

    @staticmethod
    def _parse_priority(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
