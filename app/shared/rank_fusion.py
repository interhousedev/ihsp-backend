"""Reciprocal rank fusion: one ranking out of several, without comparing scores.

Full-text rank (`ts_rank_cd`) and cosine distance are on different scales, so their
numbers cannot be added or averaged. Reciprocal rank fusion (Cormack, Clarke and
Buettcher, SIGIR 2009) uses only the *positions*: a document earns `1 / (K + rank)`
from every ranking it appears in (rank starts at 1) and the earnings are summed.
"""

from collections.abc import Hashable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Hashable)

RRF_K = 60
"""The constant of the paper. It flattens the head of each ranking: with 60 the 1st
place is worth 1/61 and the 10th 1/70, so a document that is 3rd in both rankings
(2/63) beats one that is 1st in only one (1/61), but the top of a single list still
counts. Not tuned: the original value works across data sets and needs no labels."""

CANDIDATES = 24
"""How many documents each ranking contributes before fusion (at least; a caller that
wants more results gets that many). 24 is what the notebook chat asks for, so the
fused list is built from exactly the part of each ranking the model will read. A
deeper list lets a weak word match that also sits far down the other ranking collect
points from both and outrank a clear winner of one of them."""


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]], *, k: int = RRF_K
) -> list[T]:
    """The documents of all rankings, best first.

    A document earns `1 / (k + rank)` from each ranking that contains it. Equal scores
    keep the order of first appearance (the first ranking wins), so the result is
    deterministic, and a single ranking comes back unchanged. Pass the ranking you
    trust more first: it wins the ties.
    """
    scores: dict[T, float] = {}
    first_seen: dict[T, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(item, len(first_seen))
    return sorted(scores, key=lambda item: (-scores[item], first_seen[item]))
