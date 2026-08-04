"""沙箱隔离"""


class Sandbox:
    """MCP 工具执行沙箱"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def run(self, tool_name: str, **kwargs) -> dict:
        """在沙箱中安全执行工具"""
        return {}
