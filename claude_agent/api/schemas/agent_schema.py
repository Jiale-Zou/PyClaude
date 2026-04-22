from __future__ import annotations

from pydantic import BaseModel


class AgentStatusResponse(BaseModel):
    session_id: str
    status: str


class AgentResetResponse(BaseModel):
    session_id: str
    ok: bool
