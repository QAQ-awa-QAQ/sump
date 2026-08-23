"""过程技能（可持久化的具体技能）"""

from typing import Any

from sump.skills.base import Skill
from sump.types import SkillProficiency


class ProcedureSkill(Skill):
    """可复用的过程技能：名称 + 描述 + 步骤列表。

    执行时返回给 LLM 的提示文本（过程记忆，非代码）。
    支持 JSON 序列化，用于持久化到 skills/permanent/。
    """

    def __init__(
        self,
        name: str,
        description: str,
        steps: list[str] | None = None,
        proficiency: SkillProficiency = SkillProficiency.INITIAL,
    ) -> None:
        self.name = name
        self.description = description
        self.steps = steps or []
        self.proficiency = proficiency

    async def execute(self, **kwargs: Any) -> str:
        """执行技能：返回给 LLM 的过程提示。"""
        return self.to_prompt()

    def to_prompt(self) -> str:
        lines = [f"Skill: {self.name} - {self.description}"]
        if self.steps:
            lines.append("步骤：")
            lines.extend(f"{i + 1}. {s}" for i, s in enumerate(self.steps))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": self.steps,
            "proficiency": self.proficiency.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcedureSkill":
        proficiency = data.get("proficiency", "initial")
        try:
            prof = SkillProficiency(str(proficiency))
        except ValueError:
            prof = SkillProficiency.INITIAL
        return cls(
            name=str(data.get("name", "")).strip(),
            description=str(data.get("description", "")).strip(),
            steps=[str(s) for s in data.get("steps", []) or []],
            proficiency=prof,
        )
