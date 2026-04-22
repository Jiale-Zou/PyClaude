from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from claude_agent.tools.base_tool import BaseTool


class LoopBreakerInput(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class LoopBreakerOutput(BaseModel):
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class LoopBreakerTool(BaseTool):
    name: str = "loop_breaker"
    search_hint: str = "检测对话陷入循环时触发，用于打断并引导下一步行动"
    description: str = "A conditional tool used to break repetitive loops."
    input_schema = LoopBreakerInput
    output_schema = LoopBreakerOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        return LoopBreakerOutput(message="LoopBreakerTool triggered.", payload=dict(kwargs.get("payload") or {}))
