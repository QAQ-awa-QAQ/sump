"""CLI 交互 —— 消费 Agent.run_stream() 事件，渲染终端"""

import asyncio

from sump.agent import Agent
from sump.core.sleep import get_sleep_manager
from sump.debug.logger import setup_logger


RESET = "\033[0m"
DIM = "\033[2m"
YELLOW = "\033[33m"


async def main():
    setup_logger("INFO")
    agent = Agent()

    def security_prompt(command: str, summary: str, danger: str) -> bool:
        """CLI 安全审批回调。"""
        print(f"\n🛡️ {summary} | 危险: {danger}")
        print(f"   命令: {command}")
        while True:
            choice = input("   是否放行? [y/N]: ").strip().lower()
            if choice in ("y", "yes"):
                return True
            if choice in ("", "n", "no"):
                return False

    agent.on_security_check = security_prompt

    print("SUMP Agent 已启动（输入 exit 退出，/consolidate 手动巩固记忆）\n")

    while True:
        try:
            user_input = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if user_input.lower() in ("exit", "quit", "q"):
            print("再见")
            break
        if user_input == "/consolidate":
            print("整理记忆中...")
            try:
                result = await get_sleep_manager().consolidate_now()
                print(f"记忆整理完成：{result}")
            except Exception as e:
                print(f"记忆整理失败：{e}")
            continue
        if not user_input:
            continue

        thinking = False
        async for event in agent.run_stream(user_input):
            t = event["type"]
            if t == "tool_call":
                print(f"\n{YELLOW}🔧 调用工具: {event['name']}({event['args']}){RESET}", flush=True)
            elif t == "tool_result":
                print(f"{YELLOW}📦 返回: {event['content'][:200]}{RESET}", flush=True)
            elif t == "reasoning":
                if not thinking:
                    thinking = True
                    print(f"\n{DIM}── 深度思考 ──{RESET}", flush=True)
                print(f"{DIM}{event['text']}{RESET}", end="", flush=True)
            elif t == "content":
                if thinking:
                    thinking = False
                    print(f"\n{DIM}── 回复 ──{RESET}")
                print(event["text"], end="", flush=True)

        if thinking:
            print()
        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
