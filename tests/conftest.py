from collections.abc import Sequence
from hashlib import sha256

import pytest

from app.ai.embeddings.service import EMBEDDING_DIMENSIONS, EmbeddingSpace


class FakeEmbeddingProvider:
    def __init__(self, version: str) -> None:
        self.space = EmbeddingSpace(
            "test/catalog-embeddings", version, EMBEDDING_DIMENSIONS, "query: ", "passage: "
        )
        self.calls: list[tuple[str, ...]] = []

    async def encode_batch(self, prefixed_texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(tuple(prefixed_texts))
        vectors = []
        for text in prefixed_texts:
            digest = sha256(text.encode()).digest()
            vectors.append(
                [float(value) / 255 for value in digest]
                + [0.0] * (self.space.dimensions - len(digest))
            )
        return vectors


@pytest.fixture
def embedding_provider_factory() -> type[FakeEmbeddingProvider]:
    return FakeEmbeddingProvider
