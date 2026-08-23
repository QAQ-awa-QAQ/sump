"""图像理解工具（deepseek-v4-flash-vision-exp）

作为工具存在，不替换主模型：Agent 在需要识别图片时调用本工具，
工具内部走视觉模型，返回文字描述。
"""

import base64
import logging
import time
from pathlib import Path
from typing import Any

from sump.tools.base import Tool

logger = logging.getLogger("sump.image_vision")


def _guess_mime(data: bytes) -> str:
    """按文件实际内容判断图片格式（而非文件名）。"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class ImageVisionTool(Tool):
    """识别图片内容：描述图片、识别截图文字、分析图表。"""

    name = "image_vision"
    description = (
        "识别图片内容（描述图片、识别截图文字、分析图表）。"
        "image 参数填本地图片路径或 http(s) 图片 URL。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "图片本地路径或 http(s) URL",
            },
            "question": {
                "type": "string",
                "description": "要问的问题，缺省为'描述这张图片'",
            },
        },
        "required": ["image"],
    }

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def execute(self, image: str = "", question: str = "", **kwargs: Any) -> str:
        """识别图片，返回文字描述。"""
        if not image:
            return "错误：缺少图片路径或 URL"
        url = self._to_image_url(image)
        if url is None:
            return f"错误：无法读取图片：{image}"
        prompt = question.strip() or "描述这张图片"

        logger.info("开始识别图片：%s（编码后 %d 字符）", image, len(url))
        start = time.monotonic()
        try:
            result = await self._llm.chat_vision(prompt, url)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - start
            logger.error("图片识别失败（%.1fs）：%s", elapsed, exc)
            return f"识别失败：{exc}"
        elapsed = time.monotonic() - start
        logger.info("图片识别完成（%.1fs），结果 %d 字符", elapsed, len(result))
        return result

    @staticmethod
    def _to_image_url(image: str) -> str | None:
        """把本地路径/URL 转成可直接传给视觉模型的图片 URL。"""
        if image.startswith(("http://", "https://", "data:image/")):
            return image
        path = Path(image)
        if not path.is_file():
            return None
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{_guess_mime(data)};base64,{b64}"
