"""计划器（分析上下文 → 生成执行计划）"""

from dataclasses import dataclass, field
from typing import Any

from sump.core.context import Context


@dataclass
class Plan:
    """执行计划。"""

    action: str = "respond"         # respond | multi_step
    tools_enabled: bool = False     # 是否允许工具调用
    max_rounds: int = 10            # 最大工具调用轮次
    reasoning: str = ""             # 计划推理说明（调试用）
    steps: list[dict[str, Any]] = field(default_factory=list)


class Planner:
    """分析对话上下文，决定执行策略。

    当前实现：检查是否有可用工具 → 生成 Plan。
    后续可接入 LLM 做复杂多步任务拆解。
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    async def plan(self, tools_available: int = 0, max_rounds: int = 10) -> Plan:
        """生成执行计划。

        Args:
            tools_available: 已注册工具数量
            max_rounds: 最大工具调用轮次（来自 config）

        Returns:
            Plan 用于 Executor 调度
        """
        return Plan(
            action="respond",
            tools_enabled=tools_available > 0,
            max_rounds=max_rounds,
            reasoning=f"工具可用: {tools_available}, 最大轮次: {max_rounds}",
        )
