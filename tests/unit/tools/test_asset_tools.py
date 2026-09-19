"""资产工具测试：asset_save / asset_search / asset_delete / asset_update"""

import pytest

from sump.assets import AssetStore
from sump.tools.builtin.asset_tools import (
    AssetDeleteTool,
    AssetSaveTool,
    AssetSearchTool,
    AssetUpdateTool,
)

# 8 字节 PNG 文件头（base64），够用于嗅探扩展名
PNG_B64 = "iVBORw0KGgo="
PNG_DATA_URL = f"data:image/png;base64,{PNG_B64}"


def _store(tmp_path) -> AssetStore:
    return AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))


class TestAssetSaveTool:
    @pytest.mark.asyncio
    async def test_description_required(self, tmp_path, ctx):
        tool = AssetSaveTool(_store(tmp_path), ctx)
        result = await tool.execute(source=PNG_DATA_URL)
        assert "必须" in result
        assert list((tmp_path / "assets").iterdir()) == []

    @pytest.mark.asyncio
    async def test_save_from_message(self, tmp_path, ctx):
        """msg:N 从最近第 N 条用户消息取图。"""
        ctx.add_user_message("看这个", images=[PNG_DATA_URL])
        tool = AssetSaveTool(_store(tmp_path), ctx)
        result = await tool.execute(source="msg:1", description="猫猫表情包", tags="猫,表情")
        assert "已保存" in result
        assert "猫猫表情包" in result
        assert len(list((tmp_path / "assets").iterdir())) == 1

    @pytest.mark.asyncio
    async def test_msg_without_image(self, tmp_path, ctx):
        ctx.add_user_message("纯文本消息")
        tool = AssetSaveTool(_store(tmp_path), ctx)
        result = await tool.execute(source="msg:1", description="x")
        assert "没有图片" in result

    @pytest.mark.asyncio
    async def test_msg_out_of_range(self, tmp_path, ctx):
        tool = AssetSaveTool(_store(tmp_path), ctx)
        result = await tool.execute(source="msg:5", description="x")
        assert "没有第 5 条用户消息" in result

    @pytest.mark.asyncio
    async def test_save_local_file(self, tmp_path, ctx):
        pic = tmp_path / "pic.png"
        pic.write_bytes(PNG_DATA_URL.encode())  # 内容任意，按路径后缀取扩展名
        tool = AssetSaveTool(_store(tmp_path), ctx)
        result = await tool.execute(source=str(pic), description="本地图片")
        assert "已保存" in result
        assert "路径：" in result

    @pytest.mark.asyncio
    async def test_unknown_source(self, tmp_path, ctx):
        tool = AssetSaveTool(_store(tmp_path), ctx)
        result = await tool.execute(source="ftp://weird", description="x")
        assert "无法识别" in result

    @pytest.mark.asyncio
    async def test_dedup_message(self, tmp_path, ctx):
        ctx.add_user_message("图", images=[PNG_DATA_URL])
        tool = AssetSaveTool(_store(tmp_path), ctx)
        first = await tool.execute(source="msg:1", description="第一次")
        again = await tool.execute(source="msg:1", description="第二次")
        assert "已保存" in first
        assert "已存在" in again


class TestAssetSearchTool:
    @pytest.mark.asyncio
    async def test_search_output(self, tmp_path):
        store = _store(tmp_path)
        store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16, description="微笑表情", tags=["搞笑"])
        tool = AssetSearchTool(store)
        out = await tool.execute(query="微笑")
        assert "微笑表情" in out
        assert "路径" in out

    @pytest.mark.asyncio
    async def test_empty_library(self, tmp_path):
        tool = AssetSearchTool(_store(tmp_path))
        out = await tool.execute(query="猫")
        assert "没有匹配" in out

    @pytest.mark.asyncio
    async def test_list_recent_without_query(self, tmp_path):
        store = _store(tmp_path)
        store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"a", description="甲")
        store.save_bytes(b"\xff\xd8\xff" + b"b", description="乙")
        out = await AssetSearchTool(store).execute()
        assert "乙" in out and "甲" in out


class TestAssetDeleteTool:
    @pytest.mark.asyncio
    async def test_delete_success(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"x", description="可爱猫猫")
        out = await AssetDeleteTool(store).execute(id=entry["id"])
        assert "已删除" in out
        assert "可爱猫猫" in out
        assert store.get(entry["id"]) is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, tmp_path):
        out = await AssetDeleteTool(_store(tmp_path)).execute(id=42)
        assert "没有编号为 #42" in out

    @pytest.mark.asyncio
    async def test_delete_bad_id(self, tmp_path):
        out = await AssetDeleteTool(_store(tmp_path)).execute(id="abc")
        assert "错误" in out


class TestAssetUpdateTool:
    @pytest.mark.asyncio
    async def test_update_description(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"x", description="旧名")
        out = await AssetUpdateTool(store).execute(id=entry["id"], description="新名")
        assert "已更新" in out
        got = store.get(entry["id"])
        assert got is not None and got["description"] == "新名"

    @pytest.mark.asyncio
    async def test_update_clear_tags(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"x", description="x", tags=["旧"])
        out = await AssetUpdateTool(store).execute(id=entry["id"], tags="")
        assert "已更新" in out
        got = store.get(entry["id"])
        assert got is not None and got["tags"] == []

    @pytest.mark.asyncio
    async def test_requires_some_field(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"x", description="x")
        out = await AssetUpdateTool(store).execute(id=entry["id"])
        assert "至少提供一个" in out

    @pytest.mark.asyncio
    async def test_empty_description_rejected(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(b"\x89PNG\r\n\x1a\n" + b"x", description="x")
        out = await AssetUpdateTool(store).execute(id=entry["id"], description="  ")
        assert "不能为空" in out

    @pytest.mark.asyncio
    async def test_update_missing(self, tmp_path):
        out = await AssetUpdateTool(_store(tmp_path)).execute(id=7, description="x")
        assert "没有编号为 #7" in out
