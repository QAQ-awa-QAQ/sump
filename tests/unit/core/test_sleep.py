"""睡眠管理器设置热更新测试。"""

from sump.core.sleep import SleepManager


class TestSleepSettingsHotUpdate:
    def test_apply_settings_updates_consolidation_client(self, config):
        """设置中心保存后，睡眠巩固工具的 LLM 客户端必须热更新，
        否则夜间记忆巩固仍用启动时的旧 Key（恒 401）。"""
        sm = SleepManager(config)
        sm.apply_settings({"api_key": "sk-sleep-fresh"})
        assert sm._tool._llm._backend._api_key == "sk-sleep-fresh"
