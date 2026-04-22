from __future__ import annotations

from pydantic import BaseModel


class CommandCheckResponse(BaseModel):
    decision: str
    normalized: str
    reason: str


class PathCheckResponse(BaseModel):
    decision: str
    normalized: str
    reason: str
