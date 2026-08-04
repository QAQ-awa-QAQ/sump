"""从任务自动创建技能"""

from sump.skills.base import Skill
from sump.skills.manager import SkillManager


class SkillCreator:
    """根据任务执行结果自动创建新技能"""

    def __init__(self, manager: SkillManager):
        self.manager = manager

    async def create_from_task(self, task_description: str, result: str) -> Skill | None:
        """从成功任务中提炼技能"""
        return None
