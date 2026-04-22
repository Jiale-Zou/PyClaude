from __future__ import annotations

from pydantic import BaseModel


class UserListResponse(BaseModel):
    users: list[str]
