from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from claude_agent.api.dependencies import get_agent_manager, get_session_manager
from claude_agent.api.schemas.chat_schema import ChatRequest, ChatResponse
from claude_agent.manager.agent_manager import AgentManager
from claude_agent.manager.session_manager import SessionManager

router = APIRouter(tags=["chat"])


@router.post("/sessions/{session_id}/chat", response_model=ChatResponse)
def chat(
    session_id: str,
    req: ChatRequest,
    user_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    agent_manager: AgentManager = Depends(get_agent_manager),
) -> ChatResponse:
    session = session_manager.get_session(user_id=user_id, session_id=session_id)
    if session is None:
        session = session_manager.create_session(user_id=user_id, session_id=session_id)
    agent = agent_manager.get_agent(user_id=user_id, session_id=session_id)
    agent.messages = list(session.messages)
    reply = agent.run(req.message, user_id=user_id, session_id=session_id)
    session.messages = [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in agent.messages]
    return ChatResponse(session_id=session_id, reply=reply)


class ConfirmRequest(BaseModel):
    confirmed: bool


@router.post("/sessions/{session_id}/chat/confirm", response_model=ChatResponse)
def confirm_tool(
    session_id: str,
    req: ConfirmRequest,
    user_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
    agent_manager: AgentManager = Depends(get_agent_manager),
) -> ChatResponse:
    session = session_manager.get_session(user_id=user_id, session_id=session_id)
    if session is None:
        session = session_manager.create_session(user_id=user_id, session_id=session_id)
    agent = agent_manager.get_agent(user_id=user_id, session_id=session_id)
    agent.messages = list(session.messages)
    reply = agent.confirm_pending(user_id=user_id, session_id=session_id, confirmed=bool(req.confirmed))
    session.messages = [dict(role=str(m.get("role", "")), content=str(m.get("content", ""))) for m in agent.messages]
    return ChatResponse(session_id=session_id, reply=reply)
