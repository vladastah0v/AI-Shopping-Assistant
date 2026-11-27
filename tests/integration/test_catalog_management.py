from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.admin import delete_product, read_product, save_product
from app.modules.catalog.models import Brand, Category, Product, ProductDocument
from app.modules.catalog.seeding import SeedResult, seed_catalog
from app.modules.catalog.synthetic import generate_products

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def product_input(session: AsyncSession) -> dict[str, object]:
    suffix = uuid4().hex
    category = Category(name="Тестовые товары", slug=f"test-{suffix}", description="")
    brand = Brand(name=f"Тестовый бренд {suffix}", description="")
    session.add_all([category, brand])
    await session.flush()
    return {
        "category_slug": category.slug,
        "brand_name": brand.name,
        "name": "Тестовый товар",
        "description": "Описание товара",
        "price": "12990.40",
        "specifications": {"ram_gb": 16},
    }


async def test_product_admin_crud(session: AsyncSession, product_input: dict[str, object]) -> None:
    sku = f"TEST-{uuid4().hex}"
    created = await save_product(session, sku, product_input, update_existing=False)
    assert created["price"] == Decimal("12990.40")
    assert await read_product(session, sku) == created

    changed = await save_product(
        session,
        sku,
        {"price": "12345.67", "stock_quantity": 4, "is_active": False},
        update_existing=True,
    )
    assert changed == created | {
        "price": Decimal("12345.67"),
        "stock_quantity": 4,
        "is_active": False,
    }
    assert await read_product(session, sku) == changed

    await delete_product(session, sku)
    with pytest.raises(ValueError, match="отсутствует в каталоге"):
        await read_product(session, sku)


async def test_seed_is_idempotent_and_extends_the_same_catalog(session: AsyncSession) -> None:
    seed = 8401734952
    first_product = next(generate_products(1, seed)).values
    sku = first_product["sku"]

    small = await seed_catalog(session, "small", seed)
    assert (small.products, small.documents) == (100, 400)
    await save_product(
        session, sku, {"price": "55123.00", "is_active": False}, update_existing=True
    )
    modified_at = await session.scalar(select(Product.updated_at).where(Product.sku == sku))

    assert await seed_catalog(session, "small", seed) == SeedResult()
    medium = await seed_catalog(session, "medium", seed)
    assert medium == SeedResult(products=900, documents=3600)
    assert await session.scalar(select(Product.updated_at).where(Product.sku == sku)) == modified_at
    assert await session.scalar(select(Product.id).where(Product.sku == sku)) == first_product["id"]
    original = await read_product(session, sku)
    assert original["price"] == Decimal("55123.00")
    assert original["is_active"] is False


async def test_seed_conflict_rolls_back_preceding_inserts(
    session: AsyncSession, product_input: dict[str, object]
) -> None:
    seed = 9934729461
    sku = f"SYN-{seed:X}-00100"
    await save_product(session, sku, product_input, update_existing=False)
    before = await read_product(session, sku)
    counts = select(
        select(func.count()).select_from(Category).scalar_subquery(),
        select(func.count()).select_from(Brand).scalar_subquery(),
        select(func.count()).select_from(Product).scalar_subquery(),
        select(func.count()).select_from(ProductDocument).scalar_subquery(),
    )
    before_counts = (await session.execute(counts)).one()

    with pytest.raises(ValueError, match=sku):
        async with session.begin_nested():
            await seed_catalog(session, "small", seed)

    assert (await session.execute(counts)).one() == before_counts
    assert await read_product(session, sku) == before
