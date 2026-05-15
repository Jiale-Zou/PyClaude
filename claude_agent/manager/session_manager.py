from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class Session:
    session_id: str # 会话唯一标识
    created_at: str # 创建时间（ISO格式）
    messages: list[dict[str, str]] = field(default_factory=list) # 消息历史

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})


@dataclass(slots=True)
class SessionManager:
    storage_root: Path = Path("storage")
    _sessions_by_user: dict[str, dict[str, Session]] = field(default_factory=dict) # user_id: {session_id:Session}

    def _session_dir(self, user_id: str, session_id: str) -> Path:
        return self.storage_root / user_id / "sessions" / session_id

    def _session_file(self, user_id: str, session_id: str) -> Path:
        return self._session_dir(user_id, session_id) / "messages.json"

    def _load_session_from_disk(self, user_id: str, session_id: str) -> Session | None:
        p = self._session_file(user_id, session_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        created_at = str(data.get("created_at", "") or "")
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        normalized: list[dict[str, str]] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            normalized.append(
                {"role": str(m.get("role", "")), "content": str(m.get("content", ""))}
            )
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        return Session(session_id=session_id, created_at=created_at, messages=normalized)

    def save_session(self, user_id: str, session: Session) -> None:
        p = self._session_file(user_id, session.session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "user_id": user_id,
            "session_id": session.session_id,
            "created_at": session.created_at,
            "messages": list(session.messages),
        }
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _ensure_user_loaded(self, user_id: str) -> None:
        user_sessions = self._sessions_by_user.setdefault(user_id, {})
        base = self.storage_root / user_id / "sessions"
        if not base.exists():
            return
        for d in base.iterdir():
            if not d.is_dir():
                continue
            sid = d.name
            if sid in user_sessions:
                continue
            s = self._load_session_from_disk(user_id, sid)
            if s is not None:
                user_sessions[sid] = s

    def list_sessions(self, user_id: str) -> list[Session]:
        '''列出用户的所有会话'''
        self._ensure_user_loaded(user_id)
        sessions = self._sessions_by_user.get(user_id, {})
        return sorted(sessions.values(), key=lambda s: s.created_at)

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        '''列出用户的所有会话'''
        self._ensure_user_loaded(user_id)
        s = self._sessions_by_user.get(user_id, {}).get(session_id)
        if s is not None:
            return s
        loaded = self._load_session_from_disk(user_id, session_id)
        if loaded is None:
            return None
        self._sessions_by_user.setdefault(user_id, {})[session_id] = loaded
        return loaded

    def create_session(self, user_id: str, session_id: str) -> Session:
        '''创建新会话（或获取已存在的）'''
        self._ensure_user_loaded(user_id)
        user_sessions = self._sessions_by_user.setdefault(user_id, {})
        if session_id in user_sessions:
            return user_sessions[session_id]
        created_at = datetime.now(timezone.utc).isoformat()
        session = Session(session_id=session_id, created_at=created_at)
        user_sessions[session_id] = session
        self.save_session(user_id, session)
        return session
