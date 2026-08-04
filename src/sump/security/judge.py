"""审判官（综合评分裁决）"""


class Judge:
    """综合安全裁决"""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def decide(self, interceptor_result: bool, scanner_result: dict) -> dict:
        """综合裁决

        Returns:
            {"allow": bool, "reason": str}
        """
        if not interceptor_result:
            return {"allow": False, "reason": "被拦截器阻止"}
        if scanner_result.get("score", 1.0) < self.threshold:
            return {"allow": False, "reason": "低于安全阈值"}
        return {"allow": True, "reason": "通过"}
