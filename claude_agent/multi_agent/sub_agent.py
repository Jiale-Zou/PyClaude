from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent.core.query_engine import QueryEngine


@dataclass(slots=True)
class SubAgent:
    query_engine: QueryEngine = field(default_factory=QueryEngine)

    def run(self, task: str) -> str:
        return self.query_engine.run(task, subagent=True)
