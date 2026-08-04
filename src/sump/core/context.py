"""运行时上下文"""

from dataclasses import dataclass, field

from sump.config import Config
from sump.types import Message


@dataclass
class Context:
    """Agent 运行时上下文，管理消息历史和状态"""

    config: Config
    messages: list[Message] = field(default_factory=list)
    round_count: int = 0

    def add_user_message(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))

    def add_assistant_message(self, content: str) -> None:
        self.messages.append(Message(role="assistant", content=content))

    @property
    def history(self) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self.messages[-50:]]
