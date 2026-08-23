"""技能管理器（注册/发现/加载）"""

import json
from pathlib import Path

from sump.skills.base import Skill
from sump.skills.procedure import ProcedureSkill


class SkillManager:
    """技能注册与发现"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册技能"""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """获取技能"""
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        """列出所有技能"""
        return list(self._skills.values())

    def unregister(self, name: str) -> None:
        """移除技能"""
        self._skills.pop(name, None)

    def discover(self, skills_dir: str) -> list[str]:
        """从目录递归加载所有技能 JSON（skills/permanent/**/*.json），返回加载的技能名列表。"""
        root = Path(skills_dir)
        if not root.exists():
            return []
        loaded: list[str] = []
        for path in sorted(root.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                skill = ProcedureSkill.from_dict(data)
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if skill.name:
                self.register(skill)
                loaded.append(skill.name)
        return loaded
