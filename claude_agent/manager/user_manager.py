from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class UserManager:
    storage_root: Path

    def user_dir(self, user_id: str) -> Path:
        return self.storage_root / user_id

    def profile_path(self, user_id: str) -> Path:
        return self.user_dir(user_id) / "profile.md"

    def load_profile_text(self, user_id: str) -> str:
        try:
            return self.profile_path(user_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def list_users(self) -> list[str]:
        if not self.storage_root.exists():
            return []
        return sorted([p.name for p in self.storage_root.iterdir() if p.is_dir()])
