from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from claude_agent.api.dependencies import get_agent_manager, get_session_manager
from claude_agent.api.schemas.session_schema import SessionCreateRequest, SessionListResponse
from claude_agent.manager.agent_manager import AgentManager
from claude_agent.manager.session_manager import SessionManager
from claude_agent.prompt.static_prompt import ensure_pyclaude_md
from claude_agent.prompt.user_profile import ensure_user_memory

router = APIRouter(tags=["session"])


@router.get("/users/{user_id}/sessions", response_model=SessionListResponse)
def list_sessions(user_id: str, session_manager: SessionManager = Depends(get_session_manager)) -> SessionListResponse:
    sessions = session_manager.list_sessions(user_id)
    out: list[dict[str, str]] = []
    for s in sessions:
        first_user = ""
        for m in s.messages:
            if str(m.get("role", "")).lower() == "user":
                first_user = str(m.get("content", ""))
                break
        out.append(
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "preview": (first_user.strip()[:30] if first_user else ""),
            }
        )
    return SessionListResponse(sessions=out)


@router.post("/users/{user_id}/sessions", response_model=SessionListResponse)
def create_session(
    user_id: str,
    req: SessionCreateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
) -> SessionListResponse:
    session_manager.create_session(user_id=user_id, session_id=req.session_id)
    storage_root = Path("storage")
    ensure_pyclaude_md()
    ensure_user_memory(storage_root, user_id)
    sessions = session_manager.list_sessions(user_id)
    out: list[dict[str, str]] = []
    for s in sessions:
        out.append({"session_id": s.session_id, "created_at": s.created_at})
    return SessionListResponse(sessions=out)


@router.get("/users/{user_id}/sessions/{session_id}/messages")
def get_session_messages(
    user_id: str,
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
) -> dict[str, object]:
    session = session_manager.get_session(user_id=user_id, session_id=session_id)
    if session is None:
        return {"user_id": user_id, "session_id": session_id, "created_at": "", "messages": []}
    return {
        "user_id": user_id,
        "session_id": session_id,
        "created_at": session.created_at,
        "messages": list(session.messages),
    }


@router.post("/users/{user_id}/sessions/{session_id}/clear")
def clear_session(
    user_id: str,
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    agent_manager: AgentManager = Depends(get_agent_manager),
) -> dict[str, object]:
    session = session_manager.get_session(user_id=user_id, session_id=session_id)
    if session is not None:
        session.messages = []
    agent_manager.reset_agent(user_id=user_id, session_id=session_id)
    return {"ok": True, "user_id": user_id, "session_id": session_id}
