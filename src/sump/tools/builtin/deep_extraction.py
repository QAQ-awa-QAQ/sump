"""深层记忆提取工具（浅层 → 深层）

用 flash 模型（不思考）对浅层记忆条目做三判断：
1. 是否重要；2. 是否对用户未来对话产生重要影响；3. 是否有利于提升本智能体。
三个条件【都】满足才升级到深层记忆，并从浅层删除。
"""

import json
from typing import Any

from sump.memory.dedup import DeepDedup
from sump.tools.base import Tool


class DeepExtractionTool(Tool):
    """浅层记忆 → 深层记忆 升级提取工具。"""

    name = "deep_extraction"
    description = "从浅层记忆提炼深层记忆（重要且影响未来且有益）"
    parameters = {"type": "object", "properties": {}}

    def __init__(
        self,
        llm: Any,
        shallow_memory: Any,
        deep_memory: Any,
        max_chars_per_batch: int = 8000,
        priority_threshold: int = 70,
        dedup: Any = None,
    ) -> None:
        self._llm = llm
        self._shallow_memory = shallow_memory
        self._deep_memory = deep_memory
        self._max_chars_per_batch = max_chars_per_batch
        self._priority_threshold = priority_threshold
        self._dedup = dedup or DeepDedup(llm, deep_memory)

    async def execute(self, **kwargs: Any) -> str:
        """升级浅层记忆到深层，返回结果描述。"""
        entries = self._shallow_memory.list_all_entries()
        if not entries:
            return "无浅层记忆可升级"

        batches = self._split_batches(entries, self._max_chars_per_batch)

        upgraded = 0
        failed = 0
        for batch in batches:
            n, ok = await self._upgrade_batch(batch)
            if ok:
                upgraded += n
            else:
                failed += 1

        if failed and upgraded == 0:
            return "升级失败：模型返回无法解析"
        if upgraded == 0:
            return "无需升级"

        suffix = f"（{len(batches)} 批）" if len(batches) > 1 else ""
        if failed:
            suffix += f"，{failed} 批解析失败"
        return f"升级 {upgraded} 条深层记忆{suffix}"

    async def _upgrade_batch(
        self, entries: list[dict[str, Any]]
    ) -> tuple[int, bool]:
        """对一批浅层条目做判断 + 冲突检测，返回 (升级条数, 是否解析成功)。"""
        raw = await self._llm.chat_flash(
            self._build_prompt(entries), max_tokens=512, temperature=0.3
        )
        data = self._parse_json(raw)
        if data is None:
            return 0, False

        decisions = data.get("items", []) or []
        candidates: list[dict[str, Any]] = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            entry_id = d.get("id")
            if not self._is_valid_id(entry_id):
                continue

            important = bool(d.get("important", False))
            affects_future = bool(d.get("affects_future", False))
            beneficial_agent = bool(d.get("beneficial_agent", False))
            priority = self._parse_priority(d.get("priority"))

            # AND 规则：三个维度都满足且 priority 达标才升级
            if not (important and affects_future and beneficial_agent):
                continue
            if priority < self._priority_threshold:
                continue

            entry = next(
                (e for e in entries if str(e["id"]) == str(entry_id)), None
            )
            if entry is None:
                continue
            candidates.append({
                "id": entry["id"],
                "content": entry["content"],
                "category": entry["category"],
                "priority": priority,
                "important": important,
                "affects_future": affects_future,
                "beneficial_agent": beneficial_agent,
            })

        if not candidates:
            return 0, True

        # 冲突检测：store / update / merge / skip
        dedup_decisions = await self._dedup.decide(candidates)
        decision_map = {str(d["id"]): d for d in dedup_decisions}

        count = 0
        for c in candidates:
            d = decision_map.get(str(c["id"]))
            if d is None or d.get("action") == "skip":
                continue
            content = c["content"]
            if d.get("action") in ("update", "merge"):
                for tk in d.get("target_keys", []) or []:
                    await self._deep_memory.forget(tk)
                if d.get("action") == "merge" and d.get("merged_content"):
                    content = str(d["merged_content"])
            await self._deep_memory.store(
                f"shallow:{c['id']}",
                content,
                category=c["category"],
                priority=c["priority"],
                metadata={
                    "source": "shallow_entry",
                    "shallow_entry_id": c["id"],
                    "important": c["important"],
                    "affects_future": c["affects_future"],
                    "beneficial_agent": c["beneficial_agent"],
                },
            )
            # 升级后从浅层删除（层级腾空）
            self._shallow_memory.remove_entry(c["id"])
            count += 1

        return count, True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _split_batches(
        self, entries: list[dict[str, Any]], max_chars: int
    ) -> list[list[dict[str, Any]]]:
        """按字符数切分条目，单批不超过 max_chars。"""
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
        """把一条浅层条目格式化成一行。"""
        return f"id={e['id']} 类别={e['category']} 内容={e['content']}"

    def _build_prompt(self, entries: list[dict[str, Any]]) -> str:
        """把一批浅层条目拼成判断 prompt。"""
        lines = [self._format_entry(e) for e in entries]
        return (
            "以下是一些浅层记忆条目，每条含 id 与内容。请逐条判断：\n"
            "1. 是否重要\n"
            "2. 是否会对用户未来对话产生重要影响\n"
            "3. 是否有利于提升本智能体\n"
            "三个条件【都】满足的条目才升级到深层记忆。\n"
            "每条还要打 priority（0-100 整数，深层标准更高）：\n"
            "90-100=核心特质/关键决策，70-89=重要事件/稳定偏好，<70=暂不升级。\n"
            "只依据条目内容判断，不要胡编乱造、不要臆测。\n\n"
            "只输出 JSON，不要 markdown 代码块、不要解释：\n"
            '{"items": [{"id": 条目id, "important": true, '
            '"affects_future": true, "beneficial_agent": true, "priority": 85}]}\n'
            "只列出三个条件都满足且 priority>=70 的条目；没有则 items 输出空数组 []。\n\n"
            "条目：\n" + "\n".join(lines)
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        """解析 flash 返回的 JSON（容忍 ```json 包装）。"""
        try:
            text = raw.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, AttributeError):
            return None

    @staticmethod
    def _is_valid_id(entry_id: Any) -> bool:
        """判断模型返回的条目 id 是否为合法数字。"""
        return isinstance(entry_id, int) or (
            isinstance(entry_id, str) and entry_id.isdigit()
        )

    @staticmethod
    def _parse_priority(value: Any) -> int:
        """解析 priority 为整数，失败时返回 0。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
