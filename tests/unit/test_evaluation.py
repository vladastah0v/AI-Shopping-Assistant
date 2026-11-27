from app.evaluation.metrics import ranking_scores, rate
from app.evaluation.scenarios import scenarios


def test_benchmark_fixture_is_fixed_and_has_at_least_100_scenarios() -> None:
    cases = scenarios()
    assert cases == scenarios()
    assert len(cases) == len({case.id for case in cases}) == 144
    assert len({case.id.rsplit("-", 1)[0] for case in cases}) == 12


def test_ranking_metrics_reward_early_unique_matches() -> None:
    result = ranking_scores(["B", "miss", "A", "A"], ["A", "B", "C"], 4)
    assert result["precision_at_k"] == 0.5
    assert result["recall_at_k"] == 2 / 3
    assert result["mrr"] == 1
    assert 0 < result["ndcg_at_k"] < 1
    assert rate(0, 0) == "NOT_MEASURED"
