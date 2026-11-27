from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.embeddings.models import DocumentChunk, ProductEmbedding
from app.ai.embeddings.pipeline import Chunking, generate_embeddings
from app.ai.embeddings.service import EMBEDDING_DIMENSIONS, EmbeddingService
from app.modules.catalog.models import Brand, Category, DocumentType, Product, ProductDocument

pytestmark = pytest.mark.asyncio


async def test_generation_updates_only_changed_content_and_preserves_other_versions(
    session: AsyncSession, embedding_provider_factory
) -> None:
    suffix = uuid4().hex
    product = Product(
        category=Category(name="Ноутбуки", slug=f"embeddings-{suffix}", description=""),
        brand=Brand(name=f"Астролив {suffix}", description=""),
        name="Ноутбук Т1",
        sku=f"T-{suffix}",
        description="Модель для программирования",
        price=Decimal("75000.00"),
        specifications={"ram_gb": 32, "ssd_gb": 512},
    )
    document = ProductDocument(
        product=product,
        document_type=DocumentType.PRODUCT_MANUAL,
        title="Руководство",
        content="Подключите питание и запустите настройку системы. " * 7,
        source="catalog/manual/v1",
    )
    session.add_all([product, document])
    await session.flush()
    sessions = async_sessionmaker(
        await session.connection(), join_transaction_mode="create_savepoint"
    )
    old_provider = embedding_provider_factory(f"v1-{suffix}")
    new_provider = embedding_provider_factory(f"v2-{suffix}")
    chunking = Chunking(size=80, overlap=12)

    first = await generate_embeddings(
        sessions, EmbeddingService(old_provider, batch_size=4), chunking
    )
    assert first.products_written >= 1 and first.chunks_written > 1
    old_version = old_provider.space.version
    new_version = new_provider.space.version
    old_rows = (
        select(DocumentChunk.content_hash, DocumentChunk.chunk_metadata)
        .where(
            DocumentChunk.document_id == document.id, DocumentChunk.embedding_version == old_version
        )
        .order_by(DocumentChunk.chunk_index)
    )
    old_chunks = (await session.execute(old_rows)).all()
    assert len(old_chunks) > 1

    vector_statement = select(ProductEmbedding.embedding, ProductEmbedding.content_hash).where(
        ProductEmbedding.product_id == product.id, ProductEmbedding.embedding_version == old_version
    )
    initial = (await session.execute(vector_statement)).one()
    assert (
        await session.scalar(
            select(func.vector_dims(ProductEmbedding.embedding)).where(
                ProductEmbedding.product_id == product.id,
                ProductEmbedding.embedding_version == old_version,
            )
        )
        == EMBEDDING_DIMENSIONS
    )
    assert await session.scalar(
        select(ProductEmbedding.embedding.cosine_distance(initial.embedding)).where(
            ProductEmbedding.product_id == product.id,
            ProductEmbedding.embedding_version == old_version,
        )
    ) == pytest.approx(0.0, abs=1e-6)

    product.price = Decimal("69900.10")
    product.stock_quantity = 5
    document.source = "catalog/manual/new-link"
    await session.flush()
    old_provider.calls.clear()
    metadata_update = await generate_embeddings(sessions, EmbeddingService(old_provider), chunking)
    assert metadata_update.products_written == 0
    assert metadata_update.chunks_written == len(old_chunks)
    assert old_provider.calls == []
    refreshed = (await session.execute(old_rows)).all()
    assert [row.content_hash for row in refreshed] == [row.content_hash for row in old_chunks]
    assert all(row.chunk_metadata["source"] == "catalog/manual/new-link" for row in refreshed)

    await generate_embeddings(sessions, EmbeddingService(new_provider), chunking)
    product.description = "Обновлённое описание модели"
    document.content = "Короткое руководство по запуску."
    await session.flush()
    changed = await generate_embeddings(sessions, EmbeddingService(old_provider), chunking)
    assert changed.products_written == changed.chunks_written == 1
    assert changed.chunks_removed == len(old_chunks) - 1
    assert (await session.execute(vector_statement)).one().content_hash != initial.content_hash

    remaining_other_version = await session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(
            DocumentChunk.document_id == document.id, DocumentChunk.embedding_version == new_version
        )
    )
    assert remaining_other_version == len(old_chunks)

    old_provider.calls.clear()
    repeat = await generate_embeddings(sessions, EmbeddingService(old_provider), chunking)
    assert repeat.products_written == repeat.chunks_written == repeat.chunks_removed == 0
    assert old_provider.calls == []
