"""手动记忆整理脚本：一次性执行记忆巩固并退出。

用法（项目根目录下）:
    python scripts/consolidate.py
"""

import asyncio
import sys

from sump.core.sleep import get_sleep_manager
from sump.debug.logger import setup_logger


async def main() -> int:
    setup_logger("INFO")
    print("开始记忆整理...")
    try:
        result = await get_sleep_manager().consolidate_now()
    except Exception as exc:  # noqa: BLE001
        print(f"记忆整理失败：{exc}")
        return 1
    print(f"记忆整理完成：{result}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
