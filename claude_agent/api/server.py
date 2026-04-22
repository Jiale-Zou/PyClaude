from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app() -> FastAPI:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Claude Agent")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from claude_agent.api.routers.agent_router import router as agent_router
    from claude_agent.api.routers.chat_router import router as chat_router
    from claude_agent.api.routers.memory_router import router as memory_router
    from claude_agent.api.routers.security_router import router as security_router
    from claude_agent.api.routers.session_router import router as session_router
    from claude_agent.api.routers.user_router import router as user_router

    app.include_router(user_router, prefix="/api")
    app.include_router(session_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(security_router, prefix="/api")

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app
