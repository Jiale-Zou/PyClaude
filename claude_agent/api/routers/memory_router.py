from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from claude_agent.api.dependencies import get_state
from claude_agent.prompt.user_profile import ensure_user_memory

router = APIRouter(tags=["memory"])


@router.get("/users/{user_id}/memory")
def get_memory(user_id: str) -> dict[str, object]:
    return {"user_id": user_id, "items": []}


@router.get("/files/config")
def get_config_file() -> dict[str, str]:
    p = Path(__file__).resolve().parents[2] / "config.py"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""
    return {"path": str(p), "content": content}


@router.get("/users/{user_id}/files/memory")
def get_user_memory_file(user_id: str) -> dict[str, str]:
    storage_root = Path(get_state().config.storage_dir)
    p = ensure_user_memory(storage_root, user_id)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        content = ""
    return {"path": str(p), "content": content}


class SaveTextRequest(BaseModel):
    content: str


@router.put("/users/{user_id}/files/memory")
def save_user_memory_file(user_id: str, req: SaveTextRequest) -> dict[str, object]:
    storage_root = Path(get_state().config.storage_dir)
    p = ensure_user_memory(storage_root, user_id)
    p.write_text(str(req.content), encoding="utf-8")
    return {"ok": True, "path": str(p)}
