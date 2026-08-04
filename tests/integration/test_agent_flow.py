"""Agent 流程集成测试"""

import pytest

from sump.agent import Agent


class TestAgentFlow:
    @pytest.mark.asyncio
    async def test_basic_run(self):
        agent = Agent()
        result = await agent.run("hello")
        assert isinstance(result, str)
