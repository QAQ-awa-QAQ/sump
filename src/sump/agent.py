"""Agent 主类 —— 委托 Planner（计划）+ Executor（执行），CLI/API 仅消费事件"""

import asyncio
import uuid as _uuid
from collections.abc import AsyncGenerator, Callable
from typing import Any

from sump.assets import AssetStore
from sump.config import Config
from sump.core.context import Context
from sump.core.executor import Executor
from sump.core.models import LLMClient, sanitize_marked_output
from sump.core.models.deepseek import supports_vision
from sump.core.planner import Planner
from sump.evaluation.arbiter import Arbiter
from sump.evaluation.internal import InternalEvaluator
from sump.event import AgentEvents, get_event_bus
from sump.memory.deep import DeepMemory
from sump.memory.persona import PersonaManager
from sump.memory.retriever import MemoryRetriever
from sump.memory.scene import SceneMemory
from sump.memory.session_memory import SessionMemory
from sump.memory.shallow import ShallowMemory
from sump.memory.working import WorkingMemory
from sump.skills.creator import SkillCreator
from sump.skills.manager import SkillManager
from sump.smart_home import from_config
from sump.tools.builtin.asset_tools import (
    AssetDeleteTool,
    AssetSaveTool,
    AssetSearchTool,
    AssetUpdateTool,
)
from sump.tools.builtin.image_vision import ImageVisionTool
from sump.tools.builtin.shell import ShellTool
from sump.tools.builtin.tool_index import ToolIndexTool
from sump.tools.builtin.wait import WaitTool
from sump.tools.mcp.client import MCPClient
from sump.tools.registry import ToolRegistry
from sump.types import Message, content_to_text

# 运行时硬性规范：每次拼入系统提示末尾，任何人格配置下都生效。
# 背景：模型偶尔以特殊标记文本形态泄漏工具调用意图，这类文本不进入标准
# 工具调用流水线（解析器明确不识别），只会被清洗剥离；此处从源头约束输出。
_RUNTIME_RULES = (
    "\n\n【工具调用硬性规范】\n"
    "- 调用工具必须使用标准工具调用协议（结构化 tool_calls）；\n"
    "- 严禁在正文文本中输出任何伪工具调用内容：特殊分隔符包裹的标记（如 DSML 标记）、"
    "伪 XML 标签、伪 JSON 调用文本等一律禁止；\n"
    "- 若当前无法使用标准协议，就直接用文字回复，不得伪造调用格式。"
)


class Agent:
    """SUMP Agent。

    唯一业务入口::

        async for event in agent.run_stream(user_input):
            # event: {type, ...} -> CLI 渲染 ANSI / API 渲染 SSE
    """

    def __init__(
        self, config: Config | None = None, deep_embedder: Any = None
    ) -> None:
        self.config = config or Config()
        self.memory = SessionMemory(self.config.get("memory.session.db_path", "data/memory.db"))
        self.ctx = Context(self.config)
        self.llm = LLMClient(self.config)
        self.tools = ToolRegistry()
        self.tools.register(ShellTool(
            platform=str(self.config.get("tools.builtin.shell.platform", "auto"))
        ))
        # 多模态主模型直读图片（图片块直发）→ 不挂额外识图工具；
        # 纯文本主模型（如 deepseek-v4-pro）挂 image_vision 兜底
        self._sync_image_tool()
        # 资产库（表情包等收藏；启动自动索引 assets/ 目录）
        self.assets = AssetStore(
            asset_dir=str(self.config.get("assets.dir", "assets")),
            db_path=str(self.config.get("assets.db_path", "data/assets.db")),
        )
        self.tools.register(AssetSaveTool(self.assets, self.ctx))
        self.tools.register(AssetSearchTool(self.assets))
        self.tools.register(AssetDeleteTool(self.assets))
        self.tools.register(AssetUpdateTool(self.assets))
        self.tools.register(WaitTool(
            max_seconds=int(self.config.get("tools.builtin.wait.max_seconds", 600))
        ))
        self.tools.register(ToolIndexTool(self.tools))
        self._session_id = "default"
        self._bus = get_event_bus()

        self.persona = PersonaManager(
            files=self.config.get("memory.soul.files", None),
            max_bytes=int(self.config.get("memory.soul.max_bytes", 5000)),
        )
        self.shallow_memory = ShallowMemory(
            self.config.get("memory.shallow.db_path", "data/shallow.db"),
            embedder=deep_embedder,
            embedder_cache_dir=self.config.get("memory.deep.embedding_cache", None),
        )
        self.deep_memory = DeepMemory(
            self.config.get("memory.deep.db_path", "data/deep.db"),
            embedder=deep_embedder,
            embedder_cache_dir=self.config.get("memory.deep.embedding_cache", None),
        )
        self.scene_memory = SceneMemory(
            self.config.get("memory.scene.db_path", "data/scene.db"),
            embedder=deep_embedder,
            embedder_cache_dir=self.config.get("memory.deep.embedding_cache", None),
        )
        self.working_memory = WorkingMemory(
            backend=self.config.get("memory.working.backend", "disk"),
            max_bytes=int(self.config.get("memory.working.max_bytes", 102400)),
            db_path=self.config.get("memory.working.db_path", "data/working.db"),
        )
        self.retriever = MemoryRetriever(
            self.deep_memory, self.shallow_memory, self.scene_memory,
            max_results=int(self.config.get("memory.recall.max_results", 5)),
            max_chars=int(self.config.get("memory.recall.max_chars", 800)),
            timeout=float(self.config.get("memory.recall.timeout", 3.0)),
            deep_inject_count=int(self.config.get("memory.deep.inject_count", 5)),
            core_max_chars=int(self.config.get("memory.recall.core_max_chars", 400)),
        )

        # 技能系统（加载已有技能 + 自动创建）
        self.skills = SkillManager()
        self.skills.discover(str(self.config.get("skills.permanent_dir", "skills/permanent")))
        self.skill_creator = SkillCreator(
            self.skills,
            llm=self.llm,
            skills_dir=str(self.config.get("skills.permanent_dir", "skills/permanent")),
            auto_create=bool(self.config.get("skills.auto_create", True)),
        )
        # MCP 客户端（延迟连接，由 connect_mcp 按配置建立）
        self.mcp = MCPClient()
        self._mcp_connected = False
        # 智能家居后端（可插拔，当前 none 占位）
        self.smart_home = from_config(self.config)

        self.ctx.on_message = self._persist_message
        self._load_session(self._session_id)

        # 安全审批状态
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._is_continue = False
        self.on_security_check: Callable[[str, str, str], bool] | None = None
        # 对话流串行锁：同一 Agent 的 run_stream / run_core 串行执行，防止并发交错写坏上下文
        self._run_lock = asyncio.Lock()

        # 子组件：Planner + Executor（含内部评估 + 裁决）
        self._planner = Planner(self.ctx)
        if bool(self.config.get("evaluation.enabled", True)):
            evaluator = InternalEvaluator(self.llm)
            arbiter = Arbiter(
                finish_threshold=float(self.config.get("evaluation.finish_threshold", 0.8)),
                retry_threshold=float(self.config.get("evaluation.retry_threshold", 0.5)),
            )
        else:
            evaluator = None
            arbiter = None
        self._executor = Executor(
            self.ctx, self.llm, self.tools,
            security_check=self._cli_security_check,
            on_approval_pending=self._api_approval_pending,
            evaluator=evaluator,
            arbiter=arbiter,
            tools_first_round_only=bool(
                self.config.get("agent.tools_first_round_only", True)
            ),
            tool_hint_every=int(self.config.get("agent.tool_hint_every", 7)),
        )

    # ------------------------------------------------------------------
    # 设置热更新
    # ------------------------------------------------------------------

    def apply_settings(self, settings: dict[str, Any]) -> None:
        """设置中心变更：热更新 LLM 后端 + 同步识图工具可用性。"""
        self.llm._backend.apply_settings(settings)
        self._sync_image_tool()

    def _sync_image_tool(self) -> None:
        """按当前主模型的多模态能力增删 image_vision 工具。"""
        vision = supports_vision(str(self.llm._backend._model))
        exists = self.tools.get("image_vision") is not None
        if vision and exists:
            self.tools.remove("image_vision")
        elif not vision and not exists:
            self.tools.register(ImageVisionTool(self.llm))

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
        inject_reasoning = bool(self.config.get("agent.inject_reasoning", False))
        for entry in valid:
            self.ctx.messages.append(Message(
                role=entry["role"],
                content=entry["content"],
                tool_call_id=entry.get("tool_call_id", ""),
                tool_calls=entry.get("tool_calls"),
                reasoning_content=(
                    entry.get("reasoning_content", "") if inject_reasoning else ""
                ),
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
        self,
        call_id: str,
        command: str,
        tool: Any,
        tc_id: str,
        args: dict[str, Any],
        summary: str = "",
        danger: str = "",
    ) -> None:
        """API: 挂起到 pending 队列，发布审批事件并启动超时定时器。"""
        self._pending_approvals[call_id] = {
            "command": command, "tool": tool,
            "tool_call_id": tc_id, "args": args,
        }
        asyncio.create_task(
            self._emit_approval_pending(call_id, command, summary, danger)
        )
        timeout = float(self.config.get("security.approval_timeout", 30))
        self._pending_approvals[call_id]["_timer"] = asyncio.create_task(
            self._approval_timeout(call_id, timeout)
        )

    async def _emit_approval_pending(
        self, call_id: str, command: str, summary: str, danger: str
    ) -> None:
        await self._bus.emit(
            AgentEvents.APPROVAL_PENDING,
            call_id=call_id,
            session_id=self._session_id,
            command=command,
            summary=summary,
            danger=danger,
        )

    async def _approval_timeout(self, call_id: str, timeout: float) -> None:
        await asyncio.sleep(timeout)
        if call_id in self._pending_approvals:
            await self._auto_reject(call_id)

    async def _auto_reject(self, call_id: str) -> None:
        """审批超时：自动拒绝并替换工具结果。"""
        pending = self._pending_approvals.pop(call_id, None)
        if not pending:
            return
        self._replace_tool_result(pending["tool_call_id"], "审批超时，已自动拒绝执行")
        await self._bus.emit(
            AgentEvents.APPROVAL_EXPIRED, call_id=call_id, session_id=self._session_id
        )

    async def approve_and_continue(self, call_id: str, approved: bool) -> str:
        """审批后继续执行（供插件/超时后调用），返回审批结果描述。"""
        result = await self.approve_command(call_id, approved)
        async for _ in self.run_core():
            pass
        return result

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

        self._replace_tool_result(pending["tool_call_id"], result)
        return result

    def _replace_tool_result(self, tool_call_id: str, result: str) -> None:
        """把待确认的 tool 消息替换为最终结果，并裁剪 assistant.tool_calls。"""
        tci = tool_call_id
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

    def lookup_pending_call(self, call_id: str) -> bool:
        return call_id in self._pending_approvals

    # ------------------------------------------------------------------
    # 唯一入口：Plan -> Execute
    # ------------------------------------------------------------------

    async def run_stream(
        self, user_input: str, images: list[str] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行一轮对话（同一 Agent 的对话流串行化，防并发交错）。

        images 为 data URL 或 http(s) 链接，随用户消息直发主模型（V4.1 原生视觉）。
        """
        async with self._run_lock:
            async for event in self._run_stream_inner(user_input, images):
                yield event

    async def _run_stream_inner(
        self, user_input: str, images: list[str] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """对话主体。流程: 更新工作记忆 -> 注入人格/记忆 -> 用户消息 -> Planner -> Executor。"""
        await self._ensure_mcp_connected()
        await self._update_working_memory(user_input)
        await self._inject_context(user_input)
        self.ctx.add_user_message(user_input, images)

        await self._bus.emit(
            AgentEvents.MESSAGE_RECEIVED, session_id=self._session_id, content=user_input
        )

        plan = await self._planner.plan(
            tools_available=len(self.tools.list_all()),
            max_rounds=self._max_rounds,
        )

        reply_parts: list[str] = []
        async for event in self._executor.execute(plan):
            etype = event.get("type")
            if etype == "tool_result":
                # 工具执行结果作为任务进度写入工作记忆
                self.working_memory.add_note(str(event.get("content", ""))[:200])
                await self._bus.emit(
                    AgentEvents.TOOL_RESULT,
                    session_id=self._session_id,
                    content=event.get("content", ""),
                )
            elif etype == "tool_call":
                await self._bus.emit(
                    AgentEvents.TOOL_CALL,
                    session_id=self._session_id,
                    name=event.get("name", ""),
                    args=event.get("args", {}),
                )
            elif etype == "content":
                reply_parts.append(str(event.get("text", "")))
            yield event

        # 出口清洗：伪调用标记文本绝不外发（QQ/CLI）
        cleaned = sanitize_marked_output("".join(reply_parts))
        if cleaned:
            await self._bus.emit(
                AgentEvents.REPLY,
                session_id=self._session_id,
                content=cleaned,
            )

    async def run_core(self) -> AsyncGenerator[dict[str, Any], None]:
        """延续执行（审批后 __continue__），不添加用户消息；与 run_stream 共用串行锁。"""
        async with self._run_lock:
            async for event in self._run_core_inner():
                yield event

    async def _run_core_inner(self) -> AsyncGenerator[dict[str, Any], None]:
        """延续执行主体。"""
        await self._inject_context(self._last_user_message())
        plan = await self._planner.plan(
            tools_available=len(self.tools.list_all()),
            max_rounds=self._max_rounds,
        )
        reply_parts: list[str] = []
        async for event in self._executor.execute(plan):
            if event.get("type") == "content":
                reply_parts.append(str(event.get("text", "")))
            yield event
        # 出口清洗：伪调用标记文本绝不外发（QQ/CLI）
        cleaned = sanitize_marked_output("".join(reply_parts))
        if cleaned:
            await self._bus.emit(
                AgentEvents.REPLY,
                session_id=self._session_id,
                content=cleaned,
            )

    async def _ensure_mcp_connected(self) -> None:
        """首次运行时按配置连接 MCP 服务器（幂等，失败不阻断主流程）。"""
        if self._mcp_connected:
            return
        self._mcp_connected = True
        try:
            registered = await self.connect_mcp()
        except Exception as e:  # noqa: BLE001
            print(f"[MCP] 连接失败（搜索工具不可用）: {e}", flush=True)
            return
        if registered:
            print(f"[MCP] 已注册工具: {registered}", flush=True)

    async def connect_mcp(self) -> list[str]:
        """按配置连接 MCP 服务器并把其工具注册进 ToolRegistry。"""
        if not bool(self.config.get("tools.mcp.enabled", False)):
            return []
        from sump.tools.mcp.sandbox import Sandbox
        from sump.tools.mcp.tool import register_mcp_tools

        servers = self.config.get("tools.mcp.servers", []) or []
        registered: list[str] = []
        for server in servers:
            name = str(server.get("name", ""))
            if not name:
                continue
            await self.mcp.connect(name, server)
            registered.extend(await register_mcp_tools(
                self.tools, self.mcp, name, sandbox=Sandbox()
            ))
        return registered

    async def _inject_context(self, user_input: str) -> None:
        """注入人格 + 工作记忆 + 召回记忆 + 技能作为 system prompt。"""
        prompt = self.persona.get_system_prompt()
        working = self._working_memory_context()
        if working:
            prompt = f"{prompt}\n\n{working}" if prompt else working
        recall = await self.retriever.recall(user_input)
        if recall:
            prompt = f"{prompt}\n\n{recall}" if prompt else recall
        skills = self._skills_prompt()
        if skills:
            prompt = f"{prompt}\n\n{skills}" if prompt else skills
        prompt = f"{prompt}{_RUNTIME_RULES}".strip()
        self.ctx.set_system_prompt(prompt)

    async def _update_working_memory(self, user_input: str) -> None:
        """flash 摘要任务目标 + 判断新/旧任务，更新跨会话任务进度。"""
        goal = self.working_memory.get_goal()
        if goal and await self._judge_new_task(goal, user_input):
            self.working_memory.clear()
            goal = ""
        if not goal:
            self.working_memory.set_goal(await self._summarize_goal(user_input))

    async def _summarize_goal(self, user_input: str) -> str:
        """flash 不思考：把用户输入概括为一句任务目标。"""
        prompt = f"用一句不超过 10 个字的话概括这个任务目标，只输出概括本身：{user_input}"
        try:
            result = await self.llm.chat_flash(prompt, max_tokens=32, temperature=0.3)
            return result.strip() or user_input[:50]
        except Exception:
            return user_input[:50]

    async def _judge_new_task(self, goal: str, user_input: str) -> bool:
        prompt = (
            f"当前进行中的任务：{goal}\n"
            f"用户新输入：{user_input}\n"
            "这是新任务的开始，还是旧任务的延续？只回答 new 或 continue。"
        )
        try:
            result = await self.llm.chat_flash(prompt, max_tokens=8, temperature=0.3)
            return "new" in result.lower()
        except Exception:
            return False

    def _working_memory_context(self) -> str:
        goal = self.working_memory.get_goal()
        if not goal:
            return ""
        lines = [f"- 任务目标：{goal}"]
        for note in self.working_memory.get_notes()[-5:]:
            lines.append(f"  - 进度：{note}")
        return "[进行中任务]\n" + "\n".join(lines)

    def _skills_prompt(self) -> str:
        """把已加载的技能拼成提示文本（无技能返回空串）。"""
        skills = self.skills.list_all()
        if not skills:
            return ""
        return "[可用技能]\n" + "\n".join(s.to_prompt() for s in skills)

    def _last_user_message(self) -> str:
        for m in reversed(self.ctx.messages):
            if m.role == "user":
                return content_to_text(m.content)
        return ""

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
