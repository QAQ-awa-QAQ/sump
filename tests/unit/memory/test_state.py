"""巩固状态游标测试"""

from sump.memory.state import ConsolidationState


class TestConsolidationState:
    def test_get_set(self, tmp_path):
        state = ConsolidationState(str(tmp_path / "state.db"))
        assert state.get("k", 0) == 0
        state.set("k", 42)
        assert state.get("k", 0) == 42
        state.set("k", 100)
        assert state.get("k", 0) == 100

    def test_default(self, tmp_path):
        state = ConsolidationState(str(tmp_path / "state.db"))
        assert state.get("missing", 7) == 7
