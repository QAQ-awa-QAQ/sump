"""本地 embedding 封装测试"""

from sump.memory.embedder import Embedder


class TestEmbedder:
    def test_embed_empty(self):
        embedder = Embedder()
        assert embedder.embed([]) == []
