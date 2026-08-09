"""SUMP API 路由 —— REST + SSE 流式"""

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.session_manager import SessionManager
from sump.agent import Agent
from sump.config import Config

router = APIRouter(prefix="/api")
manager = SessionManager()
config = Config()

# ---- 全局 Agent（共享工具注册） ----
_agent: Agent | None = None


def _get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(config)
    return _agent


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

# ---- 会话管理 ----

@router.post("/sessions")
async def create_session(body: CreateSessionRequest):
    session = manager.create(body.name)
    return session.to_dict()


@router.get("/sessions")
async def list_sessions():
    return [s.to_dict() for s in manager.list_all()]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = manager.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return session.to_dict()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    if not manager.delete(session_id):
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


@router.put("/sessions/{session_id}/settings")
async def update_settings(session_id: str, body: UpdateSettingsRequest):
    settings = {k: v for k, v in body.model_dump().items() if v is not None}
    session = manager.update_settings(session_id, settings)
    if not session:
        raise HTTPException(404, "会话不存在")
    return session.to_dict()


# ---- 对话（流式 SSE） ----

@router.post("/chat/{session_id}")
async def chat(session_id: str, body: ChatRequest):
    session = manager.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    session.settings.update({
        "model": body.model,
        "reasoning_effort": body.reasoning_effort,
        "thinking_enabled": body.thinking_enabled,
    })

    agent = _get_agent()
    # 同步 Agent 会话到前端会话
    if agent.session_id != session_id:
        agent.switch_session(session_id)
    agent.llm._backend._model = body.model
    agent.llm._backend._reasoning_effort = body.reasoning_effort
    agent.llm._backend._thinking_enabled = body.thinking_enabled

    async def event_stream():
        try:
            async for event in agent.run_stream(body.message):
                data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"data: {data}\n\n"
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


# ---- 模型列表 ----

@router.get("/models")
async def list_models():
    return [
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "description": "最强推理能力"},
        {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "description": "快速响应"},
    ]


# ---- 记忆管理（委托 Agent 统一会话） ----

memory_router = APIRouter(prefix="/api/memory")


@memory_router.post("/sessions")
async def create_memory_session():
    agent = _get_agent()
    sid = agent.new_session()
    return {"id": sid}


@memory_router.get("/sessions")
async def list_memory_sessions():
    agent = _get_agent()
    return agent.memory.list_sessions()


@memory_router.get("/sessions/{session_id}")
async def get_memory_session(session_id: str):
    agent = _get_agent()
    return agent.memory.load_messages(session_id)


@memory_router.post("/sessions/{session_id}/activate")
async def activate_memory_session(session_id: str):
    agent = _get_agent()
    msgs = agent.memory.load_messages(session_id)
    if not msgs:
        raise HTTPException(404, "会话不存在")
    agent.switch_session(session_id)
    return {"id": session_id, "message_count": len(msgs)}


@memory_router.delete("/sessions/{session_id}")
async def delete_memory_session(session_id: str):
    agent = _get_agent()
    if not agent.memory.delete_session(session_id):
        raise HTTPException(404, "会话不存在")
    # 如果删的是当前会话，切回 default
    if agent.session_id == session_id:
        agent.switch_session("default")
    return {"ok": True}
