from __future__ import annotations

from collections import defaultdict


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]], *, k: int = 60
) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return dict(scores)
