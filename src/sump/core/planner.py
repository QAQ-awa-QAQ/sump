"""计划器（任务拆解）"""

from sump.core.context import Context
from sump.core.models import LLMClient


class Planner:
    """将对话上下文拆解为可执行计划。"""

    def __init__(self, ctx: Context, llm: LLMClient) -> None:
        self.ctx = ctx
        self.llm = llm

    async def plan(self) -> list[dict]:
        """生成执行计划。

        当前最小实现：直接返回 respond 动作，
        后续可接入 LLM 做复杂任务拆解。
        """
        return [{"action": "respond"}]
