"""从任务自动创建技能（小脑技能固化）"""

import json
from pathlib import Path
from typing import Any

from sump.skills.base import Skill
from sump.skills.manager import SkillManager
from sump.skills.procedure import ProcedureSkill


def _safe_name(name: str) -> str:
    """把技能名清洗成安全的文件名。"""
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name).strip("_") or "skill"


class SkillCreator:
    """根据成功任务提炼并持久化新技能。"""

    def __init__(
        self,
        manager: SkillManager,
        llm: Any = None,
        skills_dir: str = "skills/permanent",
        auto_create: bool = True,
    ) -> None:
        self.manager = manager
        self._llm = llm
        self._skills_dir = Path(skills_dir)
        self._auto_create = auto_create

    async def create_from_task(self, task_description: str, result: str) -> Skill | None:
        """从成功任务中提炼技能；提炼失败或无复用价值返回 None。"""
        if not self._auto_create or self._llm is None:
            return None

        from sump.memory._llm_json import chat_flash_json

        prompt = (
            "以下是用户与助手成功完成的一个任务。请判断它是否包含可复用的通用步骤，"
            "若值得固化，提炼成一个技能（名称 + 一句话描述 + 步骤列表）。\n"
            f"任务描述：{task_description}\n"
            f"执行结果：{result}\n\n"
            "只输出 JSON，不要 markdown、不要解释：\n"
            '{"name": "技能名", "description": "一句话描述", "steps": ["步骤1", "步骤2"]}\n'
            "若没有可复用的通用步骤，输出：{\"name\": \"\", \"description\": \"\", \"steps\": []}"
        )
        data = await chat_flash_json(
            self._llm, prompt, max_tokens=512, temperature=0.3, label="skill_creator"
        )
        if data is None:
            return None

        skill = ProcedureSkill.from_dict(data)
        if not skill.name or not skill.description or not skill.steps:
            return None

        self._persist(skill)
        self.manager.register(skill)
        return skill

    def _persist(self, skill: ProcedureSkill) -> Path:
        """持久化技能到 skills_dir/{proficiency}/{name}.json。"""
        path = self._skills_dir / skill.proficiency.value / f"{_safe_name(skill.name)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(skill.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path
