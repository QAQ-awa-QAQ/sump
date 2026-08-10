"""MCP 客户端（Model Context Protocol）

支持 stdio 传输的 MCP 服务器连接，自动发现工具并注册到 ToolRegistry。

协议参考: https://spec.modelcontextprotocol.io/
"""

import asyncio
import json
import os
import subprocess
from typing import Any

MCP_VERSION = "2024-11-05"


class MCPServerConnection:
    """单个 MCP 服务器的 stdio 连接。"""

    def __init__(self, name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: subprocess.Popen[bytes] | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """启动 MCP 服务器子进程并完成初始化握手。"""
        merged_env = os.environ.copy()
        merged_env.update(self.env)

        self._process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
        )

        self._reader_task = asyncio.create_task(self._read_loop())

        # 初始化握手
        init_result = await self._request("initialize", {
            "protocolVersion": MCP_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "sump-mcp-client", "version": "0.1.0"},
        })

        # 发送 initialized 通知
        self._send_notification("notifications/initialized", {})

        _ = init_result  # 握手完成

    async def disconnect(self) -> None:
        """关闭连接。"""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """列出服务器提供的工具。"""
        result = await self._request("tools/list", {})
        tools: list[dict[str, Any]] = result.get("tools", [])
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用远程工具。"""
        return await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

    # ------------------------------------------------------------------
    # 内部：JSON-RPC 通信
    # ------------------------------------------------------------------

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        assert self._process and self._process.stdin
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self._process.stdin.write((msg + "\n").encode())
        self._process.stdin.flush()

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self._process and self._process.stdin
        self._request_id += 1
        rid = self._request_id
        msg = json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": method, "params": params,
        })
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        self._process.stdin.write((msg + "\n").encode())
        self._process.stdin.flush()
        return await fut

    async def _read_loop(self) -> None:
        """持续读取子进程 stdout，解析 JSON-RPC 响应。"""
        assert self._process and self._process.stdout
        loop = asyncio.get_event_loop()
        buffer = b""
        while True:
            try:
                chunk = await loop.run_in_executor(
                    None, self._process.stdout.read, 4096
                )
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self._handle_line(line.decode())
            except Exception:
                break

    def _handle_line(self, line: str) -> None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return

        rid = data.get("id")
        if rid is not None and rid in self._pending:
            fut = self._pending.pop(rid)
            if "result" in data:
                fut.set_result(data["result"])
            elif "error" in data:
                fut.set_exception(Exception(data["error"].get("message", "MCP error")))
            else:
                fut.set_result(data)


class MCPClient:
    """MCP 客户端：管理与多个 MCP 服务器的连接。

    使用方式::

        client = MCPClient()
        await client.connect("filesystem", {
            "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        })
        tools = await client.list_tools("filesystem")
        result = await client.call_tool("filesystem", "read_file", {"path": "/tmp/foo.txt"})
    """

    def __init__(self) -> None:
        self._connections: dict[str, MCPServerConnection] = {}

    async def connect(self, server_name: str, config: dict[str, Any]) -> None:
        """连接到 MCP 服务器。

        config:
            command: str  启动命令
            args: list[str] 命令行参数
            env: dict[str,str] 环境变量（可选）
        """
        if server_name in self._connections:
            await self._connections[server_name].disconnect()

        conn = MCPServerConnection(
            name=server_name,
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env", {}),
        )
        await conn.connect()
        self._connections[server_name] = conn

    async def disconnect(self, server_name: str) -> None:
        conn = self._connections.pop(server_name, None)
        if conn:
            await conn.disconnect()

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        conn = self._connections.get(server_name)
        if not conn:
            raise ValueError(f"MCP 服务器未连接: {server_name}")
        return await conn.list_tools()

    async def call_tool(
        self, server_name: str, tool_name: str, **kwargs: Any
    ) -> dict[str, Any]:
        conn = self._connections.get(server_name)
        if not conn:
            raise ValueError(f"MCP 服务器未连接: {server_name}")
        return await conn.call_tool(tool_name, dict(kwargs))

    @property
    def servers(self) -> list[str]:
        return list(self._connections.keys())
