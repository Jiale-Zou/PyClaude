from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    doc_id: str
    score: float
    text: str
    metadata: dict[str, Any]
