"""SUMP API 路由 —— REST + SSE 流式"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.session_manager import SessionManager
from sump.core.models.deepseek import DeepSeekClient
from sump.config import Config

router = APIRouter(prefix="/api")
manager = SessionManager()
config = Config()

# ---- 请求体模型 ----

class CreateSessionRequest(BaseModel):
    name: str = ""

class ChatRequest(BaseModel):
    message: str
    model: str = "deepseek-v4-pro"
    reasoning_effort: str = "high"    # low | high | max
    thinking_enabled: bool = True

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

    # 更新会话设置
    session.settings.update({
        "model": body.model,
        "reasoning_effort": body.reasoning_effort,
        "thinking_enabled": body.thinking_enabled,
    })

    # 添加用户消息
    session.messages.append({"role": "user", "content": body.message})

    # 构建临时 client（使用会话级设置）
    client = _build_client(body)

    async def event_stream():
        try:
            async for chunk in client.chat_stream(session.messages):
                data = json.dumps(chunk, ensure_ascii=False)
                yield f"data: {data}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)}, ensure_ascii=False)}\n\n"

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


# ---- 辅助 ----

def _build_client(body: ChatRequest) -> DeepSeekClient:
    """用请求中的参数构建临时的 DeepSeek 客户端"""
    import os

    class _Override:
        pass

    c = _Override()
    c.get = lambda key, default=None: {  # type: ignore[attr-defined]
        "deepseek.api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "deepseek.base_url": "https://api.deepseek.com",
        "deepseek.model": body.model,
        "deepseek.reasoning_effort": body.reasoning_effort,
        "deepseek.thinking_enabled": body.thinking_enabled,
        "deepseek.max_tokens": 4096,
        "deepseek.temperature": 1.0,
    }.get(key, default)

    return DeepSeekClient(c)  # type: ignore[arg-type]
