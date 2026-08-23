"""浅层记忆提取工具测试"""

import pytest

from sump.memory.shallow import ShallowMemory
from sump.tools.builtin.shallow_extraction import ShallowExtractionTool


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


class TestShallowExtractionTool:
    @pytest.mark.asyncio
    async def test_extract_hit(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM(
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "用户喜欢 Python", "priority": 80}]}'
        )
        tool = ShallowExtractionTool(llm, shallow)
        result = await tool.execute(
            session_id="s1",
            messages=[{"role": "user", "content": "我喜欢 Python"}],
        )
        assert "提取 1 条" in result
        entries = shallow.list_entries()
        assert entries[0]["content"] == "用户喜欢 Python"
        assert entries[0]["metadata"]["session_id"] == "s1"
        assert entries[0]["metadata"]["important"] is True

    @pytest.mark.asyncio
    async def test_no_extract(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM(
            '{"important": false, "affects_next": false, "beneficial": false, "memories": []}'
        )
        tool = ShallowExtractionTool(llm, shallow)
        result = await tool.execute(
            session_id="s1", messages=[{"role": "user", "content": "你好"}]
        )
        assert result == "无需提炼"
        assert shallow.list_entries() == []

    @pytest.mark.asyncio
    async def test_bad_json(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM("not json")
        tool = ShallowExtractionTool(llm, shallow)
        result = await tool.execute(
            session_id="s1", messages=[{"role": "user", "content": "x"}]
        )
        assert "提炼失败" in result
        assert shallow.list_entries() == []

    @pytest.mark.asyncio
    async def test_priority_filter(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM(
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "低价值", "priority": 30}, '
            '{"category": "语义", "content": "高价值", "priority": 90}]}'
        )
        tool = ShallowExtractionTool(llm, shallow)  # 默认阈值 60
        result = await tool.execute(
            session_id="s1", messages=[{"role": "user", "content": "x"}]
        )
        assert "提取 1 条" in result
        entries = shallow.list_all_entries()
        assert len(entries) == 1
        assert entries[0]["content"] == "高价值"

    @pytest.mark.asyncio
    async def test_split_long_session(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM(
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "x", "priority": 80}]}'
        )
        tool = ShallowExtractionTool(llm, shallow, max_chars_per_batch=20)
        messages = []
        for i in range(5):
            messages.append({"role": "user", "content": f"第{i}轮问题" * 5})
            messages.append({"role": "assistant", "content": f"第{i}轮回答" * 5})

        result = await tool.execute(session_id="s1", messages=messages)
        assert "5 批" in result
        assert llm.call_count == 5
        assert len(shallow.list_entries()) == 5


class TestOwnerMarkerFilter:
    @pytest.mark.asyncio
    async def test_only_owner_extracted(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM(
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "用户喜欢 Python", "priority": 80}]}'
        )
        tool = ShallowExtractionTool(llm, shallow, owner_marker="·主人")
        result = await tool.execute(
            session_id="s1",
            messages=[
                {"role": "user", "content": "[小明] 你喜欢什么语言"},
                {"role": "user", "content": "[小明·主人] 我喜欢 Python"},
            ],
        )
        assert "提取 1 条" in result
        entries = shallow.list_entries()
        assert len(entries) == 1
        assert entries[0]["content"] == "用户喜欢 Python"

    @pytest.mark.asyncio
    async def test_no_owner_message(self, tmp_path):
        shallow = ShallowMemory(str(tmp_path / "shallow.db"))
        llm = _FakeLLM(
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "x", "priority": 80}]}'
        )
        tool = ShallowExtractionTool(llm, shallow, owner_marker="·主人")
        result = await tool.execute(
            session_id="s1", messages=[{"role": "user", "content": "[小明] 你好"}]
        )
        assert "无主人消息可提炼" in result
        assert shallow.list_entries() == []
