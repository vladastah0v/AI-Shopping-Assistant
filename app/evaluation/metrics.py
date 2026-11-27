from collections.abc import Iterable, Sequence
from math import log2


def ranking_scores(returned: Sequence[str], relevant: Iterable[str], k: int) -> dict[str, float]:
    expected = set(relevant)
    ranked = list(dict.fromkeys(returned))[:k]
    hits = [rank for rank, sku in enumerate(ranked, start=1) if sku in expected]
    return {
        "precision_at_k": len(hits) / k,
        "recall_at_k": len(hits) / len(expected) if expected else 0,
        "mrr": 1 / hits[0] if hits else 0,
        "ndcg_at_k": sum(1 / log2(rank + 1) for rank in hits)
        / sum(1 / log2(rank + 1) for rank in range(1, min(k, len(expected)) + 1))
        if expected
        else 0,
    }


def rate(numerator: int, denominator: int) -> float | str:
    return round(numerator / denominator, 6) if denominator else "NOT_MEASURED"
