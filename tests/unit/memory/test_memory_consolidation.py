"""记忆整理编排测试（会话 → 浅层 → 深层 → 归档 → 清除）"""

import pytest

from sump.memory.archive import ArchiveMemory
from sump.memory.deep import DeepMemory
from sump.memory.session_memory import SessionMemory
from sump.memory.shallow import ShallowMemory
from sump.tools.builtin.memory_consolidation import MemoryConsolidationTool


class _SeqLLM:
    """按调用顺序返回预设 JSON 的 flash 模型。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.idx = 0

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        resp = self.responses[min(self.idx, len(self.responses) - 1)]
        self.idx += 1
        return resp


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class TestMemoryConsolidation:
    @pytest.mark.asyncio
    async def test_consolidate_full_flow(self, config, tmp_path):
        # 隔离 archive 路径（其余 memory.* 已由 conftest 隔离到 tmp_path）
        config._data["memory"]["archive"] = {"db_path": str(tmp_path / "archive.db")}

        session_path = config.get("memory.session.db_path")
        shallow_path = config.get("memory.shallow.db_path")
        deep_path = config.get("memory.deep.db_path")
        archive_path = config.get("memory.archive.db_path")

        # 造一个会话
        session_mem = SessionMemory(session_path)
        session_mem.save_message("s1", "user", "我喜欢 Python")
        session_mem.save_message("s1", "assistant", "好的，Python 很好用")
        session_mem.upsert_session_name("s1", "测试会话")

        llm = _SeqLLM([
            '{"important": true, "affects_next": false, "beneficial": false, '
            '"memories": [{"category": "语义", "content": "用户喜欢 Python", "priority": 80}]}',
            '{"items": [{"id": 1, "important": true, '
            '"affects_future": true, "beneficial_agent": true, "priority": 85}]}',
        ])
        tool = MemoryConsolidationTool(config, llm, deep_embedder=_FakeEmbedder())

        result = await tool.execute()
        assert "归档 1 个会话" in result
        assert "升级 1 条" in result

        # 会话消息已清除（智能体不可见）
        assert session_mem.list_sessions() == []
        # 归档保留副本
        archive = ArchiveMemory(archive_path)
        assert archive.list_sessions()[0]["name"] == "测试会话"
        # 浅层已腾空（升级后被删除）
        shallow = ShallowMemory(shallow_path)
        assert shallow.list_all_entries() == []
        # 深层已存入
        deep = DeepMemory(deep_path, embedder=_FakeEmbedder())
        assert await deep.retrieve("shallow:1") == "用户喜欢 Python"
