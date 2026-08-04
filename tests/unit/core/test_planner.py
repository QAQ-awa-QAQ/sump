"""计划器测试"""

import pytest

from sump.core.context import Context
from sump.core.planner import Planner


class TestPlanner:
    @pytest.mark.asyncio
    async def test_plan(self, config):
        ctx = Context(config)
        ctx.add_user_message("hello")
        planner = Planner(ctx)
        plan = await planner.plan()
        assert isinstance(plan, list)
