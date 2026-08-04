"""鏈€绠€绀轰緥锛氫娇鐢?SUMP Agent 杩涜瀵硅瘽"""

import asyncio

from sump.agent import Agent


async def main():
    agent = Agent()
    response = await agent.run("浣犲ソ锛岃浠嬬粛涓€涓嬩綘鑷繁")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())