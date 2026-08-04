"""性能压测脚本"""

import asyncio
import time

from sump.agent import Agent


async def benchmark(rounds: int = 10):
    agent = Agent()
    start = time.perf_counter()

    for i in range(rounds):
        await agent.run(f"压测轮次 {i}")

    elapsed = time.perf_counter() - start
    print(f"完成 {rounds} 轮，耗时 {elapsed:.2f}s")
    print(f"平均: {elapsed / rounds:.3f}s/轮")


if __name__ == "__main__":
    asyncio.run(benchmark())
