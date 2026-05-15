from __future__ import annotations

import json
from pathlib import Path


def ensure_pyclaude_md() -> Path:
    '''确保全局 PyClaude.md 文件存在'''
    d = Path(__file__).resolve().parent.parent / ".Pyclaude"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "PyClaude.md"
    if not p.exists():
        p.write_text("You are an agent.\n", encoding="utf-8")
    return p


def load_pyclaude_prompt() -> str:
    p = ensure_pyclaude_md()
    return p.read_text(encoding="utf-8")


def _collect_core_tools() -> list[dict[str, object]]:
    '''core_tool定义收集与格式化'''
    from claude_agent.tools.core_tools import (
        AgentTool,
        BashTool,
        FileEditTool,
        FileReadTool,
        FileWriteTool,
        GlobTool,
        GrepTool,
        RagTool,
        SkillTool,
        TodoWriteTool,
        ToolSearchTool
    )

    tools = [BashTool(), FileReadTool(), FileWriteTool(), FileEditTool(), GlobTool(), GrepTool(), AgentTool(), TodoWriteTool(), ToolSearchTool(), SkillTool(), RagTool()]
    out: list[dict[str, object]] = []
    for t in tools:
        out.append(
            {
                "name": t.name,
                "description": t.description,
                "needs_permission": bool(getattr(t, "needs_permission", False)),
                "input_schema": t.input_schema.model_json_schema(),
                "output_schema": t.output_schema.model_json_schema(),
            }
        )
    return out


def build_tools_prompt() -> str:
    tools = _collect_core_tools()
    return "\n".join(["# Tools", "", "```json", json.dumps(tools, ensure_ascii=False, indent=2), "```", ""])


def _extract_yaml_front_matter(text: str) -> str:
    '''从 Markdown 文件中提取 YAML Front Matte'''
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return ""
    return "\n".join(lines[1:end]).strip()


def _iter_skill_dirs(custom_skills_dir: Path) -> list[Path]:
    '''返回custom_skills_dir下的所有子目录'''
    if not custom_skills_dir.exists():
        return []
    return sorted([p for p in custom_skills_dir.iterdir() if p.is_dir()])


def build_skills_prompt(custom_skills_dir: Path) -> str:
    '''对每个skill目录，读取YAML信息'''
    skill_dirs = _iter_skill_dirs(custom_skills_dir)
    if not skill_dirs:
        return ""
    blocks: list[str] = ["# Skills", ""]
    for d in skill_dirs:
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        yaml = _extract_yaml_front_matter(text)
        if not yaml:
            continue
        blocks.extend(
            [
                f"## {d.name}",
                "",
                "```yaml",
                yaml,
                "```",
                "",
            ]
        )
    if len(blocks) <= 2:
        return ""
    return "\n".join(blocks)


def build_static_system_prompt() -> str:
    '''依次组装全局 PyClaude.md、tools、skills'''
    base = load_pyclaude_prompt().strip()
    tools = build_tools_prompt().strip()
    skills_dir = Path(__file__).resolve().parent.parent / "skills" / "custom_skills"
    skills = build_skills_prompt(skills_dir).strip()
    parts = [p for p in [base, tools, skills] if p]
    return "\n\n".join(parts) + "\n"


STATIC_PROMPT = "You are an agent.\n"
