from __future__ import annotations

from pathlib import Path


def _user_memory_path(storage_root: Path, user_id: str) -> Path:
    return storage_root / user_id / ".PyClaude" / "MEMORY.md"


def ensure_user_memory(storage_root: Path, user_id: str) -> Path:
    '''确保用户的 MEMORY.md 存在'''
    p = _user_memory_path(storage_root, user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("", encoding="utf-8")
    return p


def load_user_profile_text(profile_path: Path) -> str:
    try:
        return profile_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def load_user_profile(storage_root: Path, user_id: str) -> str:
    p = ensure_user_memory(storage_root, user_id)
    return load_user_profile_text(p)
