from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import Row, Select, String, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.ai.embeddings.models import DocumentChunk, ProductEmbedding
from app.ai.embeddings.service import (
    EMBEDDING_DIMENSIONS,
    EmbeddingService,
    EmbeddingSpace,
    validate_vector,
)
from app.modules.catalog.models import DocumentType, Product, ProductDocument
from app.modules.catalog.repository import product_conditions
from app.modules.catalog.schemas import ProductFilters

type SearchMode = Literal["exact", "hnsw"]


@dataclass(frozen=True, slots=True)
class VectorSearchOptions:
    top_k: int = 10
    mode: SearchMode = "hnsw"
    ef_search: int = 100

    def __post_init__(self) -> None:
        if self.mode not in ("exact", "hnsw"):
            raise ValueError("Укажите режим exact или hnsw.")
        if type(self.top_k) is not int or not 1 <= self.top_k <= 100:
            raise ValueError("top_k должен быть целым числом от 1 до 100.")
        if type(self.ef_search) is not int or not 1 <= self.ef_search <= 1000:
            raise ValueError("ef_search должен быть целым числом от 1 до 1000.")


DEFAULT_OPTIONS = VectorSearchOptions()


@dataclass(frozen=True, slots=True)
class ProductMatch:
    product_id: UUID
    distance: float


@dataclass(frozen=True, slots=True)
class DocumentMatch:
    chunk_id: UUID
    product_id: UUID
    document_id: UUID
    document_type: DocumentType
    chunk_index: int
    title: str
    source: str
    content: str
    distance: float


class VectorSearch:
    def __init__(self, embeddings: EmbeddingService) -> None:
        self.embeddings = embeddings

    async def find_products(
        self,
        session: AsyncSession,
        query: str,
        *,
        filters: ProductFilters | None = None,
        options: VectorSearchOptions = DEFAULT_OPTIONS,
    ) -> list[ProductMatch]:
        if not query.strip():
            raise ValueError("Поисковый запрос пуст.")
        vector = await self.embeddings.encode_query(query)
        return await search_product_vectors(
            session, vector, self.embeddings.space, filters=filters, options=options
        )

    async def find_documents(
        self,
        session: AsyncSession,
        query: str,
        *,
        filters: ProductFilters | None = None,
        document_type: DocumentType | None = None,
        options: VectorSearchOptions = DEFAULT_OPTIONS,
    ) -> list[DocumentMatch]:
        if not query.strip():
            raise ValueError("Поисковый запрос пуст.")
        vector = await self.embeddings.encode_query(query)
        return await search_document_vectors(
            session,
            vector,
            self.embeddings.space,
            filters=filters,
            document_type=document_type,
            options=options,
        )


async def search_product_vectors(
    session: AsyncSession,
    query_vector: Sequence[float],
    space: EmbeddingSpace,
    *,
    filters: ProductFilters | None = None,
    options: VectorSearchOptions = DEFAULT_OPTIONS,
) -> list[ProductMatch]:
    statement = product_candidates(query_vector, space, filters or ProductFilters())
    return [ProductMatch(*row) for row in await _fetch_neighbors(session, statement, options)]


async def search_document_vectors(
    session: AsyncSession,
    query_vector: Sequence[float],
    space: EmbeddingSpace,
    *,
    filters: ProductFilters | None = None,
    document_type: DocumentType | None = None,
    options: VectorSearchOptions = DEFAULT_OPTIONS,
) -> list[DocumentMatch]:
    statement = document_candidates(query_vector, space, filters or ProductFilters(), document_type)
    return [DocumentMatch(*row) for row in await _fetch_neighbors(session, statement, options)]


def product_candidates(
    query_vector: Sequence[float], space: EmbeddingSpace, filters: ProductFilters
) -> Select:
    distance = ProductEmbedding.embedding.cosine_distance(_query_vector(query_vector, space))
    return (
        select(ProductEmbedding.product_id, distance.label("distance"))
        .join(Product, Product.id == ProductEmbedding.product_id)
        .where(*_space_conditions(ProductEmbedding, space), *product_conditions(filters))
    )


def document_candidates(
    query_vector: Sequence[float],
    space: EmbeddingSpace,
    filters: ProductFilters,
    document_type: DocumentType | None,
) -> Select:
    distance = DocumentChunk.embedding.cosine_distance(_query_vector(query_vector, space))
    statement = (
        select(
            DocumentChunk.id,
            ProductDocument.product_id,
            DocumentChunk.document_id,
            ProductDocument.document_type,
            DocumentChunk.chunk_index,
            ProductDocument.title,
            ProductDocument.source,
            DocumentChunk.content,
            distance.label("distance"),
        )
        .join(ProductDocument, ProductDocument.id == DocumentChunk.document_id)
        .join(Product, Product.id == ProductDocument.product_id)
        .where(*_space_conditions(DocumentChunk, space), *product_conditions(filters))
    )
    if document_type is not None:
        return statement.where(ProductDocument.document_type == document_type)
    return statement


def _query_vector(query_vector: Sequence[float], space: EmbeddingSpace) -> tuple[float, ...]:
    if space.dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Размерность пространства поиска должна составлять {EMBEDDING_DIMENSIONS}."
        )
    return validate_vector(query_vector, space.dimensions)


def _space_conditions(
    entity: type[ProductEmbedding] | type[DocumentChunk],
    space: EmbeddingSpace,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    # A generic prepared plan must be able to prove the partial index predicate.
    return (
        entity.embedding_model == literal(space.model, String(), literal_execute=True),
        entity.embedding_version == literal(space.version, String(), literal_execute=True),
    )


def rank_by_distance(statement: Select, top_k: int, mode: SearchMode) -> Select:
    distance = statement.selected_columns["distance"]
    if mode == "exact":
        # Wrapping the operator excludes the approximate index access path.
        return statement.order_by(distance + 0.0, statement.selected_columns[0]).limit(top_k)
    return statement.order_by(distance).limit(top_k)


async def _fetch_neighbors(
    session: AsyncSession,
    statement: Select,
    options: VectorSearchOptions,
) -> Sequence[Row]:
    if options.mode == "hnsw":
        await session.execute(
            select(
                func.set_config("hnsw.iterative_scan", "strict_order", True),
                func.set_config("hnsw.ef_search", str(options.ef_search), True),
            )
        )
        rows = (await session.execute(rank_by_distance(statement, options.top_k, "hnsw"))).all()
        if len(rows) == options.top_k:
            return sorted(rows, key=lambda row: (row[-1], row[0]))

    return (await session.execute(rank_by_distance(statement, options.top_k, "exact"))).all()
