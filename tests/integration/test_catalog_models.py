import os
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Numeric, delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.modules.catalog.models import Brand, Category, DocumentType, Product, ProductDocument

database_url = os.environ.get("SHOPPING_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not database_url, reason="SHOPPING_TEST_DATABASE_URL is required for catalog schema tests"
    ),
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url, poolclass=NullPool, connect_args={"timeout": 5})
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def product(session: AsyncSession) -> Product:
    suffix = uuid4().hex
    parent = Category(name="Электроника", slug=f"electronics-{suffix}", description="Электроника")
    category = Category(
        name="Ноутбуки", slug=f"laptops-{suffix}", description="Ноутбуки", parent=parent
    )
    brand = Brand(name=f"Север {suffix}", description="Техника для работы")
    document = ProductDocument(
        document_type=DocumentType.PRODUCT_MANUAL,
        title="Руководство пользователя",
        content="Инструкция для модели Т1.",
        source="catalog/manual/t1",
    )
    product = Product(
        category=category,
        brand=brand,
        name="Север Т1",
        sku=f"T1-{suffix}",
        description="Ноутбук для работы",
        price=Decimal("79999.90"),
        specifications={"ram_gb": 16, "ssd_gb": 512, "display_size_in": 14.5, "cpu": "Тест 1"},
        documents=[document],
    )
    session.add(product)
    await session.flush()
    return product


async def test_catalog_round_trip_and_numeric_filter(
    session: AsyncSession, product: Product
) -> None:
    product_id = product.id
    session.expunge_all()
    ram_gb = Product.specifications["ram_gb"].astext.cast(Numeric)
    query = select(Product).where(Product.id == product_id)

    result = await session.scalar(
        query.where(ram_gb >= 16, Product.price <= Decimal("79999.90")).options(
            selectinload(Product.category).selectinload(Category.parent),
            selectinload(Product.brand),
            selectinload(Product.documents),
        )
    )

    assert result is not None
    assert result.price == Decimal("79999.90")
    assert result.currency == "RUB"
    assert result.stock_quantity == 0
    assert result.is_active is True
    assert result.rating is None
    assert result.created_at.utcoffset() == timedelta(0)
    assert result.category.parent.name == "Электроника"
    assert result.brand.name.startswith("Север")
    assert result.documents[0].document_type is DocumentType.PRODUCT_MANUAL
    assert await session.scalar(query.where(ram_gb >= 32)) is None
    assert await session.scalar(query.where(Product.price < Decimal("79999.90"))) is None


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("price", Decimal("-0.01"), "price_valid"),
        ("price", Decimal("NaN"), "price_valid"),
        ("stock_quantity", -1, "stock_quantity_non_negative"),
        ("currency", "rub", "currency_format"),
        ("rating", Decimal("5.01"), "rating_range"),
        ("specifications", [16], "specifications_object"),
        ("specifications", {"ram_gb": "16"}, "specifications_numeric_values"),
        ("specifications", {"ram_gb": [16]}, "specifications_numeric_values"),
        ("specifications", {"ram_gb": None}, "specifications_numeric_values"),
        ("specifications", {"weight_g": 0}, "specifications_numeric_values"),
    ],
)
async def test_database_rejects_invalid_products(
    session: AsyncSession, product: Product, column: str, value: object, constraint: str
) -> None:
    statement = (
        insert(Product.__table__)
        .values(
            brand_id=product.brand_id,
            category_id=product.category_id,
            name="Север Т2",
            sku=f"{product.sku}-B",
            description="Ноутбук для работы",
            price=product.price,
        )
        .values({column: value})
    )
    with pytest.raises(IntegrityError, match=f"ck_products_{constraint}"):
        await session.execute(statement)


async def test_database_enforces_catalog_references_and_keys(
    session: AsyncSession, product: Product
) -> None:
    for statement, constraint in (
        (delete(Category).where(Category.id == product.category_id), "fk_products_category_id"),
        (delete(Brand).where(Brand.id == product.brand_id), "fk_products_brand_id"),
        (
            update(Category)
            .where(Category.id == product.category_id)
            .values(parent_id=product.category_id),
            "ck_categories_parent_not_self",
        ),
        (
            insert(Product).values(
                category_id=product.category_id,
                brand_id=product.brand_id,
                name=product.name,
                sku=product.sku,
                description=product.description,
                price=product.price,
            ),
            "uq_products_sku",
        ),
        (
            text(
                "INSERT INTO product_documents (product_id, document_type, title, content, source) "
                "VALUES (:product_id, 'invalid', 'Название', 'Текст', 'catalog')"
            ).bindparams(product_id=product.id),
            "ck_product_documents_document_type",
        ),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            async with session.begin_nested():
                await session.execute(statement)


async def test_database_updates_timestamps_and_cascades_document_deletion(
    session: AsyncSession, product: Product
) -> None:
    document = product.documents[0]
    product_updated_at = await session.scalar(
        update(Product)
        .where(Product.id == product.id)
        .values(stock_quantity=3)
        .returning(Product.updated_at)
    )
    document_updated_at = await session.scalar(
        update(ProductDocument)
        .where(ProductDocument.id == document.id)
        .values(title="Руководство по настройке")
        .returning(ProductDocument.updated_at)
    )
    assert product_updated_at > product.created_at
    assert document_updated_at > document.created_at

    await session.execute(delete(Product).where(Product.id == product.id))
    assert (
        await session.scalar(select(ProductDocument.id).where(ProductDocument.id == document.id))
        is None
    )


async def test_api_role_can_read_catalog_but_cannot_write(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL ROLE shopping_app"))
    for model in (Category, Brand, Product, ProductDocument):
        await session.execute(select(model.id).limit(1))
        cannot_write = await session.scalar(
            text(
                "SELECT NOT has_table_privilege(current_user, :table, "
                "'INSERT, UPDATE, DELETE, TRUNCATE')"
            ),
            {"table": model.__tablename__},
        )
        assert cannot_write

    with pytest.raises(DBAPIError, match="permission denied for table products"):
        await session.execute(text("UPDATE products SET stock_quantity = 0 WHERE false"))
