"""记忆生命周期集成测试"""

import pytest

from sump.memory.session_memory import SessionMemory
from sump.memory.compressor import MemoryCompressor


class TestMemoryLifecycle:
    @pytest.mark.asyncio
    async def test_compress_empty(self, tmp_path):
        session_memory = SessionMemory(str(tmp_path / "session.db"))
        compressor = MemoryCompressor(session_memory)
        deleted = await compressor.compress()
        assert deleted == 0  # 空会话无消息可删

    @pytest.mark.asyncio
    async def test_compress_trims_half(self, tmp_path):
        session_memory = SessionMemory(str(tmp_path / "session.db"))
        for i in range(10):
            session_memory.save_message("s1", "user", f"msg{i}")
        compressor = MemoryCompressor(session_memory, max_messages=5)
        deleted = await compressor.compress("s1")
        assert deleted == 5
        assert session_memory.count_messages("s1") == 5
