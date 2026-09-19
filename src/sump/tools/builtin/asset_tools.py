"""资产库工具（保存 / 检索"有意思的东西"，如表情包、收藏图）

- asset_save：把图片/文件收藏进资产库，必须写一句描述；支持从会话消息取图
- asset_search：按关键词检索资产，返回描述与本地路径
"""

import base64
import re
from pathlib import Path
from typing import Any

from sump.assets import MAX_ASSET_BYTES, AssetStore, guess_asset_ext
from sump.tools.base import Tool

# data URL 头部的 MIME → 扩展名
_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _check_size(data: bytes) -> None:
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError(f"文件超过 {MAX_ASSET_BYTES // 1048576}MiB 上限")


def _decode_data_url(url: str) -> tuple[bytes, str]:
    """解码 data URL，返回 (字节, 扩展名)。"""
    head, _, b64 = url.partition(",")
    mime = head.removeprefix("data:").split(";", 1)[0]
    try:
        data = base64.b64decode(b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"data URL 解码失败：{exc}") from exc
    _check_size(data)
    return data, _MIME_EXT.get(mime, guess_asset_ext(data))


class AssetSaveTool(Tool):
    """保存资产到资产库（必须写描述）。"""

    name = "asset_save"
    description = (
        "把有意思的东西（表情包、图片、文件）收藏进资产库，必须写一句描述方便以后检索。"
        "source 三种写法：msg:N（从最近第 N 条用户消息里取图，1=最新，"
        "用户刚发的图用 msg:1）；http(s) 图片链接；本地文件路径。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "图片来源：msg:N / http(s) 链接 / 本地文件路径",
            },
            "description": {
                "type": "string",
                "description": "资产描述（必填，一句话说明内容与用途，用于以后检索）",
            },
            "tags": {
                "type": "string",
                "description": "标签，逗号分隔（可选），例如：表情包,猫,搞笑",
            },
        },
        "required": ["source", "description"],
    }

    def __init__(self, store: AssetStore, ctx: Any) -> None:
        self._store = store
        self._ctx = ctx

    async def execute(
        self, source: str = "", description: str = "", tags: str = "", **kwargs: Any
    ) -> str:
        """保存资产，返回已保存条目信息。"""
        desc = description.strip()
        if not desc:
            return "错误：必须为资产写一句描述（description 参数），否则以后无法检索"
        src = source.strip()
        if not src:
            return "错误：缺少 source 参数（msg:N / http(s) 链接 / 本地文件路径）"
        tag_list = [t.strip() for t in re.split(r"[,，]", tags) if t.strip()]

        try:
            data, ext, note = await self._load_source(src)
        except Exception as exc:  # noqa: BLE001
            return f"保存失败：{exc}"

        entry = self._store.save_bytes(data, description=desc, tags=tag_list, ext=ext)
        dup = "（内容已存在，未重复保存）" if entry.get("duplicated") else ""
        size_kb = max(1, int(entry["size"]) // 1024)
        tag_text = "、".join(tag_list) if tag_list else "无"
        return (
            f"已保存进资产库{dup}：[资产 #{entry['id']}] {desc}"
            f"（标签：{tag_text}，{size_kb}KB，路径：{entry['path']}）{note}"
        )

    # ------------------------------------------------------------------
    # 图片来源解析
    # ------------------------------------------------------------------

    async def _load_source(self, src: str) -> tuple[bytes, str, str]:
        """解析 source 得到 (文件字节, 扩展名, 附注)。失败抛 ValueError。"""
        m = re.fullmatch(r"msg[:：]\s*(\d+)", src)
        if m:
            return self._from_message(int(m.group(1)))
        if src.startswith("data:image/"):
            data, ext = _decode_data_url(src)
            return data, ext, ""
        if src.startswith(("http://", "https://")):
            return await self._from_url(src)
        path = Path(src)
        if path.is_file():
            data = path.read_bytes()
            _check_size(data)
            ext = path.suffix.lower() or guess_asset_ext(data)
            return data, ext, ""
        raise ValueError(f"无法识别的 source：{src}（支持 msg:N / http(s) 链接 / 本地文件路径）")

    def _from_message(self, n: int) -> tuple[bytes, str, str]:
        """从最近第 N 条用户消息中提取第一张图片。"""
        user_msgs = [m for m in self._ctx.messages if m.role == "user"]
        if n < 1 or n > len(user_msgs):
            raise ValueError(f"没有第 {n} 条用户消息（当前会话共 {len(user_msgs)} 条）")
        msg = user_msgs[-n]
        images: list[str] = []
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "image_url":
                    url = str((block.get("image_url") or {}).get("url", ""))
                    if url:
                        images.append(url)
        if not images:
            raise ValueError(f"最近第 {n} 条用户消息里没有图片")
        first = images[0]
        if not first.startswith("data:image/"):
            raise ValueError("该消息的图片是外链，请直接用链接调用本工具")
        data, ext = _decode_data_url(first)
        note = f"（该消息共 {len(images)} 张图，已保存第 1 张）" if len(images) > 1 else ""
        return data, ext, note

    async def _from_url(self, url: str) -> tuple[bytes, str, str]:
        """下载 http(s) 链接内容。"""
        import httpx

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
        _check_size(data)
        ext = guess_asset_ext(data, fallback="")
        if not ext:
            suffix = Path(url.split("?", 1)[0]).suffix.lower()
            ext = suffix if suffix else ".bin"
        return data, ext, ""


class AssetSearchTool(Tool):
    """检索资产库中的收藏。"""

    name = "asset_search"
    description = (
        "检索资产库（表情包等收藏）。query 填关键词（描述/标签/文件名，可留空列出最近收藏），"
        "返回条目含描述与本地文件路径，可直接引用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "关键词；留空列出最近收藏"},
            "top_k": {"type": "integer", "description": "返回条数上限（默认 5）"},
        },
    }

    def __init__(self, store: AssetStore) -> None:
        self._store = store

    async def execute(self, query: str = "", top_k: Any = 5, **kwargs: Any) -> str:
        """检索资产并格式化返回。"""
        try:
            limit = max(1, min(int(top_k or 5), 20))
        except (TypeError, ValueError):
            limit = 5
        entries = self._store.search(query, top_k=limit)
        if not entries:
            if query.strip():
                return f"资产库没有匹配「{query}」的资产"
            return "资产库还是空的（可以用 asset_save 收藏表情包等）"
        lines: list[str] = []
        for e in entries:
            tags = "、".join(e["tags"]) if e["tags"] else "无"
            desc = e["description"] or "（未描述）"
            lines.append(f"[资产 #{e['id']}] {desc} | 标签：{tags} | 路径：{e['path']}")
        return "\n".join(lines)


class AssetDeleteTool(Tool):
    """删除资产库中的资产（软删除，可恢复）。"""

    name = "asset_delete"
    description = (
        "删除资产库中的资产（从检索结果里拿 id）。删除是软删除：文件移入 "
        "assets/.trash/ 目录可人工恢复，索引条目清除。确认该资产确实不要了再删。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "资产编号（asset_search 结果里的 #编号）"},
        },
        "required": ["id"],
    }

    def __init__(self, store: AssetStore) -> None:
        self._store = store

    async def execute(self, id: Any = None, **kwargs: Any) -> str:
        """按 id 删除资产。"""
        try:
            asset_id = int(id)
        except (TypeError, ValueError):
            return "错误：缺少有效的 id 参数（资产编号）"
        entry = self._store.delete(asset_id)
        if entry is None:
            return f"删除失败：没有编号为 #{asset_id} 的资产"
        desc = entry["description"] or entry["filename"]
        return f"已删除 [资产 #{asset_id}] {desc}（文件已移入 assets/.trash/，需要可人工恢复）"


class AssetUpdateTool(Tool):
    """更新资产的描述/标签（语义重命名）。"""

    name = "asset_update"
    description = (
        "更新资产的描述或标签（相当于重命名，方便以后检索）。description 与 tags 至少提供一个。"
        "tags 逗号分隔；传空字符串表示清空标签。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "资产编号（asset_search 结果里的 #编号）"},
            "description": {"type": "string", "description": "新的描述（可选，须非空）"},
            "tags": {"type": "string", "description": "新标签，逗号分隔；传空字符串清空（可选）"},
        },
        "required": ["id"],
    }

    def __init__(self, store: AssetStore) -> None:
        self._store = store

    async def execute(
        self, id: Any = None, description: Any = None, tags: Any = None, **kwargs: Any
    ) -> str:
        """更新资产描述/标签。"""
        try:
            asset_id = int(id)
        except (TypeError, ValueError):
            return "错误：缺少有效的 id 参数（资产编号）"
        if description is None and tags is None:
            return "错误：description 与 tags 至少提供一个"

        new_desc: str | None = None
        if description is not None:
            new_desc = str(description).strip()
            if not new_desc:
                return "错误：描述不能为空（不修改描述请勿传该参数）"
        new_tags: list[str] | None = None
        if tags is not None:
            new_tags = [t.strip() for t in re.split(r"[,，]", str(tags)) if t.strip()]

        entry = self._store.update(asset_id, description=new_desc, tags=new_tags)
        if entry is None:
            return f"更新失败：没有编号为 #{asset_id} 的资产"
        tag_text = "、".join(entry["tags"]) if entry["tags"] else "无"
        return f"已更新 [资产 #{asset_id}]：{entry['description']}（标签：{tag_text}）"
