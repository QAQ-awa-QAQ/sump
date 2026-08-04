"""瀹″垽瀹橈紙缁煎悎璇勫垎瑁佸喅锛?""


class Judge:
    """缁煎悎瀹夊叏瑁佸喅"""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def decide(self, interceptor_result: bool, scanner_result: dict) -> dict:
        if not interceptor_result:
            return {"allow": False, "reason": "blocked by interceptor"}
        if scanner_result.get("score", 1.0) < self.threshold:
            return {"allow": False, "reason": "below safety threshold"}
        return {"allow": True, "reason": "passed"}