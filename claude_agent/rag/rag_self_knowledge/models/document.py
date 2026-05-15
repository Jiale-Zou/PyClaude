from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentMetadata:
    doc_id: str | None = None
    source: str | None = None
    title: str | None = None
    author: str | None = None
    created_date: str | None = None
    tags: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
