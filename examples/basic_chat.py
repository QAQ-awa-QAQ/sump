"""最简示例：使用 SUMP Agent 进行交互式对话"""

import asyncio

from sump.agent import Agent


async def main():
    agent = Agent()
    await agent.chat_loop()


if __name__ == "__main__":
    asyncio.run(main())
