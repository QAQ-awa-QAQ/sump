"""深层记忆 embedding 检索测试"""

import time

import pytest

from sump.memory.deep import DeepMemory


class _FakeEmbedder:
    """模拟 embedding：把文本长度映射到固定向量，避免联网下载模型。"""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class TestDeepMemoryEmbedding:
    @pytest.mark.asyncio
    async def test_store_auto_embed(self, tmp_path):
        embedder = _FakeEmbedder()
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=embedder)
        await deep.store("k1", "用户喜欢 Python")
        assert embedder.calls == [["用户喜欢 Python"]]
        assert await deep.retrieve("k1") == "用户喜欢 Python"

    @pytest.mark.asyncio
    async def test_search_auto_embed_rank(self, tmp_path):
        embedder = _FakeEmbedder()
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=embedder)
        # k1 与 query 向量更接近（同方向）
        await deep.store("k1", "内容A", embedding=[1.0, 0.0, 0.0])
        await deep.store("k2", "内容BB", embedding=[0.0, 1.0, 0.0])

        results = await deep.search("查询")
        assert len(results) == 2
        assert results[0]["key"] == "k1"
        assert results[0]["score"] > results[1]["score"]

    @pytest.mark.asyncio
    async def test_search_embedder_failure_fallback(self, tmp_path):
        # embedder 抛异常时，回退为全表返回、分数为 0
        class _Broken:
            def embed(self, texts: list[str]) -> list[list[float]]:
                raise RuntimeError("boom")

        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_Broken())
        await deep.store("k1", "内容A", embedding=[1.0, 0.0, 0.0])
        results = await deep.search("查询")
        assert len(results) == 1
        assert results[0]["score"] == 0.0

    @pytest.mark.asyncio
    async def test_store_priority(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "内容A", priority=80, embedding=[1.0, 0.0, 0.0])
        results = await deep.search("查询", query_embedding=[1.0, 0.0, 0.0])
        assert results[0]["priority"] == 80

    @pytest.mark.asyncio
    async def test_hybrid_bm25(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "用户喜欢 Python 编程", embedding=[1.0, 0.0, 0.0])
        await deep.store("k2", "用户喜欢看电影", embedding=[1.0, 0.0, 0.0])
        results = await deep.search("Python", query_embedding=[1.0, 0.0, 0.0])
        assert results[0]["key"] == "k1"

    @pytest.mark.asyncio
    async def test_delete_expired(self, tmp_path):
        deep = DeepMemory(str(tmp_path / "deep.db"), embedder=_FakeEmbedder())
        await deep.store("k1", "旧1", priority=80, embedding=[1.0, 0.0, 0.0])
        await deep.store("k2", "旧2", priority=80, embedding=[1.0, 0.0, 0.0])
        await deep.store("k3", "新1", priority=80, embedding=[1.0, 0.0, 0.0])
        db = deep._conn()
        db.execute(
            "UPDATE deep_memory SET created_at = ? WHERE key IN ('k1', 'k2')",
            (time.time() - 400 * 86400,),
        )
        db.commit()
        db.close()
        assert await deep.delete_expired(365) == 2
