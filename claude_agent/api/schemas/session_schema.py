from __future__ import annotations

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    session_id: str


class SessionListResponse(BaseModel):
    sessions: list[dict[str, str]]
