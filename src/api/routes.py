"""SUMP API 路由 —— REST + SSE 流式"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sump.agent import Agent
from sump.config import Config
from sump.core.sleep import get_sleep_manager
from sump.memory.archive import ArchiveMemory

router = APIRouter(prefix="/api")
config = Config()

# 归档历史（独立只读访问，供前端查看历史记录）
_archive = ArchiveMemory(config.get("memory.archive.db_path", "data/archive.db"))

# ---- Agent 实例池（按 session_id 隔离，避免并发串扰）----
_session_agents: dict[str, Agent] = {}


def _get_agent(session_id: str) -> Agent:
    """获取或创建 session 对应的 Agent 实例。"""
    if session_id not in _session_agents:
        agent = Agent(config)
        agent.switch_session(session_id)
        _session_agents[session_id] = agent
    return _session_agents[session_id]


def _any_agent() -> Agent:
    """获取任意 Agent 实例（仅用于跨 session 的 memory 查询操作）。"""
    if _session_agents:
        return next(iter(_session_agents.values()))
    return Agent(config)


# ---- 请求体模型 ----

class CreateSessionRequest(BaseModel):
    name: str = ""

class ChatRequest(BaseModel):
    message: str
    model: str = "deepseek-v4-flash"
    reasoning_effort: str = "high"
    thinking_enabled: bool = False

class UpdateSettingsRequest(BaseModel):
    model: str | None = None
    reasoning_effort: str | None = None
    thinking_enabled: bool | None = None

class RenameSessionRequest(BaseModel):
    name: str

# ---- 会话管理（统一走 Agent 持久化） ----

@router.post("/sessions")
async def create_session(body: CreateSessionRequest):
    # 先创建 session_id，再初始化对应 Agent 实例
    agent = Agent(config)
    sid = agent.new_session()
    _session_agents[sid] = agent
    return {"id": sid}


@router.get("/sessions")
async def list_sessions():
    return _any_agent().memory.list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    msgs = _any_agent().memory.load_messages(session_id)
    return {"id": session_id, "messages": msgs}


@router.post("/sessions/{session_id}/activate")
async def activate_session(session_id: str):
    agent = _get_agent(session_id)
    msgs = agent.memory.load_messages(session_id)
    return {"id": session_id, "message_count": len(msgs)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if not _any_agent().memory.delete_session(session_id):
        raise HTTPException(404, "会话不存在")
    # 清理实例池
    agent = _session_agents.pop(session_id, None)
    if agent and agent.session_id == session_id:
        agent.switch_session("default")
    return {"ok": True}


@router.put("/sessions/{session_id}")
async def rename_session(session_id: str, body: RenameSessionRequest):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "会话名不能为空")
    _any_agent().memory.upsert_session_name(session_id, name[:50])
    return {"ok": True, "name": name[:50]}


# ---- 对话（流式 SSE） ----

@router.post("/chat/{session_id}")
async def chat(session_id: str, body: ChatRequest):
    agent = _get_agent(session_id)
    # 每个 session 有独立 Agent，无需 switch_session
    agent.llm._backend._model = body.model
    agent.llm._backend._reasoning_effort = body.reasoning_effort
    agent.llm._backend._thinking_enabled = body.thinking_enabled

    async def event_stream():
        try:
            if body.message == "__continue__":
                # 审批后自动延续——不添加用户消息，直接让 LLM 继续
                yield "data: {\"type\":\"continue\",\"text\":\"审批完成，继续对话\"}\n\n"
                async for event in agent.run_core():
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {data}\n\n"
            else:
                # ── 会话命名：首条消息即写入初始名称 ──
                is_first = len(agent.memory.load_messages(session_id, limit=1)) == 0
                if is_first:
                    initial_name = body.message[:50]
                    agent.memory.upsert_session_name(session_id, initial_name)
                    yield f"data: {json.dumps({'type': 'session_name', 'session_id': session_id, 'name': initial_name}, ensure_ascii=False, separators=(',', ':'))}\n\n"

                async for event in agent.run_stream(body.message):
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {data}\n\n"

                # ── 首轮对话完成后：flash 模型总结标题并覆盖 ──
                if is_first:
                    title = await _summarize_title(agent, body.message)
                    if title:
                        agent.memory.upsert_session_name(session_id, title)
                        yield f"data: {json.dumps({'type': 'session_name', 'session_id': session_id, 'name': title}, ensure_ascii=False, separators=(',', ':'))}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            err = json.dumps({"type": "error", "text": str(e)}, ensure_ascii=False, separators=(",", ":"))
            yield f"data: {err}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- Flash 标题总结 ----

async def _summarize_title(agent: Agent, user_input: str) -> str:
    """用 flash 模型（无思考）对首轮对话总结一个短标题。"""
    try:
        # 取最后一条 assistant 消息作为回复
        reply = ""
        for m in reversed(agent.ctx.messages):
            if m.role == "assistant" and m.content:
                reply = m.content
                break

        prompt = (
            "请用10个字以内的简短中文标题概括以下对话主题，"
            "只输出标题本身，不要任何其他内容、标点或解释。\n\n"
            f"用户：{user_input[:200]}\n"
            f"助手：{reply[:300]}"
        )

        title = (await agent.llm.chat_flash(prompt, max_tokens=32, temperature=0.3)).strip()
        # 清理：去掉引号、书名号等
        for ch in "\"'""''《》「」":
            title = title.replace(ch, "")
        return title[:20] if title else ""
    except Exception:
        return ""


# ---- 模型列表 ----

@router.get("/models")
async def list_models():
    return [
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "description": "最强推理能力"},
        {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "description": "快速响应"},
    ]


# ---- 安全审批 ----

class ApproveRequest(BaseModel):
    call_id: str
    approved: bool


@router.post("/tools/approve")
async def approve_tool(body: ApproveRequest):
    # 按 call_id 定位所属 session 的 Agent 实例
    for session_id, agent in _session_agents.items():
        if agent.lookup_pending_call(body.call_id):
            result = await agent.approve_command(body.call_id, body.approved)
            return {"result": result[:500], "continue": True}
    raise HTTPException(404, "审批请求已过期或不存在")


# ---- 记忆整理（手动触发） ----

@router.post("/memory/consolidate")
async def consolidate_memory() -> dict[str, Any]:
    """手动触发一次记忆整理（不依赖睡眠窗口与空闲时长）。"""
    try:
        result = await get_sleep_manager().consolidate_now()
    except Exception as e:
        raise HTTPException(500, f"记忆整理失败: {e}")
    return {"ok": True, "result": result[:2000]}


# ---- 归档历史（前端查看历史记录） ----

@router.get("/archive/sessions")
async def list_archive_sessions() -> list[dict[str, Any]]:
    """列出已归档的历史会话（session_id + 标题 + 消息数）。"""
    return _archive.list_sessions()


@router.get("/archive/sessions/{session_id}")
async def get_archive_session(session_id: str) -> dict[str, Any]:
    """读取某个归档会话的完整消息副本（按时间正序）。"""
    msgs = _archive.load_messages(session_id)
    if not msgs:
        raise HTTPException(404, "归档会话不存在")
    return {"id": session_id, "messages": msgs}


@router.get("/archive/search")
async def search_archive(q: str = "") -> list[dict[str, Any]]:
    """全文检索归档消息（FTS5），返回命中消息（session_id + content）。"""
    if not q.strip():
        return []
    return _archive.search(q, top_k=20)
