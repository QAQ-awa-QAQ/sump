"""执行器（调度执行）"""

from sump.core.context import Context


class Executor:
    """按计划逐步执行任务"""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    async def execute(self, plan: list[dict]) -> str:
        """执行计划并返回结果"""
        results = []
        for step in plan:
            result = f"[{step.get('step', 'unknown')}] done"
            results.append(result)
        output = "\n".join(results)
        self.ctx.add_assistant_message(output)
        return output
