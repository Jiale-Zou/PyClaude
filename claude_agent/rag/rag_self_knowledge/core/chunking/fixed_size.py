from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ...models.chunk import Chunk
from ...models.ids import new_id
from ...utils.hashing import sha256_text
from .base import BaseChunker


@dataclass(frozen=True)
class FixedSizeChunker(BaseChunker):
    chunk_size: int = 800
    overlap: int = 100

    def chunk(
        self, text: str, *, doc_id: str, metadata: Mapping[str, Any] | None = None
    ) -> list[Chunk]:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if self.overlap < 0:
            raise ValueError("overlap must be >= 0")
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap must be < chunk_size")

        cleaned = text or ""
        chunks: list[Chunk] = []

        start = 0
        chunk_index = 0
        step = self.chunk_size - self.overlap
        while start < len(cleaned):
            end = min(len(cleaned), start + self.chunk_size)
            chunk_text = cleaned[start:end]
            chunk_hash = sha256_text(chunk_text)
            chunks.append(
                Chunk(
                    chunk_id=new_id(),
                    doc_id=doc_id,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    content_hash=chunk_hash,
                    text_ref=None,
                )
            )
            chunk_index += 1
            start += step

        return chunks
