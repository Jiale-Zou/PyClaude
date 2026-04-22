from __future__ import annotations

from dataclasses import dataclass, field

from claude_agent.core.query_engine import QueryEngine


@dataclass(slots=True)
class AgentManager:
    _agent_by_session: dict[str, QueryEngine] = field(default_factory=dict) # '{user_if}:{session_id}': QueryEngine

    def _key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}:{session_id}"

    def get_agent(self, *, user_id: str, session_id: str) -> QueryEngine:
        '''获取或创建 Agent'''
        key = self._key(user_id, session_id)
        agent = self._agent_by_session.get(key)
        if agent is None:
            agent = QueryEngine()
            self._agent_by_session[key] = agent
        return agent

    def reset_agent(self, *, user_id: str, session_id: str) -> None:
        '''重置（删除）Agent'''
        self._agent_by_session.pop(self._key(user_id, session_id), None)
