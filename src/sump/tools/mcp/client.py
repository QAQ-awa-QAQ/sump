"""MCP 瀹㈡埛绔?""


class MCPClient:
    """Model Context Protocol 瀹㈡埛绔?""

    def __init__(self):
        self.servers: dict[str, dict] = {}

    async def connect(self, server_name: str, config: dict) -> None:
        """杩炴帴鍒?MCP 鏈嶅姟鍣?""
        pass

    async def list_tools(self, server_name: str) -> list[dict]:
        """鍒楀嚭鏈嶅姟鍣ㄦ彁渚涚殑宸ュ叿"""
        return []

    async def call_tool(self, server_name: str, tool_name: str, **kwargs) -> dict:
        """璋冪敤杩滅▼宸ュ叿"""
        return {}