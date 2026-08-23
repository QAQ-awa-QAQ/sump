"""沙箱隔离执行测试：成功 / 异常 / 超时"""

import asyncio

import pytest

from sump.tools.mcp.sandbox import Sandbox


class TestSandbox:
    @pytest.mark.asyncio
    async def test_success(self):
        sb = Sandbox(timeout=1.0)

        async def ok(x: int) -> int:
            return x * 2

        assert await sb.run(ok, x=21) == {"ok": True, "result": 42}

    @pytest.mark.asyncio
    async def test_error_isolated(self):
        sb = Sandbox(timeout=1.0)

        async def boom(x: int) -> int:
            raise ValueError("bad input")

        result = await sb.run(boom, x=1)
        assert result["ok"] is False
        assert "bad input" in result["error"]

    @pytest.mark.asyncio
    async def test_timeout(self):
        sb = Sandbox(timeout=0.05)

        async def slow() -> int:
            await asyncio.sleep(1.0)
            return 1

        result = await sb.run(slow)
        assert result["ok"] is False
        assert "超时" in result["error"]
