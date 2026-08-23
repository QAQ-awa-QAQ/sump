"""深层记忆矛盾检测测试"""

import pytest

from sump.memory.conflict import ConflictResolver
from sump.memory.deep import DeepMemory


class _FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        return self.raw


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class TestConflictResolver:
    @pytest.mark.asyncio
    async def test_resolve_conflict(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "用户喜欢 Python", priority=80, embedding=[1.0, 0.0, 0.0])
        await deep.store("k2", "用户讨厌 Python", priority=80, embedding=[1.0, 0.0, 0.0])
        llm = _FakeLLM('{"conflicts": [{"keep": "k2", "drop": "k1"}]}')
        resolver = ConflictResolver(llm, deep)

        result = await resolver.resolve()
        assert "解决 1 对" in result
        assert await deep.retrieve("k1") is None
        assert await deep.retrieve("k2") == "用户讨厌 Python"

    @pytest.mark.asyncio
    async def test_no_conflict(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "内容A", priority=80, embedding=[1.0, 0.0, 0.0])
        llm = _FakeLLM('{"conflicts": []}')
        resolver = ConflictResolver(llm, deep)

        result = await resolver.resolve()
        assert "解决 0 对" in result
        assert await deep.retrieve("k1") == "内容A"
