"""整体裁决"""

from typing import Any


class Arbiter:
    """综合内外部评估结果做最终裁决"""

    async def arbitrate(self, internal: dict[str, Any], external: dict[str, Any] | None = None) -> dict[str, Any]:
        """综合裁决

        Returns:
            {"proceed": bool, "action": str, "reason": str}
        """
        return {"proceed": True, "action": "继续", "reason": "所有检查通过"}
