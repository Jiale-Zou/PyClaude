from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent.multi_agent.sub_agent import SubAgent


@dataclass(slots=True)
class TeamAgent:
    members: list[SubAgent] = field(default_factory=list)

    def run_parallel(self, tasks: list[str]) -> list[str]:
        if not self.members:
            self.members = [SubAgent() for _ in tasks]
        return [agent.run(task) for agent, task in zip(self.members, tasks, strict=False)]
