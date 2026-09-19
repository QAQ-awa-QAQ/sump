"""执行器（按 Plan 调度 —— 工具调用循环 + 安全审查 + 流式输出）"""

import json
import uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sump.core.context import Context
from sump.core.models import LLMClient, sanitize_marked_output
from sump.core.planner import Plan
from sump.security.interceptor import Interceptor
from sump.security.judge import Judge
from sump.tools.registry import ToolRegistry
from sump.types import Message, content_to_text

# 审批回调类型
# - CLI: (command, summary, danger) -> True=放行, False=拒绝, None=API模式挂起
SecurityCallback = Callable[[str, str, str], bool | None] | None
# 审批挂起回调：(call_id, command, tool, tool_call_id, args, summary, danger) -> None
ApprovalSink = Callable[[str, str, Any, str, dict[str, Any], str, str], None] | None


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
        evaluator: Any = None,
        arbiter: Any = None,
        tools_first_round_only: bool = True,
        tool_hint_every: int = 7,
    ) -> None:
        self.ctx = ctx
        self.llm = llm
        self.tools = tools
        self._security_check = security_check
        self._on_approval_pending = on_approval_pending
        self._evaluator = evaluator
        self._arbiter = arbiter
        self._tools_first_round_only = tools_first_round_only
        self._tool_hint_every = tool_hint_every
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
            # 工具定义默认仅首轮传递（省 token）；开关关闭后每轮都传；
            # 每 tool_hint_every 轮也重新注入工具（对抗 agent 忘记工具）。
            is_hint_round = (
                self._tool_hint_every > 0
                and round_idx > 0
                and round_idx % self._tool_hint_every == 0
            )
            send_tools = round_idx == 0 or not self._tools_first_round_only or is_hint_round
            _tools: Any = schemas if send_tools else None
            print(f"[EXEC] round={round_idx} msgs={len(self.ctx.messages)} tools={_tools is not None}", flush=True)

            history = self.ctx.history
            if is_hint_round:
                history = history + [{
                    "role": "user",
                    "content": (
                        "【系统提示】对话已进行多轮，如需回顾可用工具，"
                        "可调用 list_tools 工具查看完整工具列表及用途。"
                    ),
                }]

            result = await self.llm.chat_full(history, tools=_tools)

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
                # 评价：工具执行后评估是否已完成，完成则提前结束循环
                if await self._should_finish():
                    async for event in self._stream_final():
                        yield event
                    return
            else:
                async for event in self._stream_final():
                    yield event
                return

    # ------------------------------------------------------------------
    # 内部评估 + 裁决
    # ------------------------------------------------------------------

    async def _should_finish(self) -> bool:
        """评估当前进展，裁决是否应结束工具循环。"""
        if self._evaluator is None or self._arbiter is None:
            return False
        internal = await self._evaluator.evaluate(self._current_task(), self._recent_progress())
        verdict = await self._arbiter.arbitrate(internal)
        return verdict.get("action") in ("finish", "stop")

    def _current_task(self) -> str:
        """取第一条用户消息作为任务描述。"""
        for m in self.ctx.messages:
            if m.role == "user":
                return content_to_text(m.content)
        return ""

    def _recent_progress(self) -> str:
        """把最近几条消息拼成当前进展文本。"""
        parts: list[str] = []
        for m in self.ctx.messages[-6:]:
            if m.role == "system":
                continue
            content = content_to_text(m.content)
            if m.tool_calls:
                names = [
                    t["function"]["name"]
                    for t in m.tool_calls
                    if isinstance(t, dict) and "function" in t
                ]
                content = "调用工具: " + ", ".join(names)
            if content:
                parts.append(f"{m.role}: {content[:300]}")
        return "\n".join(parts)

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
            # 是否真正挂起等审批（非 shell 工具不参与审批，不能凭 approved 判空）
            pending = False
            if sec_event:
                if self._security_check:
                    approved = self._security_check(
                        sec_event.command, sec_event.summary, sec_event.danger,
                    )

                if approved is None:
                    # API: 挂起等前端审批
                    if self._on_approval_pending:
                        pending = True
                        import uuid as _uuid
                        call_id = _uuid.uuid4().hex[:8]
                        self._on_approval_pending(
                            call_id, args["command"], tool, tc_id, args,
                            sec_event.summary, sec_event.danger,
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

            # 真正挂起等审批：终止本轮（审批通过后由 __continue__ 恢复）
            if pending:
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
            # 标记文本跨块残片兜底：全文级再清洗一次，绝不写入上下文
            content=sanitize_marked_output("".join(content_parts)),
            reasoning_content="".join(reasoning_parts),
        ))
