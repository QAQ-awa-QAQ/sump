"""带记忆的示例：演示记忆系统用法"""

import asyncio

from sump.agent import Agent
from sump.config import Config


async def main():
    config = Config()
    agent = Agent(config)

    # 第一轮对话
    response = await agent.run("我的名字叫小明")
    print(f"第1轮: {response}")

    # 第二轮：Agent 应记住名字
    response = await agent.run("我叫什么名字？")
    print(f"第2轮: {response}")


if __name__ == "__main__":
    asyncio.run(main())
