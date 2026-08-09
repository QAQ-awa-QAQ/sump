"""执行器（调度执行 + 工具调用循环）"""

import json

from sump.core.context import Context
from sump.core.models import LLMClient
from sump.tools.registry import ToolRegistry
from sump.types import Message


class Executor:
    """按计划逐步执行任务，支持 LLM 工具调用。"""

    def __init__(self, ctx: Context, llm: LLMClient, tools: ToolRegistry | None = None) -> None:
        self.ctx = ctx
        self.llm = llm
        self.tools = tools or ToolRegistry()

    async def execute(self, plan: list[dict]) -> str:
        """执行计划并返回最终结果。"""
        result = ""
        for step in plan:
            action = step.get("action", "")
            if action == "respond":
                result = (
                    await self._run_with_tools()
                    if self.tools.list_all()
                    else await self._stream_respond()
                )

        self.ctx.add_assistant_message(result)
        return result

    # ------------------------------------------------------------------
    # 工具调用循环
    # ------------------------------------------------------------------

    async def _run_with_tools(self) -> str:
        """LLM 可调用工具，循环直到给出最终回复。"""
        schemas = self.tools.get_schemas()
        max_loops = 10

        for _ in range(max_loops):
            result = await self.llm.chat_full(self.ctx.history, tools=schemas)

            if result["tool_calls"]:
                # 记录 assistant 的工具调用决策
                self.ctx.messages.append(Message(
                    role="assistant", content="",
                    tool_calls=result["tool_calls"],
                ))

                for tc in result["tool_calls"]:
                    name = tc["function"]["name"]
                    tool = self.tools.get(name)
                    if tool is None:
                        self.ctx.add_tool_message(tc["id"], f"工具 {name} 未注册")
                        continue

                    args = json.loads(tc["function"]["arguments"])
                    print(f"\n\033[33m🔧 调用工具: {name}({args})\033[0m", flush=True)
                    tool_result = await tool.execute(**args)
                    print(f"\033[33m📦 返回: {str(tool_result)[:200]}\033[0m", flush=True)
                    self.ctx.add_tool_message(tc["id"], str(tool_result))
            else:
                # 最终回复 —— 流式输出
                return await self._stream_respond()

        return "已达到最大工具调用轮次"

    # ------------------------------------------------------------------
    # 流式响应
    # ------------------------------------------------------------------

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
