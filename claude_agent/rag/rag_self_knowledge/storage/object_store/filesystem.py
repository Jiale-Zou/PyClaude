from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSystemObjectStore:
    root: Path

    def put_text(self, *, key: str, text: str) -> str:
        rel = key.lstrip("/").replace("\\", "/")
        path = (self.root / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return f"fs://{path.as_posix()}"

    def get_text(self, *, ref: str) -> str:
        if not ref.startswith("fs://"):
            raise ValueError("unsupported ref")
        path = Path(ref[len("fs://") :])
        return path.read_text(encoding="utf-8")
