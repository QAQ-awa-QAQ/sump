"""人格/灵魂管理器测试"""

import pytest

from sump.memory.persona import PersonaManager


class _FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.calls = 0

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        self.calls += 1
        return self.raw


class TestPersonaManager:
    def test_empty_prompt_when_no_files(self, tmp_path):
        pm = PersonaManager(base_dir=str(tmp_path))
        assert pm.get_system_prompt() == ""

    def test_join_and_truncate(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("灵魂内容", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("agent 内容", encoding="utf-8")
        pm = PersonaManager(base_dir=str(tmp_path), max_bytes=20)
        prompt = pm.get_system_prompt()
        assert "灵魂内容" in prompt
        assert len(prompt.encode("utf-8")) <= 20

    @pytest.mark.asyncio
    async def test_compact_shrinks_and_backs_up(self, tmp_path):
        f = tmp_path / "SOUL.md"
        original = "这是一段很长的内容。" * 50
        f.write_text(original, encoding="utf-8")
        llm = _FakeLLM("精简后的短内容")
        pm = PersonaManager(base_dir=str(tmp_path), max_bytes=50)

        report = await pm.compact(llm)
        assert "→" in report
        assert (tmp_path / "SOUL.md.bak").exists()
        assert len(f.read_text(encoding="utf-8")) < len(original)

    @pytest.mark.asyncio
    async def test_compact_rejects_longer(self, tmp_path):
        f = tmp_path / "SOUL.md"
        original = "短" * 100
        f.write_text(original, encoding="utf-8")
        llm = _FakeLLM("更长的内容" * 100)
        pm = PersonaManager(base_dir=str(tmp_path), max_bytes=10)

        report = await pm.compact(llm)
        assert "弃用" in report
        assert f.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_compact_skips_within_limit(self, tmp_path):
        f = tmp_path / "SOUL.md"
        f.write_text("短内容", encoding="utf-8")
        llm = _FakeLLM("不应被调用")
        pm = PersonaManager(base_dir=str(tmp_path), max_bytes=100)

        report = await pm.compact(llm)
        assert report == "无需精简"
        assert llm.calls == 0
