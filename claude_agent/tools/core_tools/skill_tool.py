from __future__ import annotations

from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from claude_agent.tools.base_tool import BaseTool


class SkillLoadInput(BaseModel):
    skill_name: str = Field(description="Skill 目录名（不含空格）")


class SkillLoadOutput(BaseModel):
    ok: bool
    content: str = ""
    error: str = ""


class SkillTool(BaseTool):
    name: str = "skill_tool"
    search_hint: str = "Load a custom skill's SKILL.md"
    description: str = (
        "Read and return the SKILL.md content of a custom skill located in "
        "claude_agent/skills/custom_skills/{skill_name}/SKILL.md."
    )
    input_schema: type[BaseModel] = SkillLoadInput
    output_schema: type[BaseModel] = SkillLoadOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        """Load SKILL.md from the specified skill directory."""
        skill_name = str(kwargs["skill_name"])
        if not skill_name or "/" in skill_name or "\\" in skill_name:
            return SkillLoadOutput(ok=False, error="Invalid skill_name.")

        skill_dir = (
            Path(__file__).resolve().parent.parent.parent
            / "skills"
            / "custom_skills"
            / skill_name
        )
        skill_md = skill_dir / "SKILL.md"

        if not skill_md.is_file():
            return SkillLoadOutput(
                ok=False, error=f"SKILL.md not found in {skill_dir.as_posix()}."
            )

        try:
            content = skill_md.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return SkillLoadOutput(ok=False, error=f"Read failed: {e}")

        return SkillLoadOutput(ok=True, content=content)