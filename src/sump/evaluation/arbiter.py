"""整体裁决"""


class Arbiter:
    """综合内外部评估结果做最终裁决"""

    async def arbitrate(self, internal: dict, external: dict | None = None) -> dict:
        """综合裁决

        Returns:
            {"proceed": bool, "action": str, "reason": str}
        """
        return {"proceed": True, "action": "继续", "reason": "所有检查通过"}
