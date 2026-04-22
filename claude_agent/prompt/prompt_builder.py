from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_agent.prompt.dynamic_prompt import DynamicPromptContext, build_dynamic_prompt
from claude_agent.prompt.static_prompt import STATIC_PROMPT, build_static_system_prompt
from claude_agent.prompt.user_profile import load_user_profile


@dataclass(frozen=True, slots=True)
class PromptBundle:
    system_prompt: str
    user_prompt: str


@dataclass(slots=True)
class PromptBuilder:
    static_prompt: str = STATIC_PROMPT
    storage_root: Path = Path("storage")

    def build(self, dynamic_ctx: DynamicPromptContext, user_profile_text: str = "") -> str:
        '''当不需要完整的会话管理，可以用这个轻量级方法快速构建提示词'''
        dynamic_prompt = build_dynamic_prompt(dynamic_ctx)
        parts = [p for p in [self.static_prompt, user_profile_text, dynamic_prompt] if p]
        return "\n\n".join(parts)

    def build_prompts(
        self,
        *,
        user_id: str,
        session_id: str,
        messages: list[dict[str, str]],
        instructions: str = "",
    ) -> PromptBundle:
        system_static = build_static_system_prompt()
        user_profile = load_user_profile(self.storage_root, user_id)
        system_prompt = system_static.strip() + "\n"

        ctx = DynamicPromptContext(
            messages=messages,
            instructions=instructions,
            user_id=user_id,
            session_id=session_id,
            storage_root=self.storage_root,
        )
        dynamic_prompt = build_dynamic_prompt(ctx)
        user_prompt = "\n\n".join([p for p in [user_profile.strip(), dynamic_prompt.strip()] if p]) + "\n"
        return PromptBundle(system_prompt=system_prompt, user_prompt=user_prompt)
