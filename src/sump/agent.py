"""Agent 主类（对外入口）"""

from sump.config import Config
from sump.core.context import Context
from sump.core.planner import Planner
from sump.core.executor import Executor


class Agent:
    """SUMP Agent 主类"""

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.ctx = Context(self.config)

    async def run(self, user_input: str) -> str:
        """执行一轮对话"""
        self.ctx.add_user_message(user_input)
        planner = Planner(self.ctx)
        plan = await planner.plan()
        executor = Executor(self.ctx)
        result = await executor.execute(plan)
        return result
