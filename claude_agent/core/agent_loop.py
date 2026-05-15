from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent.core.query_engine import QueryEngine


@dataclass(slots=True)
class AgentLoop:
    query_engine: QueryEngine = field(default_factory=QueryEngine)
    user_id: str = "local"
    session_id: str = "cli"

    def run(self) -> None:
        print("PyClaude start...")
        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                return
            result = self.query_engine.run(user_input, user_id=self.user_id, session_id=self.session_id)
            print(result)

if __name__ == "__main__":
    loop = AgentLoop()
    loop.run()
