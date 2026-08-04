"""鎬ц兘鍘嬫祴鑴氭湰"""

import asyncio
import time

from sump.agent import Agent


async def benchmark(rounds: int = 10):
    agent = Agent()
    start = time.perf_counter()

    for i in range(rounds):
        await agent.run(f"benchmark round {i}")

    elapsed = time.perf_counter() - start
    print(f"Completed {rounds} rounds in {elapsed:.2f}s")
    print(f"Average: {elapsed / rounds:.3f}s per round")


if __name__ == "__main__":
    asyncio.run(benchmark())