"""执行器（按 Plan 调度 —— 工具调用循环 + 安全审查 + 流式输出）"""

import json
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sump.core.context import Context
from sump.core.models import LLMClient
from sump.core.planner import Plan
from sump.security.interceptor import Interceptor
from sump.security.judge import Judge
from sump.tools.registry import ToolRegistry
from sump.types import Message

# 审批回调类型
# - CLI: (command, summary, danger) -> True=放行, False=拒绝, None=API模式挂起
SecurityCallback = Callable[[str, str, str], bool | None] | None
# API 审批挂起回调：(call_id, command, tool, tool_call_id, args) -> None
ApprovalSink = Callable[[str, str, Any, str, dict[str, Any]], None] | None


class Executor:
    """按 Plan 逐步执行，封装工具调用循环与安全审查。"""

    def __init__(
        self,
        ctx: Context,
        llm: LLMClient,
        tools: ToolRegistry,
        *,
        security_check: SecurityCallback = None,
        on_approval_pending: ApprovalSink = None,
    ) -> None:
        self.ctx = ctx
        self.llm = llm
        self.tools = tools
        self._security_check = security_check
        self._on_approval_pending = on_approval_pending
        self._should_break = False

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def execute(self, plan: Plan) -> AsyncGenerator[dict[str, Any], None]:
        """按计划执行，流式产出事件。"""
        if not plan.tools_enabled or not self.tools.list_all():
            # 无工具：直接流式回复
            async for event in self._stream_final():
                yield event
            return

        schemas = self.tools.get_schemas()

        for round_idx in range(plan.max_rounds):
            _tools: Any = schemas if round_idx == 0 else None
            print(f"[EXEC] round={round_idx} msgs={len(self.ctx.messages)} tools={_tools is not None}", flush=True)

            result = await self.llm.chat_full(self.ctx.history, tools=_tools)

            if result.get("tool_calls"):
                tc_ids = [tc["id"] for tc in result["tool_calls"]]
                print(f"[EXEC] tool_calls: {tc_ids}", flush=True)
                self.ctx._append(Message(
                    role="assistant", content="",
                    tool_calls=result["tool_calls"],
                    reasoning_content=result.get("reasoning_content") or "",
                ))
                async for event in self._process_tools(result["tool_calls"]):
                    yield event
                if self._should_break:
                    return
            else:
                async for event in self._stream_final():
                    yield event
                return

    # ------------------------------------------------------------------
    # 工具处理
    # ------------------------------------------------------------------

    async def _process_tools(
        self, tool_calls: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """遍历并执行本轮所有工具调用。"""
        self._should_break = False
        processed_ids: list[str] = []

        for i, tc in enumerate(tool_calls):
            tc_id = tc["id"]
            name = tc["function"]["name"]
            tool = self.tools.get(name)
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, TypeError):
                args = {}

            print(f"[EXEC] TC[{i}] {name}({args})", flush=True)
            yield {"type": "tool_call", "name": name, "args": args}

            if tool is None:
                tr = f"工具 {name} 未注册"
                self.ctx.add_tool_message(tc_id, tr)
                yield {"type": "tool_result", "content": tr[:500]}
                processed_ids.append(tc_id)
                continue

            # ── 安全检查（仅 shell） ──
            sec_event, llm_needed = None, True
            if name == "shell" and "command" in args:
                rule_event, flash_event, sec_event, llm_needed = \
                    await self._analyze_security(args["command"])
                yield rule_event
                yield flash_event

            # ── 执行 / 审批（三路分支：approved=None→挂起, True→执行, False→拒绝）──
            tool_msg_added = False
            approved: bool | None = None
            if sec_event:
                if self._security_check:
                    approved = self._security_check(
                        sec_event.command, sec_event.summary, sec_event.danger,
                    )

                if approved is None:
                    # API: 挂起等前端审批
                    if self._on_approval_pending:
                        import uuid as _uuid
                        call_id = _uuid.uuid4().hex[:8]
                        self._on_approval_pending(
                            call_id, args["command"], tool, tc_id, args,
                        )
                        tr = (
                            f"⛔ 安全审查待确认 | call_id: {call_id} | "
                            f"命令: {args['command']} | "
                            f"意图: {sec_event.summary} | "
                            f"危险等级: {sec_event.danger}"
                        )
                        self.ctx.add_tool_message(tc_id, tr)
                        tool_msg_added = True
                        yield {"type": "tool_result", "content": tr[:500]}
                        yield {
                            "type": "security_check",
                            "call_id": call_id,
                            "command": sec_event.command,
                            "summary": sec_event.summary,
                            "danger": sec_event.danger,
                            "concerns": sec_event.concerns,
                            "verdict": sec_event.verdict,
                            "analysis_source": "llm" if llm_needed else "rules",
                        }
                        if not llm_needed:
                            detailed = await Judge().analyze_llm(args["command"], self.llm)
                            yield {
                                "type": "security_check_detail",
                                "call_id": call_id,
                                "command": sec_event.command,
                                "summary": detailed.summary,
                                "danger": detailed.danger,
                                "concerns": detailed.concerns,
                                "verdict": detailed.verdict,
                                "analysis_source": "llm",
                            }
                    else:
                        tr = "安全审查服务不可用"
                elif approved:
                    try:
                        tr = str(await tool.execute(**args))
                    except Exception as e:
                        tr = f"工具执行失败: {e}"
                else:
                    tr = "用户拒绝执行该命令"
            else:
                try:
                    tr = str(await tool.execute(**args))
                except Exception as e:
                    tr = f"工具执行失败: {e}"

            if not tool_msg_added:
                self.ctx.add_tool_message(tc_id, tr)
                yield {"type": "tool_result", "content": tr[:500]}
            processed_ids.append(tc_id)

            # API 模式（approved=None）：挂起等前端审批
            if approved is None:
                self._crop_assistant_tool_calls(processed_ids)
                self._should_break = True
                return

    def _crop_assistant_tool_calls(self, processed_ids: list[str]) -> None:
        """裁剪 assistant 消息中未处理的 tool_call_id。"""
        for msg in reversed(self.ctx.messages):
            if msg.role == "assistant" and msg.tool_calls:
                msg.tool_calls = [
                    t for t in msg.tool_calls if t["id"] in processed_ids
                ]
                break

    # ------------------------------------------------------------------
    # 安全检查
    # ------------------------------------------------------------------

    async def _analyze_security(
        self, command: str
    ) -> tuple[dict[str, Any], dict[str, Any], Any, bool]:
        """规则匹配 + LLM Flash 双重检查。"""
        rule = Judge().analyze(command)
        llm_needed = rule.verdict == "unknown"
        rule_event = {
            "type": "security_check",
            "call_id": "",
            "command": command,
            "summary": rule.summary,
            "danger": rule.danger,
            "verdict": rule.verdict,
            "analysis_source": "rules",
        }
        flash = await Judge().analyze_llm(command, self.llm)
        flash_event = {
            "type": "security_check_detail",
            "call_id": "",
            "command": command,
            "summary": flash.summary,
            "danger": flash.danger,
            "verdict": flash.verdict,
            "analysis_source": "llm",
        }
        sec_event = Interceptor().check(command, flash)
        return rule_event, flash_event, sec_event, llm_needed

    # ------------------------------------------------------------------
    # 流式最终回复
    # ------------------------------------------------------------------

    async def _stream_final(self) -> AsyncGenerator[dict[str, Any], None]:
        reasoning_parts: list[str] = []
        content_parts: list[str] = []
        async for chunk in self.llm.chat_stream(self.ctx.history):
            if chunk["type"] == "reasoning":
                reasoning_parts.append(chunk["text"])
            elif chunk["type"] == "content":
                content_parts.append(chunk["text"])
            yield chunk
        self.ctx._append(Message(
            role="assistant",
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
        ))
