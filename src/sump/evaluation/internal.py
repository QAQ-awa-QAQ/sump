"""内部自评（v4-flash 不思考）"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger("sump.evaluation")


class InternalEvaluator:
    """Agent 内部自评估：用 flash 模型判断任务是否完成。"""

    def __init__(self, llm: Any | None = None, timeout: float = 8.0) -> None:
        self._llm = llm
        self._timeout = timeout

    async def evaluate(self, task: str, result: str) -> dict[str, Any]:
        """评估当前进展，返回 done/score/issues/suggestions。"""
        fallback = {"done": False, "score": 0.0, "issues": [], "suggestions": []}
        if self._llm is None:
            return fallback

        from sump.memory._llm_json import chat_flash_json

        prompt = (
            "判断以下任务是否已经完成，并评估当前进展质量。\n"
            f"任务：{task}\n"
            f"当前执行结果：{result}\n\n"
            "只输出 JSON，不要 markdown、不要解释：\n"
            '{"done": bool, "score": 0到1的小数, "issues": ["问题"], "suggestions": ["建议"]}\n'
            "任务已完成或进展充分则 done=true，否则 done=false。"
        )
        try:
            data = await asyncio.wait_for(
                chat_flash_json(
                    self._llm,
                    prompt,
                    max_tokens=256,
                    temperature=0.3,
                    label="internal_evaluator",
                ),
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("评估器超时/失败（%.1fs）：%s，降级为继续执行", self._timeout, exc)
            data = None
        if data is None:
            return fallback
        try:
            score = float(data.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return {
            "done": bool(data.get("done", False)),
            "score": max(0.0, min(1.0, score)),
            "issues": [str(x) for x in data.get("issues", []) or []],
            "suggestions": [str(x) for x in data.get("suggestions", []) or []],
        }
