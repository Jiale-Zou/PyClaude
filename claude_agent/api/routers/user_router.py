from __future__ import annotations

from fastapi import APIRouter, Depends

from claude_agent.api.dependencies import get_user_manager
from claude_agent.api.schemas.user_schema import UserListResponse
from claude_agent.manager.user_manager import UserManager

router = APIRouter(tags=["user"])


@router.get("/users", response_model=UserListResponse)
def list_users(user_manager: UserManager = Depends(get_user_manager)) -> UserListResponse:
    return UserListResponse(users=user_manager.list_users())
