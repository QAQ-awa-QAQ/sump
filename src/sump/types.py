"""全局类型定义（Pydantic models）"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    WORKING = "working"
    SHALLOW = "shallow"
    DEEP = "deep"
    TASK = "task"


class SkillProficiency(str, Enum):
    INITIAL = "initial"
    HIGH = "high"
    LOW = "low"


class Message(BaseModel):
    role: str
    content: str
    tool_call_id: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    reasoning_content: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class MemoryEntry(BaseModel):
    id: str
    type: MemoryType
    content: Any
    metadata: dict = Field(default_factory=dict)
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
