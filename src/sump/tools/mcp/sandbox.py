"""沙箱隔离：超时 + 异常隔离执行工具"""

import asyncio
from typing import Any


class Sandbox:
    """在超时与异常隔离下执行工具调用。"""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def run(self, fn, /, **kwargs: Any) -> dict[str, Any]:
        """执行 fn(**kwargs)，带超时与异常隔离，返回结构化结果。

        返回 {"ok": True, "result": ...} 或 {"ok": False, "error": ...}。
        """
        try:
            result = await asyncio.wait_for(fn(**kwargs), timeout=self.timeout)
            return {"ok": True, "result": result}
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"工具执行超时（{self.timeout}s）"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
