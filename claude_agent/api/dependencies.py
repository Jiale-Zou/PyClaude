from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_agent.config import AgentConfig
from claude_agent.manager.agent_manager import AgentManager
from claude_agent.manager.session_manager import SessionManager
from claude_agent.manager.user_manager import UserManager


@dataclass(slots=True)
class AppState:
    config: AgentConfig
    user_manager: UserManager
    session_manager: SessionManager
    agent_manager: AgentManager


_DEFAULT_STATE: AppState | None = None


def get_state() -> AppState:
    global _DEFAULT_STATE
    if _DEFAULT_STATE is None:
        config = AgentConfig()
        storage_root = Path(config.storage_dir)
        _DEFAULT_STATE = AppState(
            config=config,
            user_manager=UserManager(storage_root=storage_root),
            session_manager=SessionManager(),
            agent_manager=AgentManager(),
        )
    return _DEFAULT_STATE


def get_user_manager() -> UserManager:
    return get_state().user_manager


def get_session_manager() -> SessionManager:
    return get_state().session_manager


def get_agent_manager() -> AgentManager:
    return get_state().agent_manager
