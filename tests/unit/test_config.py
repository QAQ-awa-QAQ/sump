"""配置加载器测试：YAML 叠加 + 多环境 + 运行时设置优先级"""

from sump.config import Config
from sump.settings import save_settings


class TestMultiEnvOverlay:
    def test_single_env(self, tmp_path):
        (tmp_path / "default.yaml").write_text("a:\n  x: 1\n  y: 2\n", encoding="utf-8")
        (tmp_path / "env1.yaml").write_text("a:\n  y: 20\n", encoding="utf-8")
        cfg = Config(config_dir=tmp_path, env="env1")
        assert cfg.get("a.x") == 1
        assert cfg.get("a.y") == 20

    def test_comma_separated_envs_later_wins(self, tmp_path):
        """多环境叠加：按顺序加载，后者覆盖前者。"""
        (tmp_path / "default.yaml").write_text("a:\n  x: 1\n  y: 2\n", encoding="utf-8")
        (tmp_path / "env1.yaml").write_text("a:\n  y: 20\n  z: 3\n", encoding="utf-8")
        (tmp_path / "env2.yaml").write_text("a:\n  x: 100\n", encoding="utf-8")
        cfg = Config(config_dir=tmp_path, env="env1,env2")
        assert cfg.get("a.x") == 100  # env2 覆盖 default
        assert cfg.get("a.y") == 20   # env1 生效
        assert cfg.get("a.z") == 3

    def test_env_names_with_spaces_and_blanks(self, tmp_path):
        (tmp_path / "default.yaml").write_text("a:\n  x: 1\n", encoding="utf-8")
        (tmp_path / "env1.yaml").write_text("a:\n  x: 7\n", encoding="utf-8")
        cfg = Config(config_dir=tmp_path, env=" env1 , ")
        assert cfg.get("a.x") == 7

    def test_missing_env_file_ignored(self, tmp_path):
        (tmp_path / "default.yaml").write_text("a:\n  x: 1\n", encoding="utf-8")
        cfg = Config(config_dir=tmp_path, env="nope")
        assert cfg.get("a.x") == 1

    def test_settings_json_has_highest_priority(self, tmp_path, monkeypatch):
        """settings.json 叠加优先级高于所有 yaml 层。"""
        monkeypatch.setenv("SUMP_SETTINGS_FILE", str(tmp_path / "settings.json"))
        (tmp_path / "default.yaml").write_text("deepseek:\n  model: m-default\n", encoding="utf-8")
        (tmp_path / "env1.yaml").write_text("deepseek:\n  model: m-env\n", encoding="utf-8")
        save_settings({"deepseek.model": "m-settings"})
        cfg = Config(config_dir=tmp_path, env="env1")
        assert cfg.get("deepseek.model") == "m-settings"
