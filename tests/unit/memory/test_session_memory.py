"""会话记忆测试"""

import pytest

from sump.memory.session_memory import SessionMemory


class TestSessionMemory:
    @pytest.mark.asyncio
    async def test_init(self, tmp_path):
        mem = SessionMemory(str(tmp_path / "session.db"))
        assert mem is not None
