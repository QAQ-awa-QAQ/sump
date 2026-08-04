"""甯﹁蹇嗙殑绀轰緥锛氭紨绀鸿蹇嗙郴缁熺敤娉?""

import asyncio

from sump.agent import Agent
from sump.config import Config


async def main():
    config = Config()
    agent = Agent(config)

    response = await agent.run("鎴戠殑鍚嶅瓧鍙皬鏄?)
    print(f"Round 1: {response}")

    response = await agent.run("鎴戝彨浠€涔堝悕瀛楋紵")
    print(f"Round 2: {response}")


if __name__ == "__main__":
    asyncio.run(main())