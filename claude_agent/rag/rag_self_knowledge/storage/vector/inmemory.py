from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .base import VectorItem, VectorQueryResult, VectorStore


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def _cosine(a: list[float], b: list[float]) -> float:
    na = _norm(a)
    nb = _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


@dataclass
class InMemoryVectorStore(VectorStore):
    _data: dict[str, dict[str, VectorItem]]

    def __init__(self) -> None:
        self._data = {}

    def upsert(self, *, collection: str, items: list[VectorItem]) -> None:
        col = self._data.setdefault(collection, {})
        for it in items:
            col[it.item_id] = it

    def query(
        self,
        *,
        collection: str,
        query_embedding: list[float],
        top_k: int,
        where: Mapping[str, Any] | None = None,
    ) -> list[VectorQueryResult]:
        col = self._data.get(collection, {})
        results: list[VectorQueryResult] = []
        for item in col.values():
            if where is not None:
                matched = True
                for k, v in where.items():
                    if item.metadata.get(k) != v:
                        matched = False
                        break
                if not matched:
                    continue

            score = _cosine(query_embedding, item.embedding)
            results.append(
                VectorQueryResult(
                    item_id=item.item_id,
                    score=score,
                    document=item.document,
                    metadata=dict(item.metadata),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[: max(0, top_k)]
