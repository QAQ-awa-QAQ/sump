"""外部反馈收集"""


class ExternalFeedback:
    """收集外部反馈"""

    def __init__(self):
        self._feedback: list[dict] = []

    def record(self, user_rating: int, comment: str = "") -> None:
        """记录用户反馈"""
        self._feedback.append({"rating": user_rating, "comment": comment})

    def get_summary(self) -> dict:
        """获取反馈摘要"""
        if not self._feedback:
            return {"count": 0, "avg_rating": 0}
        ratings = [f["rating"] for f in self._feedback]
        return {"count": len(ratings), "avg_rating": sum(ratings) / len(ratings)}
