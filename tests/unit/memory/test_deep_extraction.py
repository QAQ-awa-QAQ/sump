"""深层记忆提取工具测试"""

import pytest

from sump.memory.deep import DeepMemory
from sump.memory.shallow import ShallowMemory
from sump.tools.builtin.deep_extraction import DeepExtractionTool


class _FakeLLM:
    """模拟 flash 模型，返回预设 JSON 字符串。"""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.last_prompt = ""
        self.call_count = 0

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        self.last_prompt = text
        self.call_count += 1
        return self.raw


class _FakeEmbedder:
    """模拟 embedding，避免测试联网下载模型。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class TestDeepExtractionTool:
    @pytest.mark.asyncio
    async def test_upgrade_hit(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        eid = shallow.add_entry("语义", "用户在做 SUMP 项目")
        llm = _FakeLLM(
            '{"items": [{"id": %d, "important": true, '
            '"affects_future": true, "beneficial_agent": true, "priority": 85}]}' % eid
        )
        tool = DeepExtractionTool(llm, shallow, deep)

        result = await tool.execute()
        assert "升级 1 条" in result
        # 浅层已删除
        assert shallow.list_all_entries() == []
        # 深层已存储
        stored = await deep.retrieve(f"shallow:{eid}")
        assert stored == "用户在做 SUMP 项目"

    @pytest.mark.asyncio
    async def test_no_upgrade(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        shallow.add_entry("语义", "今天天气不错")
        llm = _FakeLLM('{"items": []}')
        tool = DeepExtractionTool(llm, shallow, deep)

        result = await tool.execute()
        assert result == "无需升级"
        assert len(shallow.list_all_entries()) == 1

    @pytest.mark.asyncio
    async def test_not_all_three(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        eid = shallow.add_entry("语义", "内容X")
        # important 满足但 affects_future 不满足 → 不升级
        llm = _FakeLLM(
            '{"items": [{"id": %d, "important": true, '
            '"affects_future": false, "beneficial_agent": true}]}' % eid
        )
        tool = DeepExtractionTool(llm, shallow, deep)

        result = await tool.execute()
        assert result == "无需升级"
        assert len(shallow.list_all_entries()) == 1
