"""资产库（AssetStore）测试：保存 / 去重 / 检索 / 对账扫描"""

from sump.assets import AssetStore, guess_asset_ext

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff" + b"\x00" * 32


def _store(tmp_path) -> AssetStore:
    return AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))


class TestGuessAssetExt:
    def test_known_formats(self):
        assert guess_asset_ext(PNG) == ".png"
        assert guess_asset_ext(JPG) == ".jpg"
        assert guess_asset_ext(b"GIF89a") == ".gif"
        assert guess_asset_ext(b"RIFF\x00\x00\x00\x00WEBP") == ".webp"

    def test_fallback(self):
        assert guess_asset_ext(b"garbage") == ".bin"
        assert guess_asset_ext(b"garbage", fallback=".dat") == ".dat"


class TestAssetStore:
    def test_save_and_get(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(PNG, description="一只猫表情", tags=["猫", "表情包"])
        assert entry["duplicated"] is False
        assert entry["filename"].endswith(".png")
        assert entry["kind"] == "image"
        assert (tmp_path / "assets" / entry["filename"]).is_file()

        got = store.get(entry["id"])
        assert got is not None
        assert got["description"] == "一只猫表情"
        assert got["tags"] == ["猫", "表情包"]
        assert got["path"].endswith(entry["filename"])

    def test_dedup_same_content(self, tmp_path):
        store = _store(tmp_path)
        first = store.save_bytes(PNG, description="a")
        again = store.save_bytes(PNG, description="b")
        assert again["duplicated"] is True
        assert again["id"] == first["id"]
        # 只落盘一个文件
        assert len(list((tmp_path / "assets").iterdir())) == 1

    def test_search_hits_description_and_tags(self, tmp_path):
        store = _store(tmp_path)
        store.save_bytes(PNG, description="可爱的猫咪表情", tags=["猫", "搞笑"])
        store.save_bytes(JPG, description="工作汇报截图", tags=["工作"])
        hits = store.search("猫咪")
        assert len(hits) == 1
        assert "猫咪" in hits[0]["description"]
        assert len(store.search("工作")) == 1

    def test_search_empty_lists_recent(self, tmp_path):
        store = _store(tmp_path)
        store.save_bytes(PNG, description="第一条")
        store.save_bytes(JPG, description="第二条")
        recent = store.search("")
        assert [e["description"] for e in recent] == ["第二条", "第一条"]

    def test_search_miss(self, tmp_path):
        store = _store(tmp_path)
        store.save_bytes(PNG, description="猫咪")
        assert store.search("完全不存在的关键词xyz") == []

    def test_scan_indexes_manual_files(self, tmp_path):
        """对账扫描：手工放入的文件自动入库（描述为空）；删除后条目清理。"""
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir()
        (asset_dir / "manual.png").write_bytes(PNG)

        store = AssetStore(str(asset_dir), str(tmp_path / "assets.db"))
        entries = store.search("manual")
        assert len(entries) == 1
        assert entries[0]["description"] == ""

        (asset_dir / "manual.png").unlink()
        store2 = AssetStore(str(asset_dir), str(tmp_path / "assets.db"))
        assert store2.search("") == []

    def test_scan_keeps_saved_entries(self, tmp_path):
        """已有条目在重新扫描后保持描述与索引。"""
        store = _store(tmp_path)
        entry = store.save_bytes(PNG, description="保留我")
        store2 = AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))
        got = store2.get(entry["id"])
        assert got is not None
        assert got["description"] == "保留我"

    def test_delete_moves_file_to_trash(self, tmp_path):
        """删除 = 软删除：文件移入 .trash，索引清除。"""
        store = _store(tmp_path)
        entry = store.save_bytes(PNG, description="待删")
        removed = store.delete(entry["id"])
        assert removed is not None
        assert removed["description"] == "待删"
        # 索引已清除
        assert store.get(entry["id"]) is None
        assert store.search("") == []
        # 文件在 .trash 里（可恢复），不在资产目录顶层
        trash_files = list((tmp_path / "assets" / ".trash").iterdir())
        assert len(trash_files) == 1
        assert not list((tmp_path / "assets").glob("*.png"))

    def test_delete_missing_id(self, tmp_path):
        store = _store(tmp_path)
        assert store.delete(999) is None

    def test_delete_then_scan_keeps_trash_ignored(self, tmp_path):
        """对账扫描不应把 .trash 当资产或恢复条目。"""
        store = _store(tmp_path)
        entry = store.save_bytes(PNG, description="x")
        store.delete(entry["id"])
        store2 = AssetStore(str(tmp_path / "assets"), str(tmp_path / "assets.db"))
        assert store2.search("") == []

    def test_update_description_and_tags(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(PNG, description="旧描述", tags=["旧标签"])
        updated = store.update(entry["id"], description="新描述", tags=["新标签"])
        assert updated is not None
        assert updated["description"] == "新描述"
        assert updated["tags"] == ["新标签"]
        # FTS 同步：搜新词命中、旧词不命中
        assert len(store.search("新描述")) == 1
        assert store.search("旧描述") == []

    def test_update_partial_keeps_other_field(self, tmp_path):
        store = _store(tmp_path)
        entry = store.save_bytes(PNG, description="原描述", tags=["原标签"])
        updated = store.update(entry["id"], tags=["仅改标签"])
        assert updated is not None
        assert updated["description"] == "原描述"
        assert updated["tags"] == ["仅改标签"]

    def test_update_missing_id(self, tmp_path):
        store = _store(tmp_path)
        assert store.update(999, description="x") is None
