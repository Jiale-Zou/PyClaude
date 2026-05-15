from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from ...models.chunk import Chunk


class BaseChunker(ABC):
    @abstractmethod
    def chunk(
        self, text: str, *, doc_id: str, metadata: Mapping[str, Any] | None = None
    ) -> list[Chunk]:
        raise NotImplementedError
