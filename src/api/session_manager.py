"""会话管理器 —— 内存级会话存储"""

import uuid
from datetime import datetime, timezone
from typing import Any


class Session:
    """单个会话"""

    def __init__(self, name: str = "") -> None:
        self.id = str(uuid.uuid4())[:8]
        self.name = name or f"会话 {self.id}"
        self.created_at = datetime.now(timezone.utc)
        self.messages: list[dict[str, str]] = []
        self.settings: dict[str, Any] = {
            "model": "deepseek-v4-pro",
            "reasoning_effort": "high",
            "thinking_enabled": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "message_count": len(self.messages),
            "settings": self.settings,
        }


class SessionManager:
    """会话管理器（内存存储）"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, name: str = "") -> Session:
        session = Session(name)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_all(self) -> list[Session]:
        return list(self._sessions.values())

    def delete(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def update_settings(self, session_id: str, settings: dict[str, Any]) -> Session | None:
        session = self._sessions.get(session_id)
        if session:
            session.settings.update(settings)
        return session
