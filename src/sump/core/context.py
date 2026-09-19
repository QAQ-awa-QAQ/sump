"""运行时上下文"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sump.config import Config
from sump.types import Message, build_user_content, content_has_images, content_to_text


@dataclass
class Context:
    """Agent 运行时上下文，管理消息历史和状态。"""

    config: Config
    messages: list[Message] = field(default_factory=list)
    round_count: int = 0
    on_message: Callable[[Message], None] | None = None
    system_prompt: str = ""

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def add_user_message(self, content: str, images: list[str] | None = None) -> None:
        self._append(Message(role="user", content=build_user_content(content, images)))

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
        window = int(self.config.get("agent.context_window", 50))
        recent = self.messages[-window:]
        # 仅最近一条带图用户消息内联图片，更早的图片降级为 [图片] 占位（控制请求体与 token）
        last_image_idx = -1
        for i, m in enumerate(recent):
            if m.role == "user" and content_has_images(m.content):
                last_image_idx = i
        result: list[dict[str, Any]] = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for i, m in enumerate(recent):
            entry: dict[str, Any] = {"role": m.role}
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            else:
                content = m.content
                if isinstance(content, list) and i != last_image_idx:
                    content = content_to_text(content)
                entry["content"] = content
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            result.append(entry)
        return result
