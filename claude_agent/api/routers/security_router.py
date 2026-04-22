from __future__ import annotations

from fastapi import APIRouter

from claude_agent.api.schemas.security_schema import CommandCheckResponse, PathCheckResponse
from claude_agent.security.command_whitelist import CommandWhitelist
from claude_agent.security.path_validator import PathValidator
from claude_agent.security.semantic_analyzer import SemanticAnalyzer

router = APIRouter(tags=["security"])


@router.get("/security/command/check", response_model=CommandCheckResponse)
def check_command(command: str) -> CommandCheckResponse:
    decision = CommandWhitelist().decision_for_frontend(command)
    return CommandCheckResponse(**decision)


@router.get("/security/path/check", response_model=PathCheckResponse)
def check_path(path: str) -> PathCheckResponse:
    decision = PathValidator().decision_for_frontend(path)
    return PathCheckResponse(**decision)


@router.get("/security/command/semantic/check", response_model=CommandCheckResponse)
def check_command_semantic(command: str) -> CommandCheckResponse:
    decision = SemanticAnalyzer().decision_for_frontend(command)
    return CommandCheckResponse(**decision)
