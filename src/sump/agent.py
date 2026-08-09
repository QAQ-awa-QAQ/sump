"""Agent 主类（对外入口）"""

from sump.config import Config
from sump.core.context import Context
from sump.core.executor import Executor
from sump.core.models import LLMClient
from sump.core.planner import Planner


class Agent:
    """SUMP Agent 主类。"""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.ctx = Context(self.config)
        self.llm = LLMClient(self.config)

    async def run(self, user_input: str) -> str:
        """执行一轮对话。"""
        self.ctx.add_user_message(user_input)
        plan = await Planner(self.ctx, self.llm).plan()
        return await Executor(self.ctx, self.llm).execute(plan)

    async def chat_loop(self) -> None:
        """交互式对话循环，输入 exit/quit/q 退出。"""
        print("SUMP Agent 已启动（输入 exit 退出）\n")
        while True:
            try:
                user_input = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见")
                break
            if user_input.lower() in ("exit", "quit", "q"):
                print("再见")
                break
            if not user_input:
                continue
            response = await self.run(user_input)
            print(f"\n{response}\n")
