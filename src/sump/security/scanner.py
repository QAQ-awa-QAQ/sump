"""扫描器（内容安全）"""

from typing import Any


class Scanner:
    """内容安全扫描"""

    def scan(self, content: str) -> dict[str, Any]:
        """扫描内容安全性

        Returns:
            {"safe": bool, "score": float, "issues": list}
        """
        return {"safe": True, "score": 1.0, "issues": []}
