from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Numeric, Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.modules.catalog.models import Brand, Category, Product
from app.modules.catalog.schemas import PageQuery, ProductQuery, SpecificationFilter

_PRODUCT_SORTS = {
    "name_asc": Product.name.asc(),
    "name_desc": Product.name.desc(),
    "price_asc": Product.price.asc(),
    "price_desc": Product.price.desc(),
    "rating_desc": Product.rating.desc().nulls_last(),
    "newest": Product.created_at.desc(),
    "stock_desc": Product.stock_quantity.desc(),
}


async def list_categories(session: AsyncSession, query: PageQuery) -> Sequence[Category]:
    statement = select(Category).order_by(Category.name, Category.id)
    return await _fetch_page(session, statement, query)


async def list_brands(session: AsyncSession, query: PageQuery) -> Sequence[Brand]:
    statement = select(Brand).order_by(Brand.name, Brand.id)
    return await _fetch_page(session, statement, query)


async def list_products(session: AsyncSession, query: ProductQuery) -> Sequence[Product]:
    statement = _visible_products()
    if query.category_id is not None or query.category_slug is not None:
        statement = statement.where(Product.category_id.in_(_category_ids(query)))
    if query.brand_id is not None:
        statement = statement.where(Product.brand_id == query.brand_id)
    currency = query.price_currency
    if currency is not None:
        statement = statement.where(Product.currency == currency)
    if query.min_price is not None:
        statement = statement.where(Product.price >= query.min_price)
    if query.max_price is not None:
        statement = statement.where(Product.price <= query.max_price)
    if query.in_stock is not None:
        stock_filter = Product.stock_quantity > 0 if query.in_stock else Product.stock_quantity == 0
        statement = statement.where(stock_filter)
    for specification in query.specification_filters:
        statement = statement.where(_specification_condition(specification))
    statement = statement.order_by(_PRODUCT_SORTS[query.sort], Product.id)
    return await _fetch_page(session, statement, query)


async def get_products_by_id(
    session: AsyncSession, product_ids: Sequence[UUID]
) -> dict[UUID, Product]:
    statement = _visible_products().where(Product.id.in_(product_ids))
    return {product.id: product for product in await session.scalars(statement)}


def _visible_products() -> Select[tuple[Product]]:
    return (
        select(Product)
        .where(Product.is_active.is_(True))
        .options(
            joinedload(Product.category, innerjoin=True), joinedload(Product.brand, innerjoin=True)
        )
    )


async def _fetch_page[T](
    session: AsyncSession, statement: Select[tuple[T]], query: PageQuery
) -> Sequence[T]:
    return (await session.scalars(statement.offset(query.offset).limit(query.limit + 1))).all()


def _category_ids(query: ProductQuery) -> Select[tuple[UUID]]:
    root = select(Category.id)
    if query.category_id is not None:
        root = root.where(Category.id == query.category_id)
    if query.category_slug is not None:
        root = root.where(Category.slug == query.category_slug)
    tree = root.cte("category_tree", recursive=True)
    tree = tree.union(select(Category.id).join(tree, Category.parent_id == tree.c.id))
    return select(tree.c.id)


def _specification_condition(specification: SpecificationFilter) -> ColumnElement[bool]:
    if isinstance(specification.value, str):
        return Product.specifications.contains({specification.key: specification.value})

    raw_value = Product.specifications[specification.key]
    number = case((func.jsonb_typeof(raw_value) == "number", raw_value.astext.cast(Numeric())))
    if specification.operator == "gte":
        return number >= specification.value
    if specification.operator == "lte":
        return number <= specification.value
    return number == specification.value
