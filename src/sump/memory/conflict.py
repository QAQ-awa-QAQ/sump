"""深层记忆矛盾检测（旧 vs 旧冲突解决）"""

import json
from typing import Any


class ConflictResolver:
    """睡眠时审视深层记忆，解决互相矛盾的旧条目（保留较新、删除过时）。"""

    def __init__(
        self, llm: Any, deep_memory: Any, max_chars_per_batch: int = 8000
    ) -> None:
        self._llm = llm
        self._deep_memory = deep_memory
        self._max_chars_per_batch = max_chars_per_batch

    async def resolve(self) -> str:
        """扫描并解决矛盾，返回结果描述。"""
        entries = self._deep_memory.list_all()
        if not entries:
            return "无深层记忆可检测"

        batches = self._split_batches(entries, self._max_chars_per_batch)
        resolved = 0
        for batch in batches:
            resolved += await self._resolve_batch(batch)
        return f"解决 {resolved} 对矛盾"

    async def _resolve_batch(self, entries: list[dict[str, Any]]) -> int:
        """对一批条目做一次矛盾判断，返回解决的矛盾对数。"""
        raw = await self._llm.chat_flash(
            self._build_prompt(entries), max_tokens=1024, temperature=0.3
        )
        data = self._parse_json(raw)
        if data is None:
            return 0

        conflicts = data.get("conflicts", []) or []
        count = 0
        for c in conflicts:
            if not isinstance(c, dict):
                continue
            drop = c.get("drop")
            if not drop:
                continue
            await self._deep_memory.forget(str(drop))
            count += 1
        return count

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
        return f"key={e['key']} 内容={e['value']}"

    def _build_prompt(self, entries: list[dict[str, Any]]) -> str:
        lines = [self._format_entry(e) for e in entries]
        return (
            "以下是一些深层记忆条目（key + 内容）。请找出互相矛盾的条目对：\n"
            "例如一条说某事实为 A、另一条说为 B 且 A/B 互相冲突。\n"
            "对每对矛盾，保留较新/较权威的那条（keep），删除另一条（drop）。\n"
            "只依据条目内容判断，不要臆造矛盾。\n\n"
            "只输出 JSON，不要 markdown 代码块、不要解释：\n"
            '{"conflicts": [{"keep": "key1", "drop": "key2"}]}\n'
            "没有矛盾则 conflicts 输出空数组 []。\n\n"
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
