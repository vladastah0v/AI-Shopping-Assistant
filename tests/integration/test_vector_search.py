from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from pgvector import Vector as PgVector
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.huggingface import E5_SMALL
from app.ai.embeddings.models import HNSW_INDEXES, DocumentChunk, ProductEmbedding
from app.ai.embeddings.service import EMBEDDING_DIMENSIONS, EmbeddingService, EmbeddingSpace
from app.ai.retrieval.indexing import rebuild_vector_indexes
from app.ai.retrieval.vector import (
    VectorSearch,
    VectorSearchOptions,
    document_candidates,
    product_candidates,
    rank_by_distance,
    search_document_vectors,
    search_product_vectors,
)
from app.modules.catalog.models import Brand, Category, DocumentType, Product, ProductDocument
from app.modules.catalog.schemas import ProductFilters

pytestmark = pytest.mark.asyncio


def _vector(offset: float) -> list[float]:
    return [1.0, offset] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


@dataclass
class SearchCatalog:
    products: dict[str, Product]
    alternate: EmbeddingSpace
    filters: ProductFilters


@pytest_asyncio.fixture
async def search_catalog(session: AsyncSession) -> SearchCatalog:
    suffix = uuid4().hex
    root = Category(name="Компьютерная техника", slug=f"computers-{suffix}", description="")
    laptops = Category(name="Ноутбуки", slug=f"laptops-{suffix}", description="", parent=root)
    other = Category(name="Наушники", slug=f"headphones-{suffix}", description="")
    brand = Brand(name=f"Астролив {suffix}", description="")
    alternate = replace(E5_SMALL, version=f"test-v2-{suffix}")
    products = {}
    variants = {
        "first": (laptops, 79_999, 3, 32, True, "RUB", 0.25, E5_SMALL),
        "second": (laptops, 80_000, 1, 16, True, "RUB", 0.5, E5_SMALL),
        "above-budget": (laptops, 80_001, 3, 32, True, "RUB", 0.0, E5_SMALL),
        "out-of-stock": (laptops, 70_000, 0, 32, True, "RUB", 0.0, E5_SMALL),
        "weak": (laptops, 70_000, 3, 8, True, "RUB", 0.0, E5_SMALL),
        "retired": (laptops, 70_000, 3, 32, False, "RUB", 0.0, E5_SMALL),
        "currency": (laptops, 90, 3, 32, True, "USD", 0.0, E5_SMALL),
        "wrong-category": (other, 70_000, 3, 32, True, "RUB", 0.0, E5_SMALL),
        "other-version": (laptops, 70_000, 3, 32, True, "RUB", 0.0, alternate),
    }

    for label, (category, price, stock, ram, active, currency, offset, space) in variants.items():
        product = Product(
            category=category,
            brand=brand,
            name=f"Модель {label}",
            sku=f"{suffix}-{label}",
            description="Синтетический товар",
            price=Decimal(price),
            currency=currency,
            stock_quantity=stock,
            specifications={"ram_gb": ram},
            is_active=active,
        )
        document = ProductDocument(
            product=product,
            document_type=DocumentType.PRODUCT_MANUAL,
            title=f"Документ {label}",
            content=f"Текст {label}",
            source=f"catalog/{label}",
        )
        products[label] = product
        session.add_all([product, document])
        await session.flush()
        session.add_all(
            [
                ProductEmbedding(
                    product_id=product.id,
                    embedding=_vector(offset),
                    content_hash="a" * 64,
                    embedding_model=space.model,
                    embedding_version=space.version,
                ),
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=0,
                    content=document.content,
                    chunk_metadata={},
                    embedding=_vector(offset),
                    content_hash="b" * 64,
                    embedding_model=space.model,
                    embedding_version=space.version,
                ),
            ]
        )
    await session.flush()
    return SearchCatalog(
        products,
        alternate,
        ProductFilters(
            category_id=root.id,
            max_price=Decimal("80000"),
            in_stock=True,
            spec=["ram_gb:gte:16"],
        ),
    )


async def test_exact_and_hnsw_respect_filters_and_document_provenance(
    session: AsyncSession,
    search_catalog: SearchCatalog,
) -> None:
    expected = [search_catalog.products[label].id for label in ("first", "second")]
    for mode in ("exact", "hnsw"):
        options = VectorSearchOptions(mode=mode, top_k=2)
        items = await search_product_vectors(
            session, _vector(0), E5_SMALL, filters=search_catalog.filters, options=options
        )
        documents = await search_document_vectors(
            session,
            _vector(0),
            E5_SMALL,
            filters=search_catalog.filters,
            document_type=DocumentType.PRODUCT_MANUAL,
            options=options,
        )
        assert [item.product_id for item in items] == expected
        assert [document.product_id for document in documents] == expected
        assert [document.source for document in documents] == ["catalog/first", "catalog/second"]
        assert [document.content for document in documents] == ["Текст first", "Текст second"]
        assert 0 < items[0].distance < items[1].distance < 1

    fallback = await search_product_vectors(
        session,
        _vector(0),
        E5_SMALL,
        filters=search_catalog.filters,
        options=VectorSearchOptions(top_k=5, ef_search=1),
    )
    assert [item.product_id for item in fallback] == expected

    other_version = await search_product_vectors(
        session,
        _vector(0),
        search_catalog.alternate,
        filters=search_catalog.filters,
    )
    assert [item.product_id for item in other_version] == [
        search_catalog.products["other-version"].id
    ]
    assert (
        await search_document_vectors(
            session,
            _vector(0),
            E5_SMALL,
            filters=search_catalog.filters,
            document_type=DocumentType.FREQUENTLY_ASKED_QUESTIONS,
        )
        == []
    )


async def test_search_text_uses_query_prefix_and_provider_space(
    session: AsyncSession,
    search_catalog: SearchCatalog,
    embedding_provider_factory,
) -> None:
    provider = embedding_provider_factory("vector-search")
    provider.space = search_catalog.alternate
    search = VectorSearch(EmbeddingService(provider))
    options = VectorSearchOptions(mode="exact", top_k=1)
    products = await search.find_products(
        session, "ноутбук", filters=search_catalog.filters, options=options
    )
    documents = await search.find_documents(
        session, "ноутбук", filters=search_catalog.filters, options=options
    )
    assert [product.product_id for product in products] == [
        search_catalog.products["other-version"].id
    ]
    assert [document.product_id for document in documents] == [
        search_catalog.products["other-version"].id
    ]
    assert provider.calls == [("query: ноутбук",)]


async def test_postgresql_uses_partial_hnsw_indexes_for_both_query_shapes(
    session: AsyncSession,
    search_catalog: SearchCatalog,
) -> None:
    connection = await session.connection()
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    await session.execute(text("SET LOCAL enable_sort = off"))
    await session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))

    for query, index in (
        (product_candidates(_vector(0), E5_SMALL, ProductFilters()), HNSW_INDEXES[0][1]),
        (document_candidates(_vector(0), E5_SMALL, ProductFilters(), None), HNSW_INDEXES[1][1]),
    ):
        for mode in ("hnsw", "exact"):
            statement = rank_by_distance(query, 1, mode)
            compiled = statement.compile(
                dialect=connection.dialect, compile_kwargs={"render_postcompile": True}
            )
            values = (compiled.params[name] for name in compiled.positiontup)
            params = tuple(
                PgVector(value).to_text() if isinstance(value, tuple) else value for value in values
            )
            plan = "\n".join(
                (
                    await connection.exec_driver_sql(
                        f"EXPLAIN (GENERIC_PLAN, COSTS OFF) {compiled}", params
                    )
                ).scalars()
            )
            assert (index in plan) == (mode == "hnsw"), plan

    result = await search_product_vectors(
        session,
        _vector(0),
        E5_SMALL,
        filters=search_catalog.filters,
        options=VectorSearchOptions(top_k=1),
    )
    assert [product.product_id for product in result] == [search_catalog.products["first"].id]


async def test_rebuild_switches_both_predicates_and_keeps_vectors(
    session: AsyncSession,
    search_catalog: SearchCatalog,
) -> None:
    counts = select(
        select(func.count()).select_from(ProductEmbedding).scalar_subquery(),
        select(func.count()).select_from(DocumentChunk).scalar_subquery(),
    )
    before = (await session.execute(counts)).one()
    scope = search_catalog.alternate
    connection = await session.connection()

    await rebuild_vector_indexes(connection, scope.model, scope.version)
    definitions = (
        (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'ix_%_hnsw_cosine'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(definitions) == 2
    assert all(
        scope.version in definition and "vector_cosine_ops" in definition
        for definition in definitions
    )
    assert (await session.execute(counts)).one() == before

    previous_space = await search_product_vectors(
        session, _vector(0), E5_SMALL, filters=search_catalog.filters
    )
    assert [product.product_id for product in previous_space] == [
        search_catalog.products["first"].id,
        search_catalog.products["second"].id,
    ]


async def test_rebuild_restores_index_pair_if_second_creation_fails(
    session: AsyncSession,
    search_catalog: SearchCatalog,
) -> None:
    connection = await session.connection()
    await session.execute(
        text("CREATE INDEX ix_document_chunks_hnsw_cosine_next ON document_chunks (document_id)")
    )
    scope = search_catalog.alternate
    with pytest.raises(DBAPIError, match="already exists"):
        async with connection.begin_nested():
            await rebuild_vector_indexes(connection, scope.model, scope.version)
    definitions = (
        (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'ix_%_hnsw_cosine'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(definitions) == 2
    assert all(E5_SMALL.version in definition for definition in definitions)
    assert (
        await session.scalar(
            text("SELECT to_regclass('public.ix_product_embeddings_hnsw_cosine_next')")
        )
        is None
    )
