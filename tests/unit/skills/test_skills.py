"""技能系统测试：自动创建 + 持久化 + 发现加载"""

import json

import pytest

from sump.skills.creator import SkillCreator
from sump.skills.manager import SkillManager
from sump.types import SkillProficiency


class _FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def chat_flash(
        self, text: str, *, max_tokens: int = 256, temperature: float = 0.3
    ) -> str:
        return self.raw


class TestSkillCreator:
    @pytest.mark.asyncio
    async def test_create_from_task(self, tmp_path):
        mgr = SkillManager()
        llm = _FakeLLM(
            '{"name": "部署Flask", "description": "部署Flask应用到服务器", '
            '"steps": ["创建虚拟环境", "pip install flask", "启动 gunicorn"]}'
        )
        creator = SkillCreator(mgr, llm=llm, skills_dir=str(tmp_path / "skills"))

        skill = await creator.create_from_task("部署 flask", "成功部署")

        assert skill is not None
        assert mgr.get("部署Flask") is skill
        path = tmp_path / "skills" / "initial" / "部署Flask.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["name"] == "部署Flask"
        assert len(data["steps"]) == 3

    @pytest.mark.asyncio
    async def test_create_skips_empty(self, tmp_path):
        mgr = SkillManager()
        llm = _FakeLLM('{"name": "", "description": "", "steps": []}')
        creator = SkillCreator(mgr, llm=llm, skills_dir=str(tmp_path / "skills"))
        assert await creator.create_from_task("x", "y") is None
        assert mgr.list_all() == []

    @pytest.mark.asyncio
    async def test_auto_create_disabled(self, tmp_path):
        mgr = SkillManager()
        creator = SkillCreator(
            mgr,
            llm=_FakeLLM("{}"),
            skills_dir=str(tmp_path / "skills"),
            auto_create=False,
        )
        assert await creator.create_from_task("x", "y") is None
        assert mgr.list_all() == []


class TestSkillManagerDiscover:
    def test_discover_loads_all(self, tmp_path):
        (tmp_path / "high").mkdir()
        (tmp_path / "high" / "a.json").write_text(
            json.dumps({"name": "A", "description": "d", "steps": ["s1"]}),
            encoding="utf-8",
        )
        (tmp_path / "low").mkdir()
        (tmp_path / "low" / "b.json").write_text(
            json.dumps(
                {"name": "B", "description": "d2", "steps": [], "proficiency": "low"}
            ),
            encoding="utf-8",
        )

        mgr = SkillManager()
        names = mgr.discover(str(tmp_path))
        assert set(names) == {"A", "B"}
        assert mgr.get("B").proficiency == SkillProficiency.LOW

    def test_discover_missing_dir(self, tmp_path):
        mgr = SkillManager()
        assert mgr.discover(str(tmp_path / "nope")) == []
