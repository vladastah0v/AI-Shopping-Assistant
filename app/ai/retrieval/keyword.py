from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.models import (
    SEARCH_CONFIGURATION,
    SEARCH_TRANSLATION_FROM,
    SEARCH_TRANSLATION_TO,
    SKU_SEPARATOR_PATTERN,
    DocumentType,
    Product,
    ProductDocument,
)
from app.modules.catalog.repository import product_conditions
from app.modules.catalog.schemas import ProductFilters

_SEARCH_TRANSLATION = str.maketrans(SEARCH_TRANSLATION_FROM, SEARCH_TRANSLATION_TO)


@dataclass(frozen=True, slots=True)
class KeywordProductMatch:
    product_id: UUID
    score: float


@dataclass(frozen=True, slots=True)
class KeywordDocumentMatch:
    document_id: UUID
    product_id: UUID
    document_type: DocumentType
    title: str
    source: str
    score: float


async def search_products_by_keywords(
    session: AsyncSession,
    query: str,
    *,
    filters: ProductFilters | None = None,
    top_k: int = 10,
) -> list[KeywordProductMatch]:
    statement = product_keyword_statement(query, filters or ProductFilters(), top_k)
    return [KeywordProductMatch(*row) for row in await session.execute(statement)]


async def search_documents_by_keywords(
    session: AsyncSession,
    query: str,
    *,
    filters: ProductFilters | None = None,
    document_type: DocumentType | None = None,
    top_k: int = 10,
) -> list[KeywordDocumentMatch]:
    statement = document_keyword_statement(query, filters or ProductFilters(), document_type, top_k)
    return [KeywordDocumentMatch(*row) for row in await session.execute(statement)]


def product_keyword_statement(query: str, filters: ProductFilters, top_k: int) -> Select:
    query = _validate_query(query, top_k)
    terms = _search_terms(query)
    normalized_sku = func.regexp_replace(func.lower(query), SKU_SEPARATOR_PATTERN, "", "g")
    sku_match = (normalized_sku != "") & (Product.search_sku == normalized_sku)
    score = case(
        (sku_match & (func.lower(Product.sku) == func.lower(query)), 2.0),
        (sku_match, 1.0),
        else_=func.ts_rank_cd(Product.search_vector, terms, 32),
    ).label("score")
    return (
        select(Product.id, score)
        .where(
            *product_conditions(filters), or_(sku_match, Product.search_vector.bool_op("@@")(terms))
        )
        .order_by(score.desc(), Product.id)
        .limit(top_k)
    )


def document_keyword_statement(
    query: str,
    filters: ProductFilters,
    document_type: DocumentType | None,
    top_k: int,
) -> Select:
    terms = _search_terms(_validate_query(query, top_k))
    score = func.ts_rank_cd(ProductDocument.search_vector, terms, 32).label("score")
    statement = (
        select(
            ProductDocument.id,
            Product.id,
            ProductDocument.document_type,
            ProductDocument.title,
            ProductDocument.source,
            score,
        )
        .join(Product, Product.id == ProductDocument.product_id)
        .where(*product_conditions(filters), ProductDocument.search_vector.bool_op("@@")(terms))
        .order_by(score.desc(), ProductDocument.id)
        .limit(top_k)
    )
    if document_type is not None:
        return statement.where(ProductDocument.document_type == document_type)
    return statement


def _search_terms(query: str) -> ColumnElement:
    return func.plainto_tsquery(
        literal_column(SEARCH_CONFIGURATION), query.translate(_SEARCH_TRANSLATION)
    )


def _validate_query(query: str, top_k: int) -> str:
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError("top_k должен быть целым числом от 1 до 100.")
    query = query.strip()
    if not query or len(query) > 512 or "\x00" in query:
        raise ValueError("Укажите поисковый запрос длиной от 1 до 512 символов без нулевых байтов.")
    return query
