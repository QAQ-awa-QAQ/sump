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
        self._should_break = False
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
        print(f"[[32mINFO[0m][approval] 进入 | call_id={call_id} approved={approved} pending队列={list(self._pending_approvals.keys())}", flush=True)
        pending = self._pending_approvals.pop(call_id, None)
        if not pending:
            print(f"[[32mINFO[0m][approval] call_id={call_id} 不在pending队列中", flush=True)
            return "审批已过期或不存在"

        print(f"[[32mINFO[0m][approval] pending数据: tool_call_id={pending['tool_call_id']} command={pending['command']}", flush=True)
        if approved:
            try:
                result = str(await pending["tool"].execute(**pending["args"]))
            except Exception as e:
                result = f"工具执行失败: {e}"
        else:
            result = "用户拒绝执行该命令"
        print(f"[[32mINFO[0m][approval] 最终tool_result='{result[:80]}'", flush=True)

        # 替换上下文中"⛔ 待确认"的 tool 消息
        tci = pending["tool_call_id"]
        found = False
        for i, msg in enumerate(self.ctx.messages):
            if msg.role == "tool" and msg.tool_call_id == tci and "⛔ 安全审查待确认" in msg.content:
                print(f"[[32mINFO[0m][approval] 替换上下文第{i}条消息: '{msg.content[:60]}...' → '{result[:60]}'", flush=True)
                self.ctx.messages[i] = Message(role="tool", content=result, tool_call_id=tci)
                # 持久化替换结果
                self.memory.update_tool_message(self._session_id, tci, result)
                found = True
                break
        if not found:
            print(f"[[32mINFO[0m][approval] 未找到待确认消息，追加新 tool 消息", flush=True)
            self.ctx.add_tool_message(tci, result)

        # ★ 同步裁剪：移除 assistant 中没有对应 tool 响应的 tool_call_id
        #   避免旧生成器的裁剪与 __continue__ 的新 LLM 调用产生竞态
        valid_tool_ids = {
            m.tool_call_id for m in self.ctx.messages if m.role == "tool" and m.tool_call_id
        }
        for msg in self.ctx.messages:
            if msg.role == "assistant" and msg.tool_calls:
                before = [t["id"] for t in msg.tool_calls]
                msg.tool_calls = [t for t in msg.tool_calls if t["id"] in valid_tool_ids]
                after = [t["id"] for t in msg.tool_calls]
                if before != after:
                    print(f"[[32mINFO[0m][approval] 同步裁剪 assistant.tool_calls: {before} → {after}", flush=True)

        print(f"[[32mINFO[0m][approval] 完成 | 上下文消息数={len(self.ctx.messages)}", flush=True)
        # 打印最后3条消息摘要
        for m in self.ctx.messages[-3:]:
            tc_ids = [t['id'] for t in (m.tool_calls or [])] if m.tool_calls else 'N/A'
            print(f"[[32mINFO[0m][approval]   role={m.role} tool_calls={tc_ids} tool_call_id={m.tool_call_id} content={m.content[:60]}", flush=True)
        return result

    def lookup_pending_call(self, call_id: str) -> bool:
        """检查 call_id 是否在待审批队列中（供路由层定位 session）。"""
        return call_id in self._pending_approvals

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
    # 核心循环（拆分为分析方法）
    # ------------------------------------------------------------------

    async def _run_core(self) -> AsyncGenerator[dict[str, Any], None]:
        """工具调用循环 → 流式最终回复。"""
        schemas = self.tools.get_schemas() if self.tools.list_all() else None

        for round_idx in range(10):
            _tools: Any = schemas if round_idx == 0 else None
            if round_idx == 0:
                self._is_continue = False
            print(f"[[32mINFO[0m][core] round={round_idx} | context消息数={len(self.ctx.messages)} | 携带tools={_tools is not None}", flush=True)
            result = await self.llm.chat_full(self.ctx.history, tools=_tools)

            if result.get("tool_calls"):
                tc_ids = [tc["id"] for tc in result["tool_calls"]]
                tc_names = [tc["function"]["name"] for tc in result["tool_calls"]]
                print(f"[[32mINFO[0m][core] LLM 返回 {len(result['tool_calls'])} 个 tool_calls: ids={tc_ids} names={tc_names}", flush=True)
                self.ctx._append(Message(
                    role="assistant", content="",
                    tool_calls=result["tool_calls"],                    reasoning_content=result.get("reasoning_content") or "",                ))
                print(f"[[32mINFO[0m][core] 已追加 assistant 消息到上下文 (位置={len(self.ctx.messages)-1}), tool_calls={tc_ids}", flush=True)
                async for event in self._process_tool_calls(result["tool_calls"]):
                    yield event
                if self._should_break:
                    print(f"[[32mINFO[0m][core] 因 _should_break=True 退出", flush=True)
                    return
            else:
                print(f"[[32mINFO[0m][core] LLM 返回纯文本 (无 tool_calls)", flush=True)
                async for event in self._stream_final_response():
                    yield event
                return

    async def _analyze_command_security(
        self, command: str
    ) -> tuple[dict[str, Any], dict[str, Any], Any | None, bool]:
        """规则 + LLM Flash 双重安全检查。

        Returns:
            (rule_event, flash_event, security_event, llm_needed)
            - rule_event: 规则匹配结果（秒出）
            - flash_event: Flash LLM 终裁结果
            - security_event: Interceptor 最终安全事件（始终基于 Flash 结果）
            - llm_needed: 规则无法判断时为 True
        """
        # 先推规则（秒出），再补 Flash 终裁（前端据此刷新）
        rule = Judge().analyze(command)
        llm_needed = (rule.verdict == "unknown")
        rule_event = {
            "type": "security_check",
            "call_id": "",
            "command": command,
            "summary": rule.summary,
            "danger": rule.danger,
            "verdict": rule.verdict if rule.verdict != "unknown" else "unknown",
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

        security_event = Interceptor().check(command, flash)
        return rule_event, flash_event, security_event, llm_needed

    async def _process_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """遍历并执行本轮所有工具调用。

        API 模式下每处理完一个 tool call 即挂起等待前端审批。
        """
        self._should_break = False
        processed_ids: list[str] = []
        api_mode = self.on_security_check is None
        print(f"[[32mINFO[0m][tool] 进入 _process_tool_calls | 共{len(tool_calls)}个TC | API模式={api_mode}", flush=True)

        for i, tc in enumerate(tool_calls):
            tc_id = tc["id"]
            name = tc["function"]["name"]
            tool = self.tools.get(name)
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, TypeError):
                args = {}

            print(f"[[32mINFO[0m][tool] TC[{i}] id={tc_id} name={name} args={args}", flush=True)
            yield {"type": "tool_call", "name": name, "args": args}

            if tool is None:
                tool_result = f"工具 {name} 未注册"
                print(f"[[32mINFO[0m][tool] TC[{i}] 工具未注册 → tool_result='{tool_result[:80]}'", flush=True)
                self.ctx.add_tool_message(tc_id, tool_result)
                yield {"type": "tool_result", "content": tool_result[:500]}
                processed_ids.append(tc_id)
                continue

            # ── 安全检查（仅 shell 命令） ──
            security_event = None
            llm_needed = True
            if name == "shell" and "command" in args:
                rule_event, flash_event, security_event, llm_needed = \
                    await self._analyze_command_security(args["command"])
                print(f"[[32mINFO[0m][security] TC[{i}] 安全检查: verdict={security_event.verdict} danger={security_event.danger} summary={security_event.summary}", flush=True)
                yield rule_event
                yield flash_event
            else:
                print(f"[[32mINFO[0m][security] TC[{i}] 非shell命令，跳过安全检查", flush=True)

            # ── 执行 / 审批分支 ──
            tool_msg_added = False
            if security_event:
                if self.on_security_check:
                    # CLI: 同步交互审批
                    print(f"[[32mINFO[0m][security] TC[{i}] CLI模式 → 调用 on_security_check", flush=True)
                    approved = self.on_security_check(
                        security_event.command,
                        security_event.summary,
                        security_event.danger,
                    )
                    print(f"[[32mINFO[0m][security] TC[{i}] CLI审批结果: approved={approved}", flush=True)
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
                        "tool_call_id": tc_id,
                        "args": args,
                    }
                    tool_result = (
                        f"⛔ 安全审查待确认 | call_id: {call_id} | "
                        f"命令: {args['command']} | "
                        f"意图: {security_event.summary} | "
                        f"危险等级: {security_event.danger}"
                    )
                    print(f"[[32mINFO[0m][tool] TC[{i}] API模式 → 挂起审批 call_id={call_id} pending_approvals keys={list(self._pending_approvals.keys())}", flush=True)
                    # ★ 先写待确认消息，再 yield tool_result（在审批事件之前），
                    #   避免生成器恢复后重复推送旧流
                    self.ctx.add_tool_message(tc_id, tool_result)
                    tool_msg_added = True
                    print(f"[[32mINFO[0m][tool] TC[{i}] 已写入 tool 消息(待确认), 上下文消息数={len(self.ctx.messages)}", flush=True)
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
                    # 命中规则时补 Flash 详细分析（带 call_id）
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
                    print(f"[[32mINFO[0m][tool] TC[{i}] 无安全事件 → 直接执行", flush=True)
                    tool_result = str(await tool.execute(**args))
                except Exception as e:
                    tool_result = f"工具执行失败: {e}"
                print(f"[[32mINFO[0m][tool] TC[{i}] 执行结果: '{tool_result[:80]}'", flush=True)

            if not tool_msg_added:
                self.ctx.add_tool_message(tc_id, tool_result)
                print(f"[[32mINFO[0m][tool] TC[{i}] 已写入 tool 消息(结果), 上下文消息数={len(self.ctx.messages)}", flush=True)
                yield {"type": "tool_result", "content": tool_result[:500]}
            processed_ids.append(tc_id)
            print(f"[[32mINFO[0m][tool] TC[{i}] processed_ids={processed_ids}", flush=True)

            # API 模式：统一挂起等前端审批（安全命令前端自动通过）
            if not self.on_security_check:
                # 向前查找 assistant(tool_calls) 消息（刚追加的 tool 消息在它后面）
                print(f"[[32mINFO[0m][tool] TC[{i}] API模式 → 开始裁剪 assistant.tool_calls", flush=True)
                found = False
                for j, msg in enumerate(reversed(self.ctx.messages)):
                    if msg.role == "assistant" and msg.tool_calls:
                        before_ids = [t["id"] for t in msg.tool_calls]
                        msg.tool_calls = [
                            t for t in msg.tool_calls if t["id"] in processed_ids
                        ]
                        after_ids = [t["id"] for t in msg.tool_calls]
                        print(f"[[32mINFO[0m][tool] TC[{i}] 裁剪 assistant.tool_calls: {before_ids} → {after_ids}", flush=True)
                        found = True
                        break
                if not found:
                    print(f"[[32mINFO[0m][tool] TC[{i}] ⚠️ 裁剪失败！未找到 assistant(tool_calls) 消息! 上下文最后5条:", flush=True)
                    for m in self.ctx.messages[-5:]:
                        print(f"[[32mINFO[0m][tool]   role={m.role} tool_calls={[t['id'] for t in (m.tool_calls or [])]} tool_call_id={m.tool_call_id}", flush=True)
                self._should_break = True
                print(f"[[32mINFO[0m][tool] TC[{i}] API模式 → _should_break=True, return", flush=True)
                return

        print(f"[[32mINFO[0m][tool] _process_tool_calls 完成 | 所有TC处理完毕 processed_ids={processed_ids}", flush=True)

    async def _stream_final_response(self) -> AsyncGenerator[dict[str, Any], None]:
        """流式产生 LLM 最终回复并写入上下文。"""
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
