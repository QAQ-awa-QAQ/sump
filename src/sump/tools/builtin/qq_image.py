"""QQ 发图工具（把表情包/本地图片发送到当前 QQ 会话）

仅在 NapCat QQ 场景注册（由插件注入 sender）；Web 场景不存在此工具。
"""

from pathlib import Path
from typing import Any

from sump.tools.base import Tool

MAX_IMAGE_BYTES = 32 * 1024 * 1024


class SendQQImageTool(Tool):
    """把本地图片发送到当前 QQ 会话（群聊/私聊）。"""

    name = "send_qq_image"
    description = (
        "把图片发送到当前 QQ 会话（群聊/私聊）。image 传本地图片路径——"
        "资产库里的表情包先用 asset_search 查到路径再发送；text 可选，附一句话。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "本地图片路径（如 asset_search 返回的路径）",
            },
            "text": {"type": "string", "description": "附带文字（可选）"},
        },
        "required": ["image"],
    }

    def __init__(self, sender: Any, session_id: str) -> None:
        self._sender = sender  # NapCatPlugin（鸭子类型，避免循环导入）
        self._session_id = session_id

    async def execute(self, image: str = "", text: str = "", **kwargs: Any) -> str:
        """发送图片到当前会话。"""
        path_text = image.strip()
        if not path_text:
            return "错误：缺少 image 参数（本地图片路径）"
        path = Path(path_text)
        if not path.is_file():
            return f"发送失败：找不到图片 {path_text}（表情包请先用 asset_search 查路径）"
        if path.stat().st_size > MAX_IMAGE_BYTES:
            return f"发送失败：图片超过 {MAX_IMAGE_BYTES // 1048576}MiB 上限"
        note = text.strip()
        error = await self._sender.send_image_to(self._session_id, str(path), note)
        if error:
            return f"发送失败：{error}"
        suffix = f"，附言：{note}" if note else ""
        return f"已发送图片 {path.name} 到当前会话{suffix}"
