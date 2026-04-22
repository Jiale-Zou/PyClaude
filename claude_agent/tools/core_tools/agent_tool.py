from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from claude_agent.tools.base_tool import BaseTool


class AgentInput(BaseModel):
    task: str


class AgentOutput(BaseModel):
    result: str


@dataclass(slots=True)
class AgentTool(BaseTool):
    name: str = "agent"
    search_hint: str = "创建子代理处理独立任务并返回结果，适合并行或离线推理，或用于隔离历史messages减少上下文"
    description: str = "Create a single sub-agent to execute sub tasks, help to reduce the inference of context."
    input_schema = AgentInput
    output_schema = AgentOutput
    needs_permission: bool = False

    def execute(self, **kwargs: Any) -> BaseModel:
        from claude_agent.multi_agent.sub_agent import SubAgent
        agent = SubAgent()
        result = agent.run(str(kwargs["task"]))
        return AgentOutput(result=result)
