"""LLM JSON 调用辅助：解析失败重试 + 日志。

记忆提取/聚合/去重/矛盾检测统一依赖 flash 模型输出 JSON。
此模块提供统一的 JSON 解析与重试语义：解析失败重试 N 次，
仍失败则返回 None 并写 error 日志（由上层决定是否保留原始数据）。
"""

import json
import logging
from typing import Any

logger = logging.getLogger("sump.consolidation")

DEFAULT_MAX_RETRIES = 3


def parse_json(raw: str) -> dict[str, Any] | None:
    """解析 flash 返回的 JSON（容忍 ```json 包装）。失败返回 None。"""
    try:
        text = raw.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, AttributeError):
        return None


async def chat_flash_json(
    llm: Any,
    prompt: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.3,
    max_retries: int = DEFAULT_MAX_RETRIES,
    label: str = "",
) -> dict[str, Any] | None:
    """调用 flash 并解析 JSON；解析/调用失败重试 max_retries 次。

    全部失败时返回 None 并写 error 日志。网络层重试由 LLMClient 自身保证，
    这里只兜底「模型返回了但无法解析为 JSON」的场景。
    """
    tag = label or "flash_json"
    last_raw = ""
    for attempt in range(1, max_retries + 1):
        try:
            raw = await llm.chat_flash(
                prompt, max_tokens=max_tokens, temperature=temperature
            )
        except Exception as exc:  # noqa: BLE001 - 兜底所有异常，保证重试语义
            logger.warning("%s: flash 调用异常（第 %d/%d 次）：%s", tag, attempt, max_retries, exc)
            continue
        last_raw = raw
        data = parse_json(raw)
        if data is not None:
            return data
        logger.warning("%s: JSON 解析失败（第 %d/%d 次）", tag, attempt, max_retries)
    logger.error(
        "%s: 重试 %d 次仍无法解析 JSON，放弃。最后输出前 200 字：%s",
        tag,
        max_retries,
        last_raw[:200],
    )
    return None
