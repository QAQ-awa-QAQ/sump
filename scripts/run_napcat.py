"""独立运行 NapCat QQ 适配插件（不依赖 FastAPI 服务）。

用法（项目根目录下，需在 config 里设置 napcat.enabled: true）:
    python scripts/run_napcat.py
"""

import asyncio

from sump.debug.logger import setup_logger
from sump.plugins.builtin.napcat_plugin import NapCatPlugin


async def main() -> None:
    setup_logger("INFO")
    plugin = NapCatPlugin()
    await plugin.start()
    print("NapCat 插件已启动（Ctrl+C 退出）")
    try:
        await asyncio.Event().wait()  # 常驻运行
    finally:
        await plugin.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
