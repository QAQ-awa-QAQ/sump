"""会话记忆测试"""

import pytest

from sump.memory.session_memory import SessionMemory


class TestSessionMemory:
    @pytest.mark.asyncio
    async def test_init(self, tmp_path):
        mem = SessionMemory(str(tmp_path / "session.db"))
        assert mem is not None

    def test_save_and_load_all(self, tmp_path):
        mem = SessionMemory(str(tmp_path / "session.db"))
        mem.save_message("s1", "user", "第一条")
        mem.save_message("s1", "assistant", "第二条")
        mem.save_message("s1", "tool", "第三条", tool_call_id="t1")

        all_msgs = mem.load_all_messages("s1")
        assert [m["content"] for m in all_msgs] == ["第一条", "第二条", "第三条"]
        assert all_msgs[2]["tool_call_id"] == "t1"

    def test_load_recent(self, tmp_path):
        mem = SessionMemory(str(tmp_path / "session.db"))
        for i in range(3):
            mem.save_message("s1", "user", f"消息{i}")

        recent = mem.load_messages("s1", limit=2)
        assert [m["content"] for m in recent] == ["消息1", "消息2"]
