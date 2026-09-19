"""全局运行时设置测试（settings.json + Config 叠加 + 客户端热更新）"""

from sump.config import Config
from sump.settings import load_settings, mask_secret, save_settings


class TestMaskSecret:
    def test_empty(self):
        assert mask_secret("") == ""

    def test_short_value(self):
        assert mask_secret("sk-123") == "••••••••"

    def test_long_value(self):
        assert mask_secret("sk-1234567890abcdef") == "sk-123••••cdef"


class TestSettingsStore:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
        save_settings({"deepseek": {"model": "deepseek-v4-pro"}})
        assert load_settings()["deepseek"]["model"] == "deepseek-v4-pro"

    def test_whitelist_filters_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
        saved = save_settings(
            {"deepseek": {"model": "x", "evil": "y"}, "napcat": {"owner_id": "1"}}
        )
        assert "napcat" not in saved
        assert "evil" not in saved["deepseek"]

    def test_empty_api_key_keeps_existing(self, tmp_path, monkeypatch):
        """敏感字段空值视为不修改，避免前端未回填时清空。"""
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
        save_settings({"deepseek": {"api_key": "sk-real"}})
        save_settings({"deepseek": {"api_key": "", "model": "m2"}})
        saved = load_settings()["deepseek"]
        assert saved["api_key"] == "sk-real"
        assert saved["model"] == "m2"

    def test_corrupt_file_returns_empty(self, tmp_path, monkeypatch):
        path = tmp_path / "settings.json"
        path.write_text("{bad json", encoding="utf-8")
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(path))
        assert load_settings() == {}


class TestConfigOverlay:
    def test_settings_override_yaml(self, tmp_path, monkeypatch):
        """settings.json 优先级最高：覆盖 yaml 同名字段。"""
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
        save_settings({"deepseek": {"model": "deepseek-v4-pro", "flash_model": "m-flash"}})
        cfg = Config()
        assert cfg.get("deepseek.model") == "deepseek-v4-pro"
        assert cfg.get("deepseek.flash_model") == "m-flash"
        # 未覆盖的字段保持 yaml 值
        assert str(cfg.get("deepseek.vision_model")) == "deepseek-flash"


class TestClientApplySettings:
    def test_apply_updates_models_and_rebuilds_client(self, config):
        from sump.core.models.deepseek import DeepSeekClient

        client = DeepSeekClient(config)
        old_client = client._client
        client.apply_settings({
            "model": "m1", "vision_model": "m2", "flash_model": "m3",
            "api_key": "sk-new", "base_url": "https://example.com",
        })
        assert client._model == "m1"
        assert client._vision_model == "m2"
        assert client._flash_model == "m3"
        assert client._client is not old_client

    def test_apply_partial_keeps_current(self, config):
        from sump.core.models.deepseek import DeepSeekClient

        client = DeepSeekClient(config)
        client.apply_settings({"model": "only-model"})
        assert client._model == "only-model"
        assert str(client._vision_model) == "deepseek-flash"


class TestStaleSnapshotFreshness:
    """复现线上 401：Config 只是启动时快照，保存设置之后新建的客户端必须拿到最新值。"""

    def test_client_created_after_save_uses_new_key(self, config):
        """时间线：进程启动（快照无 Key）→ 用户在设置中心保存 → 新会话/新 QQ 群
        agent 才创建。新建的客户端必须拿到刚保存的 Key，而不是启动时的占位值。"""
        from sump.core.models.deepseek import DeepSeekClient

        # 此刻 config 快照已构造（模拟进程启动），settings.json 里还没有 api_key
        save_settings({"deepseek": {"api_key": "sk-fresh-key", "model": "m-fresh"}})
        # 保存之后才创建的客户端（QQ 首条消息 / 新前端会话的构造路径）
        client = DeepSeekClient(config)
        assert client._api_key == "sk-fresh-key"
        assert client._model == "m-fresh"
