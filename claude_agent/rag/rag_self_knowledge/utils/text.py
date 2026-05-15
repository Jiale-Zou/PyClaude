from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .hashing import sha256_text


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class HashingEmbedder:
    dim: int = 256

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        if not tokens:
            return vec

        for tok in tokens:
            h = sha256_text(tok)
            idx = int(h[:8], 16) % self.dim
            sign = -1.0 if (int(h[8:16], 16) % 2) else 1.0
            vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
