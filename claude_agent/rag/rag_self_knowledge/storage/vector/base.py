from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class VectorItem:
    item_id: str
    embedding: list[float]
    document: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorQueryResult:
    item_id: str
    score: float
    document: str
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def upsert(self, *, collection: str, items: list[VectorItem]) -> None: ...

    def query(
        self,
        *,
        collection: str,
        query_embedding: list[float],
        top_k: int,
        where: Mapping[str, Any] | None = None,
    ) -> list[VectorQueryResult]: ...
