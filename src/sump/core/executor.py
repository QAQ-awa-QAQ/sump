"""执行器（调度执行）"""

from sump.core.context import Context
from sump.core.models import LLMClient


class Executor:
    """按计划逐步执行任务，调用 LLM 完成具体步骤。"""

    def __init__(self, ctx: Context, llm: LLMClient) -> None:
        self.ctx = ctx
        self.llm = llm

    async def execute(self, plan: list[dict]) -> str:
        """执行计划并返回最终结果。"""
        result = ""
        for step in plan:
            action = step.get("action", "")
            if action == "respond":
                result = await self._stream_respond()
            else:
                result = f"[{action}] done"

        self.ctx.add_assistant_message(result)
        return result

    async def _stream_respond(self) -> str:
        """流式响应：实时打印思维链（dim 样式）和最终回复。"""
        thinking = False
        content_parts: list[str] = []

        async for chunk in self.llm.chat_stream(self.ctx.history):
            if chunk["type"] == "reasoning":
                if not thinking:
                    thinking = True
                    print("\n\033[2m── 深度思考 ──\033[0m", flush=True)
                print(f"\033[2m{chunk['text']}\033[0m", end="", flush=True)
            else:
                if thinking:
                    thinking = False
                    print("\n\033[2m── 回复 ──\033[0m")
                print(chunk["text"], end="", flush=True)
                content_parts.append(chunk["text"])

        if thinking:
            print()
        print()
        return "".join(content_parts)
