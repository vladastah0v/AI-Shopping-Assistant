import pytest

from app.ai.retrieval.keyword import product_keyword_statement
from app.modules.catalog.schemas import ProductFilters


@pytest.mark.parametrize(
    "query,top_k", [(" ", 10), ("x" * 513, 10), ("sku\x00", 10), ("ноутбук", 0), ("ноутбук", 101)]
)
def test_invalid_keyword_search_arguments_are_rejected(query: str, top_k: int) -> None:
    with pytest.raises(ValueError):
        product_keyword_statement(query, ProductFilters(), top_k)
