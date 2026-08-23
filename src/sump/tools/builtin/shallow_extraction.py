"""浅层记忆提取工具（会话 → 浅层记忆）

用 flash 模型（不思考）对整段会话做三判断：
1. 重不重要；2. 是否影响下次对话；3. 是否对后续有益。
任一命中即提炼缩句条目写入浅层记忆。
"""

import json
from typing import Any

from sump.tools.base import Tool


class ShallowExtractionTool(Tool):
    """会话记忆 → 浅层记忆 提炼工具。"""

    name = "shallow_extraction"
    description = "从会话消息提炼浅层长期记忆（重要/影响下次/有益）"
    parameters = {"type": "object", "properties": {}}

    def __init__(
        self, llm: Any, shallow_memory: Any,
        max_chars_per_batch: int = 8000, priority_threshold: int = 60,
    ) -> None:
        self._llm = llm
        self._shallow_memory = shallow_memory
        self._max_chars_per_batch = max_chars_per_batch
        self._priority_threshold = priority_threshold

    async def execute(
        self,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """提炼并写入浅层记忆，返回结果描述。"""
        msgs = messages or []
        if not msgs:
            return "无消息可提取"

        # 超长会话：按对话分界切批，一次只喂一部分，避免超出上下文
        batches = self._split_batches(msgs, self._max_chars_per_batch)

        total = 0
        failed = 0
        for batch in batches:
            n, ok = await self._extract_batch(session_id, batch)
            if ok:
                total += n
            else:
                failed += 1

        if failed and total == 0:
            return "提炼失败：模型返回无法解析"
        if total == 0:
            return "无需提炼"

        suffix = f"（{len(batches)} 批）" if len(batches) > 1 else ""
        if failed:
            suffix += f"，{failed} 批解析失败"
        return f"提取 {total} 条浅层记忆{suffix}"

    async def _extract_batch(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> tuple[int, bool]:
        """对一批消息做一次提炼，返回 (写入条数, 是否解析成功)。"""
        raw = await self._llm.chat_flash(
            self._build_prompt(messages), max_tokens=512, temperature=0.3
        )
        data = self._parse_json(raw)
        if data is None:
            return 0, False

        important = bool(data.get("important", False))
        affects_next = bool(data.get("affects_next", False))
        beneficial = bool(data.get("beneficial", False))
        memories = data.get("memories", []) or []

        # OR 规则：任一维度命中才提炼
        if not (important or affects_next or beneficial) or not memories:
            return 0, True

        count = 0
        for item in memories:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            category = str(item.get("category", "语义")).strip()
            priority = self._parse_priority(item.get("priority"))
            # 低价值直接丢弃（写入剪枝）
            if not content or priority < self._priority_threshold:
                continue
            self._shallow_memory.add_entry(
                category,
                content,
                {
                    "source": "session_extraction",
                    "session_id": session_id,
                    "important": important,
                    "affects_next": affects_next,
                    "beneficial": beneficial,
                },
                priority=priority,
            )
            count += 1
        return count, True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _split_batches(
        self, messages: list[dict[str, Any]], max_chars: int
    ) -> list[list[dict[str, Any]]]:
        """按对话分界（user 消息）切分，单批字符数不超过 max_chars。"""
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0

        for m in messages:
            line_len = len(self._format_message(m))
            if (
                current
                and m.get("role") == "user"
                and current_chars + line_len > max_chars
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(m)
            current_chars += line_len

        if current:
            batches.append(current)
        return batches

    def _format_message(self, m: dict[str, Any]) -> str:
        """把单条消息格式化成一行（工具调用只保留工具名）。"""
        role = m.get("role", "")
        content = m.get("content", "")
        tool_calls = m.get("tool_calls")
        if tool_calls:
            names = [
                (tc.get("function") or {}).get("name", "")
                for tc in tool_calls
            ]
            content = "调用工具: " + ", ".join(names)
        return f"{role}: {content}"

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        """把一批消息拼成提炼 prompt。"""
        lines = [self._format_message(m) for m in messages]
        return (
            "以下是用户与助手的一段完整对话。请先判断这段对话：\n"
            "1. 是否重要（值得长期记住）\n"
            "2. 是否会影响用户下一次对话\n"
            "3. 是否对后续对话有益\n"
            "任意一条成立，就提炼出值得长期记住的关键信息"
            "（每条一句话，浓缩保留关键事实，不要复制原文）。\n"
            "只提炼对话中真实出现的信息，不要胡编乱造、不要臆测。\n"
            "类别只能是：情景 / 语义 / 工作流 / error。\n"
            "每条记忆还要打 priority（0-100 整数）：\n"
            "80-100=核心特质/重要事件，60-79=一般偏好/普通活动，<60=次要信息。\n\n"
            "只输出 JSON，不要 markdown 代码块、不要解释：\n"
            '{"important": bool, "affects_next": bool, "beneficial": bool, '
            '"memories": [{"category": "语义", "content": "一句话关键信息", "priority": 80}]}\n'
            "若无需提炼，memories 输出空数组 []。\n\n"
            "对话内容：\n" + "\n".join(lines)
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
    def _parse_priority(value: Any) -> int:
        """解析 priority 为整数，失败时返回 0。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
