from unittest.mock import AsyncMock

import pytest

from app.ai.embeddings.pipeline import Chunking
from app.ai.embeddings.service import EMBEDDING_DIMENSIONS, EmbeddingService
from app.modules.catalog.models import Product


@pytest.mark.asyncio
async def test_embeddings_use_e5_prefixes_and_deduplicate_inputs(
    embedding_provider_factory,
) -> None:
    provider = embedding_provider_factory("v1")
    service = EmbeddingService(provider, batch_size=2, cache_size=2)

    first, repeated, second = await service.encode_batch(("ноутбук", " ноутбук  ", "планшет"))
    assert first == repeated and first != second
    assert await service.encode_text("ноутбук") == first
    assert await service.encode_query("ноутбук") != first
    assert provider.calls == [("passage: ноутбук",), ("passage: планшет",), ("query: ноутбук",)]

    await service.encode_text("планшет")
    assert provider.calls[-1] == ("passage: планшет",)
    assert await service.encode_batch(()) == []


@pytest.mark.asyncio
async def test_product_and_document_use_canonical_passage_text(embedding_provider_factory) -> None:
    provider = embedding_provider_factory("v1")
    service = EmbeddingService(provider)
    product = Product(
        name="Модель Т1",
        sku="T1",
        description="  Рабочий   ноутбук ",
        specifications={"ssd_gb": 512, "ram_gb": 16},
    )

    vector = await service.generate_product_embedding(product, "Ноутбуки", "Астролив")
    await service.generate_document_embedding("Руководство", " Запуск   устройства ")
    product_input = provider.calls[0][0]
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert product_input.startswith("passage: Товар: Модель Т1.")
    assert 'Рабочий ноутбук Характеристики: {"ram_gb": 16, "ssd_gb": 512}' in product_input
    assert provider.calls[1] == ("passage: Руководство. Запуск устройства",)


@pytest.mark.parametrize(
    "vectors,message",
    [
        ([], "неверное число"),
        ([[1.0, 0.0]], "Размерность"),
        ([[0.0] * EMBEDDING_DIMENSIONS], "ненулевой"),
        ([[float("nan")] + [1.0] * (EMBEDDING_DIMENSIONS - 1)], "конечными"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_provider_result_is_rejected(
    embedding_provider_factory, vectors, message
) -> None:
    provider = embedding_provider_factory("v1")
    provider.encode_batch = AsyncMock(return_value=vectors)
    service = EmbeddingService(provider)
    with pytest.raises(ValueError, match=message):
        await service.encode_text("Ноутбук")


def test_chunking_limits_size_and_preserves_overlap() -> None:
    chunking = Chunking(size=8, overlap=3)
    assert list(chunking.split("  abcdefghijklmnop  ")) == ["abcdefgh", "fghijklm", "klmnop"]
    assert list(chunking.split(" \n ")) == []
    assert list(Chunking(size=3, overlap=2).split("a b c")) == ["a b", "b", "b c"]
    with pytest.raises(ValueError, match="перекрытие"):
        Chunking(size=7, overlap=7)
