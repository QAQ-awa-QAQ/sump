"""MCP 客户端"""


class MCPClient:
    """Model Context Protocol 客户端"""

    def __init__(self):
        self.servers: dict[str, dict] = {}

    async def connect(self, server_name: str, config: dict) -> None:
        """连接到 MCP 服务器"""
        pass

    async def list_tools(self, server_name: str) -> list[dict]:
        """列出服务器提供的工具"""
        return []

    async def call_tool(self, server_name: str, tool_name: str, **kwargs) -> dict:
        """调用远程工具"""
        return {}
