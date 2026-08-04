"""娌欑闅旂"""


class Sandbox:
    """MCP 宸ュ叿鎵ц娌欑"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def run(self, tool_name: str, **kwargs) -> dict:
        """鍦ㄦ矙绠变腑鎵ц宸ュ叿"""
        return {}