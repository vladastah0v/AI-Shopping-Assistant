import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    field_validator,
    model_validator,
)

from app.modules.catalog.models import NUMERIC_SPECIFICATION_KEYS

_NUMERIC_KEYS = frozenset(
    (*NUMERIC_SPECIFICATION_KEYS, "depth_mm", "freezer_volume_l", "spin_speed_rpm")
)
_TEXT_KEYS = frozenset(
    (
        "cpu",
        "gpu",
        "os",
        "panel",
        "connection",
        "form_factor",
        "noise_cancellation",
        "component_type",
        "interface",
        "defrost_type",
        "appliance_type",
    )
)

type ProductSort = Literal[
    "name_asc", "name_desc", "price_asc", "price_desc", "rating_desc", "newest", "stock_desc"
]
type SpecificationOperator = Literal["eq", "gte", "lte"]
type Price = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]


@dataclass(frozen=True, slots=True)
class SpecificationFilter:
    key: str
    operator: SpecificationOperator
    value: Decimal | str


def _parse_specification_filter(raw: str) -> SpecificationFilter:
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise ValueError("Укажите характеристику в формате ключ:оператор:значение.")
    key, operator, value = parts
    if operator not in ("eq", "gte", "lte") or not value.strip():
        raise ValueError("Укажите оператор eq, gte или lte и непустое значение характеристики.")
    if key in _NUMERIC_KEYS:
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None:
            raise ValueError(f"Для характеристики {key} укажите неотрицательное десятичное число.")
        return SpecificationFilter(key, operator, Decimal(value))
    if key in _TEXT_KEYS and operator == "eq":
        return SpecificationFilter(key, "eq", value)
    raise ValueError(f"Характеристика {key} или её оператор недоступны для фильтрации.")


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(
        default=20, ge=1, le=100, description="Максимальное число записей на странице."
    )
    offset: int = Field(default=0, ge=0, le=2**31 - 1, description="Число записей перед страницей.")


class ProductQuery(PageQuery):
    category_id: UUID | None = Field(
        default=None, description="UUID категории. Подкатегории включаются."
    )
    category_slug: str | None = Field(
        default=None,
        max_length=120,
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="Код категории. Подкатегории включаются.",
    )
    brand_id: UUID | None = Field(default=None, description="UUID бренда.")
    min_price: Price | None = Field(default=None, description="Минимальная цена включительно.")
    max_price: Price | None = Field(default=None, description="Максимальная цена включительно.")
    currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="Код валюты. Для операций с ценой по умолчанию используется RUB.",
    )
    in_stock: bool | None = Field(
        default=None, description="true — в наличии, false — без остатка."
    )
    sort: ProductSort = Field(default="name_asc", description="Порядок сортировки товаров.")
    spec: list[Annotated[str, Field(max_length=160)]] = Field(
        default_factory=list,
        max_length=12,
        description="Фильтры по характеристикам. Примеры ram_gb:gte:16 и os:eq:Linux. Параметр можно повторять.",
    )

    _specification_filters: tuple[SpecificationFilter, ...] = PrivateAttr(default=())

    @model_validator(mode="after")
    def validate_filters(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("Минимальная цена превышает максимальную.")
        self._specification_filters = tuple(map(_parse_specification_filter, self.spec))
        return self

    @property
    def specification_filters(self) -> tuple[SpecificationFilter, ...]:
        return self._specification_filters

    @property
    def price_currency(self) -> str | None:
        if self.currency is None and (
            self.min_price is not None
            or self.max_price is not None
            or self.sort in ("price_asc", "price_desc")
        ):
            return "RUB"
        return self.currency


class CatalogPage[T](BaseModel):
    items: list[T]
    limit: int
    offset: int
    has_more: bool


class BrandSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class BrandRead(BrandSummary):
    description: str


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str


class CategoryRead(CategorySummary):
    description: str
    parent_id: UUID | None


class ProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    category: CategorySummary
    brand: BrandSummary
    price: Decimal
    currency: str
    stock_quantity: int
    rating: Decimal | None


class ProductRead(ProductSummary):
    description: str
    specifications: dict[str, JsonValue]


class ProductSpecifications(BaseModel):
    product_id: UUID
    specifications: dict[str, JsonValue]


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID] = Field(
        min_length=2, max_length=5, description="От двух до пяти разных UUID товаров."
    )

    @field_validator("product_ids")
    @classmethod
    def validate_unique_ids(cls, ids: list[UUID]) -> list[UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("Укажите разные товары для сравнения.")
        return ids


class ComparisonResponse(BaseModel):
    products: list[ProductSummary]
    specifications: dict[str, list[JsonValue]] = Field(
        description="Значения в том же порядке, что и товары."
    )


class CatalogError(BaseModel):
    detail: str
