"""技能管理器（注册/发现/加载）"""

from sump.skills.base import Skill


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
