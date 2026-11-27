from decimal import Decimal
from math import isfinite
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import NUMERIC_SPECIFICATION_KEYS, Brand, Category, Product


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    name: Annotated[str, Field(min_length=1, max_length=250)]
    category_slug: Annotated[str, Field(min_length=1, max_length=120)]
    brand_name: Annotated[str, Field(min_length=1, max_length=200)]
    description: str
    price: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "RUB"
    stock_quantity: Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)] = 0
    specifications: dict[str, JsonValue] = Field(default_factory=dict)
    rating: Annotated[Decimal, Field(ge=0, le=5, decimal_places=2)] | None = None
    is_active: Annotated[bool, Field(strict=True)] = True

    @field_validator("specifications")
    @classmethod
    def validate_numeric_specifications(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        for key in value.keys() & set(NUMERIC_SPECIFICATION_KEYS):
            number = value[key]
            if (
                type(number) not in (int, float)
                or number <= 0
                or (isinstance(number, float) and not isfinite(number))
            ):
                raise ValueError(f"Поле {key} должно содержать положительное число.")
        return value


async def read_product(session: AsyncSession, sku: str) -> dict[str, Any]:
    product, category_slug, brand_name = await _find_product(session, sku)
    return _product_payload(product, category_slug, brand_name)


async def save_product(
    session: AsyncSession, sku: str, payload: dict[str, Any], *, update_existing: bool
) -> dict[str, Any]:
    if update_existing:
        product, category_slug, brand_name = await _find_product(session, sku, lock=True)
        payload = _product_payload(product, category_slug, brand_name) | payload
    else:
        product = Product(sku=sku)

    values = ProductInput.model_validate(payload)
    category_id = await session.scalar(
        select(Category.id).where(Category.slug == values.category_slug)
    )
    if category_id is None:
        raise ValueError(f"Категория {values.category_slug} отсутствует в каталоге.")
    brand_id = await session.scalar(select(Brand.id).where(Brand.name == values.brand_name))
    if brand_id is None:
        raise ValueError(f"Бренд {values.brand_name} отсутствует в каталоге.")

    product.category_id = category_id
    product.brand_id = brand_id
    for key, value in values.model_dump(exclude={"category_slug", "brand_name"}).items():
        setattr(product, key, value)
    if not update_existing:
        session.add(product)
    await session.flush()
    return _product_payload(product, values.category_slug, values.brand_name)


async def delete_product(session: AsyncSession, sku: str) -> None:
    deleted = await session.scalar(delete(Product).where(Product.sku == sku).returning(Product.id))
    if deleted is None:
        raise ValueError(f"Товар с артикулом {sku} отсутствует в каталоге.")


async def _find_product(
    session: AsyncSession, sku: str, *, lock: bool = False
) -> tuple[Product, str, str]:
    statement = (
        select(Product, Category.slug, Brand.name)
        .join(Category, Product.category_id == Category.id)
        .join(Brand, Product.brand_id == Brand.id)
        .where(Product.sku == sku)
    )
    if lock:
        statement = statement.with_for_update(of=Product)
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise ValueError(f"Товар с артикулом {sku} отсутствует в каталоге.")
    product, category_slug, brand_name = row
    return product, category_slug, brand_name


def _product_payload(product: Product, category_slug: str, brand_name: str) -> dict[str, Any]:
    return {
        "name": product.name,
        "category_slug": category_slug,
        "brand_name": brand_name,
        "description": product.description,
        "price": product.price,
        "currency": product.currency,
        "stock_quantity": product.stock_quantity,
        "specifications": product.specifications,
        "rating": product.rating,
        "is_active": product.is_active,
    }
