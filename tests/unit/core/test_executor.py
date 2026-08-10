"""执行器测试"""

import pytest

from sump.core.context import Context
from sump.core.executor import Executor
from sump.core.planner import Plan
from sump.tools.registry import ToolRegistry
from tests.conftest import MockLLMClient


class TestExecutor:
    @pytest.mark.asyncio
    async def test_execute_no_tools(self, config, ctx):
        """无工具 Plan：应直接流式回复。"""
        llm = MockLLMClient([{"content": "hello", "tool_calls": None}])
        tools = ToolRegistry()
        executor = Executor(ctx, llm, tools)
        plan = Plan(action="respond", tools_enabled=False)

        events = []
        async for event in executor.execute(plan):
            events.append(event)

        content_events = [e for e in events if e["type"] == "content"]
        assert len(content_events) > 0

    @pytest.mark.asyncio
    async def test_execute_with_tools_no_registry(self, config, ctx):
        """tools_enabled=True 但 ToolRegistry 为空：退化为无工具流。"""
        llm = MockLLMClient([{"content": "hi", "tool_calls": None}])
        tools = ToolRegistry()
        executor = Executor(ctx, llm, tools)
        plan = Plan(action="respond", tools_enabled=True)

        events = []
        async for event in executor.execute(plan):
            events.append(event)
        # 应直接走 _stream_final
        assert any(e["type"] == "content" for e in events)
