"""Agent 主类 —— 唯一入口 run_stream()，CLI / API 只是消费方式不同"""

import json
from collections.abc import AsyncGenerator
from typing import Any

from sump.config import Config
from sump.core.context import Context
from sump.core.models import LLMClient
from sump.memory.shallow import ShallowMemory
from sump.tools.builtin.shell import ShellTool
from sump.tools.registry import ToolRegistry
from sump.types import Message


class Agent:
    """SUMP Agent。

    唯一业务入口::

        async for event in agent.run_stream(user_input):
            # event: {type, ...} → CLI 渲染 ANSI / API 渲染 SSE
    """

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.memory = ShallowMemory(self.config.get("memory.shallow.db_path", "data/memory.db"))
        self.ctx = Context(self.config)
        self.llm = LLMClient(self.config)
        self.tools = ToolRegistry()
        self.tools.register(ShellTool())
        self._session_id = "default"

        self.ctx.on_message = self._persist_message
        self._load_session(self._session_id)

    # ------------------------------------------------------------------
    # 会话管理（统一入口）
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    def switch_session(self, session_id: str) -> None:
        """切换到指定会话，清空当前上下文并加载历史。"""
        self._session_id = session_id
        self.ctx.messages.clear()
        self._load_session(session_id)

    def new_session(self) -> str:
        """创建新会话，返回会话 ID。"""
        import uuid
        sid = uuid.uuid4().hex[:8]
        self.switch_session(sid)
        return sid

    def _load_session(self, session_id: str) -> None:
        for entry in self.memory.load_messages(session_id, limit=50):
            self.ctx.messages.append(Message(
                role=entry["role"],
                content=entry["content"],
                tool_call_id=entry.get("tool_call_id", ""),
                tool_calls=entry.get("tool_calls"),
            ))

    # ------------------------------------------------------------------
    # 唯一入口
    # ------------------------------------------------------------------

    async def run_stream(
        self, user_input: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行一轮对话，流式产出事件。

        Yields:
            {"type": "tool_call",   "name": str, "args": dict}
            {"type": "tool_result", "content": str}
            {"type": "reasoning",   "text": str}
            {"type": "content",     "text": str}
        """
        self.ctx.add_user_message(user_input)
        async for event in self._run_core():
            yield event

    # ------------------------------------------------------------------
    # 核心循环
    # ------------------------------------------------------------------

    async def _run_core(self) -> AsyncGenerator[dict[str, Any], None]:
        """工具调用循环 → 流式最终回复。"""
        schemas = self.tools.get_schemas() if self.tools.list_all() else None

        for _ in range(10):
            result = await self.llm.chat_full(self.ctx.history, tools=schemas)

            if result.get("tool_calls"):
                self.ctx._append(Message(
                    role="assistant", content="",
                    tool_calls=result["tool_calls"],
                ))
                for tc in result["tool_calls"]:
                    name = tc["function"]["name"]
                    tool = self.tools.get(name)
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    yield {"type": "tool_call", "name": name, "args": args}

                    if tool is None:
                        tool_result = f"工具 {name} 未注册"
                    else:
                        try:
                            tool_result = str(await tool.execute(**args))
                        except Exception as e:
                            tool_result = f"工具执行失败: {e}"

                    yield {"type": "tool_result", "content": tool_result[:500]}
                    self.ctx.add_tool_message(tc["id"], tool_result)
            else:
                # 流式最终回复，同时收集内容写入上下文
                content_parts: list[str] = []
                async for chunk in self.llm.chat_stream(self.ctx.history):
                    if chunk["type"] == "content":
                        content_parts.append(chunk["text"])
                    yield chunk
                self.ctx.add_assistant_message("".join(content_parts))
                return

    # ------------------------------------------------------------------
    # 记忆持久化
    # ------------------------------------------------------------------

    def _persist_message(self, msg: Message) -> None:
        self.memory.save_message(
            session_id=self._session_id,
            role=msg.role,
            content=msg.content,
            tool_call_id=msg.tool_call_id,
            tool_calls=msg.tool_calls,
        )
