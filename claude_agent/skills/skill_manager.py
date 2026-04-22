from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent.skills.base_skill import BaseSkill


@dataclass(slots=True)
class SkillManager:
    skills: list[BaseSkill] = field(default_factory=list)

    def register(self, skill: BaseSkill) -> None:
        self.skills.append(skill)

    def dispatch(self, user_input: str) -> str | None:
        for skill in self.skills:
            if skill.can_handle(user_input):
                return skill.run(user_input)
        return None
