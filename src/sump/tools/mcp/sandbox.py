"""沙箱隔离"""

from typing import Any


class Sandbox:
    """MCP 工具执行沙箱"""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    async def run(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """在沙箱中安全执行工具"""
        return {}
