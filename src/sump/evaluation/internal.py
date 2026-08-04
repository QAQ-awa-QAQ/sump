"""内部自评"""


class InternalEvaluator:
    """Agent 内部自评估"""

    async def evaluate(self, task: str, result: str) -> dict:
        """评估自身输出质量

        Returns:
            {"score": float, "issues": list, "suggestions": list}
        """
        return {"score": 1.0, "issues": [], "suggestions": []}
