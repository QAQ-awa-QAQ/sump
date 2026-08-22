"""工作记忆测试"""

from sump.memory.working import WorkingMemory


class TestWorkingMemory:
    def test_memory_backend_goal_notes(self):
        wm = WorkingMemory(backend="memory")
        wm.set_goal("修复登录 bug")
        wm.add_note("定位到 token 过期")
        assert wm.get_goal() == "修复登录 bug"
        assert wm.get_notes() == ["定位到 token 过期"]

    def test_memory_backend_clear(self):
        wm = WorkingMemory(backend="memory")
        wm.set_goal("目标")
        wm.add_note("记录")
        wm.clear()
        assert wm.get_goal() == ""
        assert wm.get_notes() == []

    def test_memory_backend_byte_limit(self):
        wm = WorkingMemory(backend="memory", max_bytes=30)
        wm.set_goal("目标")
        wm.add_note("第一条过程记录")
        wm.add_note("第二条过程记录")
        # 超字节上限后，最旧的过程记录被丢弃
        assert "第一条过程记录" not in wm.get_notes()
        assert "第二条过程记录" in wm.get_notes()

    def test_disk_backend_persistence(self, tmp_path):
        db = str(tmp_path / "working.db")
        wm = WorkingMemory(backend="disk", db_path=db)
        wm.set_goal("目标")
        wm.add_note("记录")

        # 重新实例化验证 SQLite 持久化
        wm2 = WorkingMemory(backend="disk", db_path=db)
        assert wm2.get_goal() == "目标"
        assert wm2.get_notes() == ["记录"]
