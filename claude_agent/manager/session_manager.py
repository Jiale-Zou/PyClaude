from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class Session:
    session_id: str # 会话唯一标识
    created_at: str # 创建时间（ISO格式）
    messages: list[dict[str, str]] = field(default_factory=list) # 消息历史

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})


@dataclass(slots=True)
class SessionManager:
    _sessions_by_user: dict[str, dict[str, Session]] = field(default_factory=dict) # user_id: {session_id:Session}

    def list_sessions(self, user_id: str) -> list[Session]:
        '''列出用户的所有会话'''
        sessions = self._sessions_by_user.get(user_id, {})
        return sorted(sessions.values(), key=lambda s: s.created_at)

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        '''列出用户的所有会话'''
        return self._sessions_by_user.get(user_id, {}).get(session_id)

    def create_session(self, user_id: str, session_id: str) -> Session:
        '''创建新会话（或获取已存在的）'''
        user_sessions = self._sessions_by_user.setdefault(user_id, {})
        if session_id in user_sessions:
            return user_sessions[session_id]
        created_at = datetime.now(timezone.utc).isoformat()
        session = Session(session_id=session_id, created_at=created_at)
        user_sessions[session_id] = session
        return session
