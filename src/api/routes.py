"""SUMP API 路由 —— REST + SSE 流式"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sump.agent import Agent
from sump.config import Config

router = APIRouter(prefix="/api")
config = Config()

# ---- 全局 Agent ----
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

# ---- 会话管理（统一走 Agent 持久化） ----

@router.post("/sessions")
async def create_session(body: CreateSessionRequest):
    agent = _get_agent()
    sid = agent.new_session()
    return {"id": sid}


@router.get("/sessions")
async def list_sessions():
    agent = _get_agent()
    return agent.memory.list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    agent = _get_agent()
    msgs = agent.memory.load_messages(session_id)
    return {"id": session_id, "messages": msgs}


@router.post("/sessions/{session_id}/activate")
async def activate_session(session_id: str):
    agent = _get_agent()
    msgs = agent.memory.load_messages(session_id)
    agent.switch_session(session_id)
    return {"id": session_id, "message_count": len(msgs)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    agent = _get_agent()
    if not agent.memory.delete_session(session_id):
        raise HTTPException(404, "会话不存在")
    if agent.session_id == session_id:
        agent.switch_session("default")
    return {"ok": True}


# ---- 对话（流式 SSE） ----

@router.post("/chat/{session_id}")
async def chat(session_id: str, body: ChatRequest):
    agent = _get_agent()
    # 确保 Agent 在正确的会话上
    if agent.session_id != session_id:
        agent.switch_session(session_id)
    agent.llm._backend._model = body.model
    agent.llm._backend._reasoning_effort = body.reasoning_effort
    agent.llm._backend._thinking_enabled = body.thinking_enabled

    async def event_stream():
        try:
            if body.message == "__continue__":
                # 审批后自动延续——不添加用户消息，直接让 LLM 继续
                agent._is_continue = True
                yield "data: {\"type\":\"continue\",\"text\":\"审批完成，继续对话\"}\n\n"
                async for event in agent._run_core():
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {data}\n\n"
            else:
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


# ---- 安全审批 ----

class ApproveRequest(BaseModel):
    call_id: str
    approved: bool


@router.post("/tools/approve")
async def approve_tool(body: ApproveRequest):
    agent = _get_agent()
    result = await agent.approve_command(body.call_id, body.approved)
    return {"result": result[:500], "continue": True}
