"""鍐呴儴鑷瘎"""


class InternalEvaluator:
    """Agent 鍐呴儴鑷瘎浼?""

    async def evaluate(self, task: str, result: str) -> dict:
        return {"score": 1.0, "issues": [], "suggestions": []}