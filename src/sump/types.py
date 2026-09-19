"""全局类型定义（Pydantic models）"""

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    WORKING = "working"
    SESSION = "session"
    SHALLOW = "shallow"
    DEEP = "deep"
    TASK = "task"


class SkillProficiency(str, Enum):
    INITIAL = "initial"
    HIGH = "high"
    LOW = "low"


# 多模态内容块（OpenAI 兼容：text / image_url，DeepSeek V4.1 原生支持）
ContentBlock = dict[str, Any]
MessageContent = str | list[ContentBlock]


class Message(BaseModel):
    role: str
    content: MessageContent
    tool_call_id: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


def build_user_content(text: str, images: list[str] | None = None) -> MessageContent:
    """构造用户消息 content：无图返回纯文本；有图返回块数组（text + image_url）。

    images 中每项为 data URL（data:image/...;base64,...）或 http(s) 图片链接。
    """
    if not images:
        return text
    blocks: list[ContentBlock] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for url in images:
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def content_has_images(content: MessageContent) -> bool:
    """判断消息内容是否为包含图片块的多模态数组。"""
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "image_url" for b in content
    )


def content_to_text(content: MessageContent, image_placeholder: str = "[图片]") -> str:
    """把多模态内容还原为纯文本（图片块转为占位符），供提炼 / 提示词 / 展示使用。"""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = str(block.get("text", ""))
            if text:
                parts.append(text)
        elif btype == "image_url":
            parts.append(image_placeholder)
    return "\n".join(parts)


def serialize_content(content: MessageContent) -> str:
    """多模态内容序列化为 JSON 字符串；纯文本原样返回（SQLite 持久化用）。"""
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return content


def parse_content(raw: str) -> MessageContent:
    """还原持久化的多模态内容（JSON 块数组）；普通文本原样返回。"""
    if not raw.startswith("[{"):
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(data, list) and all(
        isinstance(b, dict) and b.get("type") in ("text", "image_url", "file")
        for b in data
    ):
        return data
    return raw


class MemoryEntry(BaseModel):
    id: str
    type: MemoryType
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class Task(BaseModel):
    id: str
    description: str
    expected_result: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.now)


class AgentConfig(BaseModel):
    name: str = "SUMP"
    model: str = "gpt-4o"
    max_rounds: int = 50
    temperature: float = 0.7
