"""Agent 主类 —— 唯一入口 run_stream()，CLI / API 只是消费方式不同"""

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sump.config import Config
from sump.core.context import Context
from sump.core.models import LLMClient
from sump.memory.shallow import ShallowMemory
from sump.security.interceptor import Interceptor
from sump.security.judge import Judge
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
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self.on_security_check: Callable[[str, str, str], bool] | None = None
        self._is_continue = False  # __continue__ 重启标记，跳过首轮 tools

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
        entries = self.memory.load_messages(session_id, limit=50)
        # 过滤不完整序列：tool 消息必须有前置 assistant(tool_calls)
        #  向前查找最近一条含有 tool_calls 的 assistant，而非只看紧邻上一条
        #  以兼容单条 assistant 包含多个 tool_calls 的场景
        valid: list[dict[str, Any]] = []
        for e in entries:
            if e["role"] == "tool" and e.get("tool_call_id"):
                # 向前查找最近一条 assistant(tool_calls)
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

    # ------------------------------------------------------------------
    # 安全审批
    # ------------------------------------------------------------------

    async def approve_command(self, call_id: str, approved: bool) -> str:
        """前端审批结果：approved=True 执行命令并替换待确认消息，False 替换为拒绝。

        审批后前端应重新发送对话请求让 LLM 继续处理结果。
        """
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

        # 替换上下文中"⛔ 待确认"的 tool 消息
        tci = pending["tool_call_id"]
        found = False
        for i, msg in enumerate(self.ctx.messages):
            if msg.role == "tool" and msg.tool_call_id == tci and "⛔ 安全审查待确认" in msg.content:
                self.ctx.messages[i] = Message(role="tool", content=result, tool_call_id=tci)
                found = True
                break
        if not found:
            self.ctx.add_tool_message(tci, result)

        return result

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

        for round_idx in range(10):
            # round 0 始终带 tools（含 __continue__ 场景，LLM 可能需要链式调用）
            _tools: Any = schemas if round_idx == 0 else None
            if round_idx == 0:
                self._is_continue = False
            result = await self.llm.chat_full(self.ctx.history, tools=_tools)

            if result.get("tool_calls"):
                self.ctx._append(Message(
                    role="assistant", content="",  # DeepSeek 要求 tool_calls 消息的 content 为空字符串
                    tool_calls=result["tool_calls"],
                ))
                _processed_tc_ids: list[str] = []
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
                        # 安全检查：规则秒出 → Flash 终裁
                        security_event = None
                        if name == "shell" and "command" in args:
                            rule = Judge().analyze(args["command"])
                            llm_needed = (rule.verdict == "unknown")
                            flash = await Judge().analyze_llm(args["command"], self.llm)

                            # 先推规则（秒出），再补 Flash 终裁（前端据此刷新）

                            # 先推规则（秒出），再补 Flash 终裁（前端据此刷新）
                            yield {
                                "type": "security_check",
                                "call_id": "",
                                "command": args["command"],
                                "summary": rule.summary,
                                "danger": rule.danger,
                                "verdict": rule.verdict if rule.verdict != "unknown" else "unknown",
                                "analysis_source": "rules",
                            }
                            yield {
                                "type": "security_check_detail",
                                "call_id": "",
                                "command": args["command"],
                                "summary": flash.summary,
                                "danger": flash.danger,
                                "verdict": flash.verdict,
                                "analysis_source": "llm",
                            }

                            # Flash 终裁
                            security_event = Interceptor().check(args["command"], flash)

                        _tool_msg_added = False

                        if security_event:
                            if self.on_security_check:
                                # CLI: 同步交互审批
                                approved = self.on_security_check(
                                    security_event.command,
                                    security_event.summary,
                                    security_event.danger,
                                )
                                if approved:
                                    try:
                                        tool_result = str(await tool.execute(**args))
                                    except Exception as e:
                                        tool_result = f"工具执行失败: {e}"
                                else:
                                    tool_result = "用户拒绝执行该命令"
                            else:
                                # API: 统一审批流（safe/risky 一律挂起等前端确认，消除竞态）
                                import uuid
                                call_id = uuid.uuid4().hex[:8]
                                self._pending_approvals[call_id] = {
                                    "command": args["command"],
                                    "tool": tool,
                                    "tool_call_id": tc["id"],
                                    "args": args,
                                }
                                tool_result = (
                                    f"⛔ 安全审查待确认 | call_id: {call_id} | "
                                    f"命令: {args['command']} | "
                                    f"意图: {security_event.summary} | "
                                    f"危险等级: {security_event.danger}"
                                )
                                # ★ 先写待确认消息，再 yield tool_result（在审批事件之前），
                                #   避免生成器恢复后重复推送旧流
                                self.ctx.add_tool_message(tc["id"], tool_result)
                                _tool_msg_added = True
                                yield {"type": "tool_result", "content": tool_result[:500]}
                                yield {
                                    "type": "security_check",
                                    "call_id": call_id,
                                    "command": security_event.command,
                                    "summary": security_event.summary,
                                    "danger": security_event.danger,
                                    "concerns": security_event.concerns,
                                    "verdict": security_event.verdict,
                                    "analysis_source": "llm" if llm_needed else "rules",
                                }
                                # 命中规则时补 Flash 详细分析
                                if not llm_needed:
                                    detailed = await Judge().analyze_llm(args["command"], self.llm)
                                    yield {
                                        "type": "security_check_detail",
                                        "call_id": call_id,
                                        "command": security_event.command,
                                        "summary": detailed.summary,
                                        "danger": detailed.danger,
                                        "concerns": detailed.concerns,
                                        "verdict": detailed.verdict,
                                        "analysis_source": "llm",
                                    }
                        else:
                            try:
                                tool_result = str(await tool.execute(**args))
                            except Exception as e:
                                tool_result = f"工具执行失败: {e}"

                    if not _tool_msg_added:
                        self.ctx.add_tool_message(tc["id"], tool_result)
                        yield {"type": "tool_result", "content": tool_result[:500]}
                    _processed_tc_ids.append(tc["id"])
                    # 所有命令统一挂起等前端审批（安全命令前端自动通过）
                    if not self.on_security_check:
                        # 裁剪 assistant 消息：移除未处理的 tool_calls，避免 DeepSeek 400
                        last_msg = self.ctx.messages[-1]
                        if last_msg.role == "assistant" and last_msg.tool_calls:
                            last_msg.tool_calls = [t for t in last_msg.tool_calls if t["id"] in _processed_tc_ids]
                        return
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
