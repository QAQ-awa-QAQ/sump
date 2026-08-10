"""Agent 主类 —— 委托 Planner（计划）+ Executor（执行），CLI/API 仅消费事件"""

import uuid as _uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sump.config import Config
from sump.core.context import Context
from sump.core.executor import Executor
from sump.core.models import LLMClient
from sump.core.planner import Planner
from sump.memory.shallow import ShallowMemory
from sump.tools.builtin.shell import ShellTool
from sump.tools.registry import ToolRegistry
from sump.types import Message


class Agent:
    """SUMP Agent。

    唯一业务入口::

        async for event in agent.run_stream(user_input):
            # event: {type, ...} -> CLI 渲染 ANSI / API 渲染 SSE
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

        # 安全审批状态
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._is_continue = False
        self.on_security_check: Callable[[str, str, str], bool] | None = None

        # 子组件：Planner + Executor
        self._planner = Planner(self.ctx)
        self._executor = Executor(
            self.ctx, self.llm, self.tools,
            security_check=self._cli_security_check,
            on_approval_pending=self._api_approval_pending,
        )

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    def switch_session(self, session_id: str) -> None:
        self._session_id = session_id
        self.ctx.messages.clear()
        self._load_session(session_id)

    def new_session(self) -> str:
        sid = _uuid.uuid4().hex[:8]
        self.switch_session(sid)
        return sid

    def _load_session(self, session_id: str) -> None:
        entries = self.memory.load_messages(session_id, limit=self._context_window)
        valid: list[dict[str, Any]] = []
        for e in entries:
            if e["role"] == "tool" and e.get("tool_call_id"):
                ok = False
                for p in reversed(valid):
                    if p["role"] == "assistant" and p.get("tool_calls"):
                        ok = True
                        break
                    if p["role"] != "tool":
                        break
                if ok:
                    valid.append(e)
            else:
                valid.append(e)
        for entry in valid:
            self.ctx.messages.append(Message(
                role=entry["role"],
                content=entry["content"],
                tool_call_id=entry.get("tool_call_id", ""),
                tool_calls=entry.get("tool_calls"),
            ))

    @property
    def _context_window(self) -> int:
        return int(self.config.get("agent.context_window", 50))

    @property
    def _max_rounds(self) -> int:
        return int(self.config.get("agent.max_rounds", 10))

    # ------------------------------------------------------------------
    # 安全审批（CLI / API 双模式）
    # ------------------------------------------------------------------

    def _cli_security_check(self, command: str, summary: str, danger: str) -> bool | None:
        """CLI: 通过 on_security_check 回调审批。API 模式返回 None。"""
        if self.on_security_check:
            return self.on_security_check(command, summary, danger)
        return None  # API 模式：挂起等前端审批

    def _api_approval_pending(
        self, call_id: str, command: str, tool: Any, tc_id: str, args: dict[str, Any]
    ) -> None:
        """API: 挂起到 pending 队列。"""
        self._pending_approvals[call_id] = {
            "command": command, "tool": tool,
            "tool_call_id": tc_id, "args": args,
        }

    async def approve_command(self, call_id: str, approved: bool) -> str:
        """前端审批结果：执行或拒绝。"""
        pending = self._pending_approvals.pop(call_id, None)
        if not pending:
            return "审批已过期或不存在"

        if approved:
            try:
                result = str(await pending["tool"].execute(**pending["args"]))
            except Exception as e:
                result = f"工具执行失败: {e}"
        else:
            result = "用户拒绝执行该命令"

        tci = pending["tool_call_id"]
        found = False
        for i, msg in enumerate(self.ctx.messages):
            if msg.role == "tool" and msg.tool_call_id == tci and "\u26d4" in msg.content:
                self.ctx.messages[i] = Message(role="tool", content=result, tool_call_id=tci)
                self.memory.update_tool_message(self._session_id, tci, result)
                found = True
                break
        if not found:
            self.ctx.add_tool_message(tci, result)

        # 同步裁剪 assistant.tool_calls
        valid_ids = {m.tool_call_id for m in self.ctx.messages
                     if m.role == "tool" and m.tool_call_id}
        for msg in self.ctx.messages:
            if msg.role == "assistant" and msg.tool_calls:
                msg.tool_calls = [t for t in msg.tool_calls if t["id"] in valid_ids]

        return result

    def lookup_pending_call(self, call_id: str) -> bool:
        return call_id in self._pending_approvals

    # ------------------------------------------------------------------
    # 唯一入口：Plan -> Execute
    # ------------------------------------------------------------------

    async def run_stream(
        self, user_input: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行一轮对话。流程: 用户消息入上下文 -> Planner 计划 -> Executor 执行。"""
        self.ctx.add_user_message(user_input)

        plan = await self._planner.plan(
            tools_available=len(self.tools.list_all()),
            max_rounds=self._max_rounds,
        )

        async for event in self._executor.execute(plan):
            yield event

    async def run_core(self) -> AsyncGenerator[dict[str, Any], None]:
        """延续执行（审批后 __continue__），不添加用户消息。"""
        plan = await self._planner.plan(
            tools_available=len(self.tools.list_all()),
            max_rounds=self._max_rounds,
        )
        async for event in self._executor.execute(plan):
            yield event

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
            reasoning_content=msg.reasoning_content,
        )
