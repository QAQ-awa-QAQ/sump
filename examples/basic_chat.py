"""最简示例：使用 SUMP Agent 进行对话"""

import asyncio

from sump.agent import Agent


async def main():
    agent = Agent()
    response = await agent.run("你好，请介绍一下你自己")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
