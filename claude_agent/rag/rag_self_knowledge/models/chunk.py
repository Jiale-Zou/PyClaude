from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    chunk_index: int
    text: str
    content_hash: str
    text_ref: str | None = None
