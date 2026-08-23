"""整体裁决"""

from typing import Any


class Arbiter:
    """综合内外部评估结果做最终裁决。"""

    def __init__(self, finish_threshold: float = 0.8, retry_threshold: float = 0.5) -> None:
        self._finish_threshold = finish_threshold
        self._retry_threshold = retry_threshold

    async def arbitrate(
        self, internal: dict[str, Any], external: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """综合裁决

        Returns:
            {"proceed": bool, "action": "finish"|"continue"|"retry", "reason": str}
        """
        done = bool(internal.get("done", False))
        score = float(internal.get("score", 0.0))
        issues = internal.get("issues", []) or []

        if done or score >= self._finish_threshold:
            return {"proceed": False, "action": "finish", "reason": "任务已完成"}
        if score < self._retry_threshold:
            reason = "；".join(issues) if issues else "评估分数过低"
            return {"proceed": True, "action": "retry", "reason": reason}
        return {"proceed": True, "action": "continue", "reason": "任务进行中"}
