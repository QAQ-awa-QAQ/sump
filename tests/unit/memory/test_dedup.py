"""深层记忆冲突检测测试"""

import pytest

from sump.memory.dedup import DeepDedup
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
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class TestDeepDedup:
    @pytest.mark.asyncio
    async def test_decide_store(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "已有内容", priority=80, embedding=[1.0, 0.0, 0.0])
        llm = _FakeLLM(
            '{"decisions": [{"id": "1", "action": "store", "target_keys": [], "merged_content": null}]}'
        )
        dedup = DeepDedup(llm, deep)
        decisions = await dedup.decide(
            [{"id": 1, "content": "新内容", "category": "语义", "priority": 80}]
        )
        assert decisions[0]["action"] == "store"

    @pytest.mark.asyncio
    async def test_decide_skip(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        llm = _FakeLLM(
            '{"decisions": [{"id": "1", "action": "skip", "target_keys": [], "merged_content": null}]}'
        )
        dedup = DeepDedup(llm, deep)
        decisions = await dedup.decide(
            [{"id": 1, "content": "重复内容", "category": "语义", "priority": 80}]
        )
        assert decisions[0]["action"] == "skip"

    @pytest.mark.asyncio
    async def test_decide_fallback_store_on_bad_json(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        llm = _FakeLLM("not json")
        dedup = DeepDedup(llm, deep)
        decisions = await dedup.decide(
            [{"id": 1, "content": "内容", "category": "语义", "priority": 80}]
        )
        assert decisions[0]["action"] == "store"
