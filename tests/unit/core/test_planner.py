"""计划器测试"""

import pytest

from sump.core.context import Context
from sump.core.planner import Planner, Plan


class TestPlanner:
    @pytest.mark.asyncio
    async def test_plan_no_tools(self, config):
        ctx = Context(config)
        planner = Planner(ctx)
        plan = await planner.plan(tools_available=0)
        assert isinstance(plan, Plan)
        assert plan.tools_enabled is False

    @pytest.mark.asyncio
    async def test_plan_with_tools(self, config):
        ctx = Context(config)
        planner = Planner(ctx)
        plan = await planner.plan(tools_available=3, max_rounds=5)
        assert plan.tools_enabled is True
        assert plan.max_rounds == 5
