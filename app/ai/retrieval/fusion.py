from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID


def reciprocal_rank_fusion(*rankings: Iterable[UUID]) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(dict.fromkeys(ranking), start=1):
            scores[item] += 1 / (60 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
