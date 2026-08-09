"""拦截器（依据 Judge 裁决执行动作）"""

from dataclasses import dataclass, field
from typing import Any

from sump.security.judge import Verdict


@dataclass
class SecurityEvent:
    """安全检查事件，推送给前端。"""
    command: str
    verdict: str  # "safe" | "risky"
    summary: str
    danger: str
    concerns: list[str] = field(default_factory=list)


class Interceptor:
    """执行安全裁决。risky 时产出事件等前端确认，safe 时可选通知。"""

    def check(self, command: str, verdict: Verdict, *, notify_safe: bool = False) -> SecurityEvent | None:
        """审查命令。

        - risky → 始终返回 SecurityEvent
        - safe  → notify_safe=True 时也返回（前端可展示，无需确认）
        """
        return SecurityEvent(
            command=command,
            verdict=verdict.verdict,
            summary=verdict.summary,
            danger=verdict.danger,
            concerns=verdict.concerns,
        )
