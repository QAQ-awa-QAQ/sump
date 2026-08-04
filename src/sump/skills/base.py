"""Skill 抽象基类"""

from abc import ABC, abstractmethod
from typing import Any

from sump.types import SkillProficiency


class Skill(ABC):
    """所有技能的抽象基类"""

    name: str = ""
    description: str = ""
    proficiency: SkillProficiency = SkillProficiency.INITIAL

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行技能"""

    def to_prompt(self) -> str:
        """生成技能的 prompt 描述"""
        return f"Skill: {self.name} - {self.description}"
