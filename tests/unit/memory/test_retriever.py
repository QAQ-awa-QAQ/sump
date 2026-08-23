"""记忆召回测试"""

import pytest

from sump.memory.deep import DeepMemory
from sump.memory.retriever import MemoryRetriever
from sump.memory.shallow import ShallowMemory


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class TestMemoryRetriever:
    @pytest.mark.asyncio
    async def test_recall_empty(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        shallow = ShallowMemory(str(tmp_path / "shallow.db"), embedder=_FakeEmbedder())
        retriever = MemoryRetriever(deep, shallow)
        assert await retriever.recall("查询") == ""

    @pytest.mark.asyncio
    async def test_recall_returns_memories(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        shallow = ShallowMemory(str(tmp_path / "shallow.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "用户喜欢 Python", priority=80, embedding=[1.0, 0.0, 0.0])
        shallow.add_entry("语义", "浅层内容", priority=70)
        retriever = MemoryRetriever(deep, shallow)

        result = await retriever.recall("Python")
        assert "<core-memories>" in result      # 深层强制注入
        assert "用户喜欢 Python" in result
        assert "<relevant-memories>" in result  # 浅层按需召回
        assert "浅层内容" in result

    @pytest.mark.asyncio
    async def test_recall_char_budget(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        shallow = ShallowMemory(str(tmp_path / "shallow.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "很长的内容" * 100, priority=80, embedding=[1.0, 0.0, 0.0])
        retriever = MemoryRetriever(deep, shallow, max_chars=10)

        result = await retriever.recall("内容")
        # 单条超字符预算，不注入
        assert result == ""
