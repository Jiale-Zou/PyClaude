from __future__ import annotations

from fastapi import APIRouter, Depends

from claude_agent.api.dependencies import get_agent_manager
from claude_agent.api.schemas.agent_schema import AgentResetResponse, AgentStatusResponse
from claude_agent.manager.agent_manager import AgentManager

router = APIRouter(tags=["agent"])


@router.get("/sessions/{session_id}/agent/status", response_model=AgentStatusResponse)
def get_status(session_id: str) -> AgentStatusResponse:
    return AgentStatusResponse(session_id=session_id, status="idle")


@router.post("/sessions/{session_id}/agent/reset", response_model=AgentResetResponse)
def reset_agent(
    session_id: str,
    user_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager),
) -> AgentResetResponse:
    agent_manager.reset_agent(user_id=user_id, session_id=session_id)
    return AgentResetResponse(session_id=session_id, ok=True)
