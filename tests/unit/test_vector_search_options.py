from dataclasses import replace

import pytest

from app.ai.embeddings.huggingface import E5_SMALL
from app.ai.embeddings.service import EMBEDDING_DIMENSIONS
from app.ai.retrieval.vector import VectorSearchOptions, product_candidates
from app.modules.catalog.schemas import ProductFilters


@pytest.mark.parametrize(
    "options", [{"top_k": 0}, {"top_k": 101}, {"ef_search": 1001}, {"mode": "invalid"}]
)
def test_invalid_vector_search_options(options) -> None:
    with pytest.raises(ValueError):
        VectorSearchOptions(**options)


def test_vector_query_has_to_belong_to_supported_dimension() -> None:
    with pytest.raises(ValueError, match="Размерность"):
        product_candidates([1.0], E5_SMALL, ProductFilters())
    with pytest.raises(ValueError, match="пространства поиска"):
        product_candidates([1.0], replace(E5_SMALL, dimensions=1), ProductFilters())
    with pytest.raises(ValueError, match="ненулевой"):
        product_candidates([0.0] * EMBEDDING_DIMENSIONS, E5_SMALL, ProductFilters())
