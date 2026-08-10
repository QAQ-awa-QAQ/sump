"""外部反馈收集"""

from typing import Any


class ExternalFeedback:
    """收集外部反馈"""

    def __init__(self) -> None:
        self._feedback: list[dict[str, Any]] = []

    def record(self, user_rating: int, comment: str = "") -> None:
        """记录用户反馈"""
        self._feedback.append({"rating": user_rating, "comment": comment})

    def get_summary(self) -> dict[str, Any]:
        """获取反馈摘要"""
        if not self._feedback:
            return {"count": 0, "avg_rating": 0}
        ratings = [f["rating"] for f in self._feedback]
        return {"count": len(ratings), "avg_rating": sum(ratings) / len(ratings)}
