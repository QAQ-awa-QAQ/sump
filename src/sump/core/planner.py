"""计划器（任务拆解）"""

from sump.core.context import Context


class Planner:
    """将用户输入拆解为可执行计划"""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    async def plan(self) -> list[dict]:
        """生成执行计划"""
        return [{"step": "execute", "input": self.ctx.messages[-1].content if self.ctx.messages else ""}]
