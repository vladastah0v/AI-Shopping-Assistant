from uuid import UUID

from app.ai.retrieval.fusion import reciprocal_rank_fusion


def test_fusion_deduplicates_and_rewards_cross_strategy_matches() -> None:
    a, b, c = (UUID(int=value) for value in range(1, 4))
    ranked = reciprocal_rank_fusion([a, a, b], [c, b])
    assert [item for item, _ in ranked] == [b, a, c]
    assert ranked[0][1] == 2 / 62
    assert reciprocal_rank_fusion([]) == []
