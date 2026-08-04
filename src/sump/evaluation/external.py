"""澶栭儴鍙嶉鏀堕泦"""


class ExternalFeedback:
    """鏀堕泦澶栭儴鍙嶉"""

    def __init__(self):
        self._feedback: list[dict] = []

    def record(self, user_rating: int, comment: str = "") -> None:
        self._feedback.append({"rating": user_rating, "comment": comment})

    def get_summary(self) -> dict:
        if not self._feedback:
            return {"count": 0, "avg_rating": 0}
        ratings = [f["rating"] for f in self._feedback]
        return {"count": len(ratings), "avg_rating": sum(ratings) / len(ratings)}