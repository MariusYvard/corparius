"""A dependency-free embedding and the similarity over it. Rank 0: pure.

These two functions were inside `safety.py`, which is domain policy — a token ceiling, a
loop guard, a spend-velocity breaker. That is why `store`, which is rank 2, had to import a
rank-4 module: it wanted a bag-of-tokens vector, not a firewall. Two unrelated things in one
file made a real edge look necessary.

Nothing here has an opinion. `LoopGuard` still owns the threshold that decides what counts
as a stutter; this module only says how similar two texts are.
"""

from __future__ import annotations

import hashlib
import math


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Mismatched lengths return 0.0 rather than raising or silently comparing the shorter
    prefix. This feeds LoopGuard, where 0.0 reads as "not a stutter", so a swapped-in
    embedding model that changes dimension mid-run lets the agent carry on instead of
    halting its day on an arithmetic detail. Truncating instead would produce a
    real-looking number from two unrelated vectors.
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def hash_embed(text: str, dim: int = 64) -> list[float]:
    """A cheap, dependency-free, deterministic bag-of-tokens embedding. Good enough to catch
    near-duplicate outputs offline; real similarity comes from the embedding model when the
    router is live."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    return vec
