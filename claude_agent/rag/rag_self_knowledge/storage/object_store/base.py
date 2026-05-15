from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    def put_text(self, *, key: str, text: str) -> str: ...

    def get_text(self, *, ref: str) -> str: ...
