"""场景记忆测试"""

import pytest

from sump.memory.scene import SceneMemory
from sump.memory.shallow import ShallowMemory
from sump.tools.builtin.scene_aggregation import SceneAggregationTool


class _FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        return self.raw


class TestSceneMemory:
    def test_upsert_and_list(self, tmp_path):
        scene = SceneMemory(str(tmp_path / "scene.db"))
        scene.upsert_scene("项目开发", "用户在做 SUMP", priority=80)
        scenes = scene.list_scenes()
        assert scenes[0]["name"] == "项目开发"
        assert scenes[0]["summary"] == "用户在做 SUMP"

    def test_upsert_overwrites(self, tmp_path):
        scene = SceneMemory(str(tmp_path / "scene.db"))
        scene.upsert_scene("项目", "旧总结", priority=60)
        scene.upsert_scene("项目", "新总结", priority=90)
        scenes = scene.list_scenes()
        assert len(scenes) == 1
        assert scenes[0]["summary"] == "新总结"


class TestSceneAggregationTool:
    @pytest.mark.asyncio
    async def test_aggregate(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        shallow.add_entry("语义", "用户喜欢 Python", priority=80)
        scene = SceneMemory(str(tmp_path / "scene.db"))
        llm = _FakeLLM(
            '{"scenes": [{"name": "项目", "summary": "用户在做 SUMP", "priority": 80}]}'
        )
        tool = SceneAggregationTool(llm, shallow, scene)

        result = await tool.execute()
        assert "聚合 1 个场景" in result
        assert scene.list_scenes()[0]["name"] == "项目"
