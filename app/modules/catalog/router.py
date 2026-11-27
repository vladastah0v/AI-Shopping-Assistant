import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from asyncpg import PostgresConnectionError
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog import repository
from app.modules.catalog.models import Product
from app.modules.catalog.schemas import (
    BrandRead,
    CatalogError,
    CatalogPage,
    CategoryRead,
    ComparisonRequest,
    ComparisonResponse,
    PageQuery,
    ProductQuery,
    ProductRead,
    ProductSpecifications,
    ProductSummary,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Каталог"],
    responses={503: {"model": CatalogError, "description": "Каталог временно недоступен."}},
)
_NOT_FOUND = {404: {"model": CatalogError, "description": "Товар не найден в публичном каталоге."}}


@asynccontextmanager
async def catalog_session(request: Request, *, timeout: float) -> AsyncIterator[AsyncSession]:
    state = request.app.state
    try:
        async with (
            AsyncSession(state.database_engine) as session,
            asyncio.timeout(timeout),
        ):
            yield session
    except (DBAPIError, PostgresConnectionError, PoolTimeoutError, OSError) as error:
        if isinstance(error, DBAPIError) and not (
            error.connection_invalidated or isinstance(error, (InterfaceError, OperationalError))
        ):
            raise
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Каталог временно недоступен."
        ) from error


async def _catalog_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with catalog_session(
        request, timeout=request.app.state.dependency_timeout_seconds
    ) as session:
        yield session


type CatalogSession = Annotated[AsyncSession, Depends(_catalog_session, scope="function")]
type ProductId = Annotated[UUID, Path(description="UUID товара.")]


def _page[T](
    page_type: type[CatalogPage[T]], rows: Sequence[object], query: PageQuery
) -> CatalogPage[T]:
    return page_type.model_validate(
        {
            "items": rows[: query.limit],
            "limit": query.limit,
            "offset": query.offset,
            "has_more": len(rows) > query.limit,
        }
    )


@router.get("/categories", summary="Получить категории каталога")
async def list_categories(
    query: Annotated[PageQuery, Query()], session: CatalogSession
) -> CatalogPage[CategoryRead]:
    return _page(CatalogPage[CategoryRead], await repository.list_categories(session, query), query)


@router.get("/brands", summary="Получить бренды каталога")
async def list_brands(
    query: Annotated[PageQuery, Query()], session: CatalogSession
) -> CatalogPage[BrandRead]:
    return _page(CatalogPage[BrandRead], await repository.list_brands(session, query), query)


@router.get("/products", summary="Получить товары с фильтрацией и сортировкой")
async def list_products(
    query: Annotated[ProductQuery, Query()], session: CatalogSession
) -> CatalogPage[ProductSummary]:
    return _page(CatalogPage[ProductSummary], await repository.list_products(session, query), query)


@router.post(
    "/products/compare", summary="Сравнить товары по характеристикам", responses=_NOT_FOUND
)
async def compare_products(body: ComparisonRequest, session: CatalogSession) -> ComparisonResponse:
    found = await repository.get_products_by_id(session, body.product_ids)
    if len(found) != len(body.product_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Один или несколько товаров не найдены.")
    products = [found[product_id] for product_id in body.product_ids]
    keys = sorted({key for product in products for key in product.specifications})
    return ComparisonResponse(
        products=[ProductSummary.model_validate(product) for product in products],
        specifications={
            key: [product.specifications.get(key) for product in products] for key in keys
        },
    )


async def _get_product(session: AsyncSession, product_id: UUID) -> Product:
    product = (await repository.get_products_by_id(session, (product_id,))).get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Товар не найден.")
    return product


@router.get("/products/{id}", summary="Получить карточку товара", responses=_NOT_FOUND)
async def get_product(id: ProductId, session: CatalogSession) -> ProductRead:
    return ProductRead.model_validate(await _get_product(session, id))


@router.get(
    "/products/{id}/specifications",
    summary="Получить технические характеристики товара",
    responses=_NOT_FOUND,
)
async def get_product_specifications(
    id: ProductId, session: CatalogSession
) -> ProductSpecifications:
    product = await _get_product(session, id)
    return ProductSpecifications(product_id=product.id, specifications=product.specifications)
