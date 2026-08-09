"""运行时上下文"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sump.config import Config
from sump.types import Message


@dataclass
class Context:
    """Agent 运行时上下文，管理消息历史和状态。"""

    config: Config
    messages: list[Message] = field(default_factory=list)
    round_count: int = 0
    on_message: Callable[[Message], None] | None = None

    def add_user_message(self, content: str) -> None:
        self._append(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        self._append(Message(role="assistant", content=content))

    def add_tool_message(self, tool_call_id: str, content: str) -> None:
        self._append(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def _append(self, msg: Message) -> None:
        self.messages.append(msg)
        if self.on_message:
            self.on_message(msg)

    @property
    def history(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for m in self.messages[-50:]:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            result.append(entry)
        return result
