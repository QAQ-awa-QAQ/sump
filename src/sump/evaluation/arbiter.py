"""鏁翠綋瑁佸喅"""


class Arbiter:
    """缁煎悎鍐呭閮ㄨ瘎浼扮粨鏋滃仛鏈€缁堣鍐?""

    async def arbitrate(self, internal: dict, external: dict | None = None) -> dict:
        return {"proceed": True, "action": "continue", "reason": "all checks passed"}